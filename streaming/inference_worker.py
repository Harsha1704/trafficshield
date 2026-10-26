"""
Streaming Inference Worker & Alert Pipeline Integration
========================================================
Milestone 14 — Real-Time Network Detection & Flow Reconstruction

Consumes finalized unidirectional flow records, executes inference via the frozen
production model service, records evidence explanations, and writes persistent
SOC security alerts with strict source provenance tracking.

Non-negotiable invariants:
- Uses the frozen ProductionInferenceService exclusively (zero model divergence).
- Strict source provenance: 'PCAP_REPLAY' or 'LIVE_CAPTURE' (never mislabeled).
- Zero raw packet payload logging.
- Deduplication of high-frequency alerts to prevent SOC alert fatigue.
- Bounded memory circular buffer of recent detections for real-time dashboard UI.
"""
from __future__ import annotations

import collections
import logging
import queue
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from app.database.models import SecurityAlert
from app.extensions import db
from ml.production_service import ProductionInferenceService

logger = logging.getLogger("inference_worker")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class StreamingInferenceWorker:
    """
    Decoupled background worker executing real-time inference on finalized flow vectors.
    Connects detections to persistent database alerts and maintains real-time UI buffer.
    """

    def __init__(
        self,
        flow_queue: queue.Queue[dict[str, Any] | None],
        inference_service: ProductionInferenceService,
        app: Any = None,
        source_provenance: str = "PCAP_REPLAY",
        recent_buffer_size: int = 200,
        decision_threshold: float = 0.50,
    ) -> None:
        self.flow_queue = flow_queue
        self.service = inference_service
        self.app = app
        self.source_provenance = source_provenance
        self.decision_threshold = decision_threshold

        self._stop_event = threading.Event()
        self._drain_requested = threading.Event()
        self._lock = threading.Lock()
        self._stop_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._is_running = False

        # Lifecycle and shutdown diagnostic flags
        self.drain_timed_out = False
        self.forced_stop = False
        self.thread_hung = False
        self.sentinel_inserted = False

        # In-memory circular buffer for low-latency dashboard streaming
        self.recent_events: collections.deque[dict[str, Any]] = collections.deque(
            maxlen=recent_buffer_size
        )

        # Operational telemetry counters
        self.flows_scored = 0
        self.anomalies_detected = 0
        self.alerts_persisted = 0
        self.validation_errors = 0
        self.inference_failures = 0
        self.persistence_failures = 0
        self.incompatible_flows_rejected = 0
        self.unprocessed_flows = 0
        self.inference_latencies_ms: list[float] = []

        # Deduplication cache: key -> last_alert_time
        self._dedup_cache: dict[str, float] = {}
        self._dedup_window_seconds = 10.0

    @property
    def is_running(self) -> bool:
        return (
            self._is_running
            and not self._stop_event.is_set()
            and (self._thread is not None and self._thread.is_alive())
        )

    def start(self) -> None:
        """Start inference worker thread."""
        with self._lock:
            if self._is_running and self._thread is not None and self._thread.is_alive():
                return
            self._is_running = True
            self.drain_timed_out = False
            self.forced_stop = False
            self.thread_hung = False
            self.sentinel_inserted = False
            self._stop_event.clear()
            self._drain_requested.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="StreamingInferenceWorker",
                daemon=True,
            )
            self._thread.start()
            logger.info(
                "Streaming inference worker started (provenance: %s, threshold: %.2f)",
                self.source_provenance,
                self.decision_threshold,
            )

    def stop(self, drain_timeout: float = 5.0) -> None:
        """
        Gracefully signal worker to drain remaining queued flows and terminate within timeout.
        If drain_timeout expires before queue is emptied, worker is forced to stop
        and any remaining flows are accounted for in self.unprocessed_flows.
        """
        with self._stop_lock:
            with self._lock:
                if not self._is_running and (self._thread is None or not self._thread.is_alive()):
                    return
                self._is_running = False
                self._drain_requested.set()

            # Enqueue sentinel None to mark the end of queued work.
            # If queue is full, wait up to min(drain_timeout, 2.0) for worker to drain a slot.
            t_start = time.monotonic()
            sentinel_wait = min(max(drain_timeout, 0.1), 2.0)
            self.sentinel_inserted = False

            while (time.monotonic() - t_start) < sentinel_wait:
                if self._thread is None or not self._thread.is_alive():
                    break
                try:
                    self.flow_queue.put(None, timeout=0.05)
                    self.sentinel_inserted = True
                    break
                except queue.Full:
                    continue

            if not self.sentinel_inserted:
                logger.warning("Could not insert sentinel (queue full or worker dead); forcing stop.")
                self.forced_stop = True
                self._stop_event.set()

            # Wait for worker thread to drain all queued flows up to the sentinel
            if self._thread and self._thread.is_alive():
                remaining_wait = max(0.05, drain_timeout - (time.monotonic() - t_start))
                self._thread.join(timeout=remaining_wait)
                if self._thread.is_alive():
                    logger.warning(
                        "Worker thread did not terminate within drain timeout (%.1fs). Forcing stop.",
                        drain_timeout,
                    )
                    self.drain_timed_out = True
                    self.forced_stop = True
                    self._stop_event.set()
                    self._thread.join(timeout=2.0)
                    if self._thread.is_alive():
                        self.thread_hung = True

            # Count any remaining unprocessed flows in queue (excluding sentinels)
            unprocessed = 0
            while not self.flow_queue.empty():
                try:
                    item = self.flow_queue.get_nowait()
                    if item is not None:
                        unprocessed += 1
                    self.flow_queue.task_done()
                except (queue.Empty, ValueError):
                    break
            self.unprocessed_flows += unprocessed

            if self.unprocessed_flows > 0:
                logger.warning(
                    "Worker stopped with %d unprocessed flows remaining in queue.",
                    self.unprocessed_flows,
                )
            else:
                logger.info(
                    "Streaming inference worker stopped gracefully (flows scored: %d)",
                    self.flows_scored,
                )

    def _run_loop(self) -> None:
        """
        Worker consumption loop with graceful queue draining.
        Processes incoming flows until sentinel (None) is reached or hard stop is signaled.
        """
        try:
            while not self._stop_event.is_set():
                try:
                    flow = self.flow_queue.get(timeout=0.1)
                    if flow is None:  # Sentinel reached
                        self.flow_queue.task_done()
                        break
                    try:
                        self._score_flow(flow)
                    finally:
                        self.flow_queue.task_done()
                except queue.Empty:
                    if self._drain_requested.is_set() and self.flow_queue.empty():
                        break
                    continue
                except Exception as exc:
                    logger.error("Unexpected error in streaming inference loop: %s", exc)
        finally:
            with self._lock:
                self._is_running = False

    def _score_flow(self, flow: dict[str, Any]) -> None:
        """Score a single finalized flow and persist alerts if anomalous."""
        t0 = time.perf_counter()
        flow_id = flow.get("flow_id", "unknown")

        # Incompatible flows (e.g. invalid STTL, unsupported transport) are rejected from inference
        if not flow.get("is_compatible", True):
            self.incompatible_flows_rejected += 1
            logger.info("Rejected incompatible flow from inference: %s (%s)", flow_id, flow.get("compatibility_reason"))
            return

        try:
            # Score using frozen production inference service
            res = self.service.predict_single(flow)
            t_infer = (time.perf_counter() - t0) * 1000.0

            anomaly_score = float(res["anomaly_score"])
            is_anomaly = anomaly_score >= self.decision_threshold
            risk_level = res.get("risk_level", "LOW")
            top_features = res.get("top_contributing_features", [])

            self.flows_scored += 1
            if is_anomaly:
                self.anomalies_detected += 1

            self.inference_latencies_ms.append(t_infer)
            if len(self.inference_latencies_ms) > 1000:
                self.inference_latencies_ms = self.inference_latencies_ms[-500:]

            event_id = str(uuid.uuid4())
            timestamp_iso = _utcnow().isoformat()

            event_record = {
                "event_id": event_id,
                "timestamp": timestamp_iso,
                "flow_id": flow_id,
                "src_ip": flow.get("src_ip"),
                "dst_ip": flow.get("dst_ip"),
                "src_port": flow.get("src_port"),
                "dst_port": flow.get("dst_port"),
                "protocol": flow.get("protocol"),
                "source_provenance": self.source_provenance,
                "anomaly_score": round(anomaly_score, 4),
                "decision_threshold": self.decision_threshold,
                "is_anomaly": is_anomaly,
                "risk_level": risk_level,
                "inference_latency_ms": round(t_infer, 2),
                "model_name": self.service.model_name,
                "model_version": self.service.version,
                "top_features": top_features,
                "is_provisional": False,
            }

            self.recent_events.append(event_record)

            # Persist alert if anomalous and within database context
            if is_anomaly and self.app:
                self._persist_alert(flow, event_record)

        except Exception as exc:
            if isinstance(exc, (ValueError, KeyError)):
                self.validation_errors += 1
            else:
                self.inference_failures += 1
            logger.warning("Flow scoring exception for %s: %s", flow_id, exc)

    def _persist_alert(self, flow: dict[str, Any], event_record: dict[str, Any]) -> None:
        """Deduplicate and insert SecurityAlert record in SQLite/PostgreSQL."""
        dedup_key = f"{flow.get('src_ip')}:{flow.get('dst_ip')}:{flow.get('dst_port')}:{flow.get('protocol')}"
        now = time.time()
        last_seen = self._dedup_cache.get(dedup_key, 0.0)

        # Skip duplicate database write if identical pattern alerted within window
        if (now - last_seen) < self._dedup_window_seconds:
            return

        self._dedup_cache[dedup_key] = now
        # Clean cache if growing large
        if len(self._dedup_cache) > 2000:
            self._dedup_cache = {k: v for k, v in self._dedup_cache.items() if (now - v) < 60.0}

        try:
            with self.app.app_context():
                alert = SecurityAlert(
                    request_id=event_record["event_id"],
                    timestamp=_utcnow(),
                    is_anomaly=True,
                    anomaly_score=event_record["anomaly_score"],
                    decision_threshold=self.decision_threshold,
                    risk_level=event_record["risk_level"],
                    model_name=self.service.model_name,
                    model_version=self.service.version,
                    status="NEW",
                    analyst_notes=f"Real-time streaming detection from {self.source_provenance}.",
                    input_features={
                        k: flow.get(k)
                        for k in [
                            "duration_seconds",
                            "fwd_bytes",
                            "sttl",
                            "sload",
                            "fwd_packets",
                            "swin",
                            "smeansz",
                            "sjit",
                            "sintpkt",
                            "is_sm_ips_ports",
                        ]
                    },
                    top_contributing_features=event_record.get("top_features"),
                    protocol=flow.get("protocol"),
                    src_port=flow.get("src_port"),
                    dst_port=flow.get("dst_port"),
                    is_demo=False,
                    source=self.source_provenance,
                )
                db.session.add(alert)
                db.session.commit()
                self.alerts_persisted += 1
        except Exception as exc:
            self.persistence_failures += 1
            logger.error("Failed to persist streaming SecurityAlert: %s", exc)
            try:
                with self.app.app_context():
                    db.session.rollback()
            except Exception:
                pass

    def get_metrics(self) -> dict[str, Any]:
        """Telemetry metrics for the streaming inference worker."""
        mean_lat = (
            sum(self.inference_latencies_ms) / len(self.inference_latencies_ms)
            if self.inference_latencies_ms
            else 0.0
        )
        return {
            "source_provenance": self.source_provenance,
            "is_running": self.is_running,
            "flows_scored": self.flows_scored,
            "anomalies_detected": self.anomalies_detected,
            "alerts_persisted": self.alerts_persisted,
            "validation_errors": self.validation_errors,
            "inference_failures": self.inference_failures,
            "persistence_failures": self.persistence_failures,
            "incompatible_flows_rejected": self.incompatible_flows_rejected,
            "unprocessed_flows": self.unprocessed_flows,
            "drain_timed_out": self.drain_timed_out,
            "forced_stop": self.forced_stop,
            "thread_hung": self.thread_hung,
            "sentinel_inserted": self.sentinel_inserted,
            "queue_depth": self.flow_queue.qsize(),
            "mean_inference_latency_ms": round(mean_lat, 2),
            "recent_events_buffered": len(self.recent_events),
        }
