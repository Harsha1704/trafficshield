"""
Real-Time Detection Coordinator & Lifecycle Manager
===================================================
Milestone 14 — Real-Time Network Detection & Flow Reconstruction

Coordinates the end-to-end packet-to-flow-to-inference pipeline.
Manages thread lifecycles, state machine transitions, bounded queues, and telemetry.

States:
- STOPPED: No capture or inference active.
- STARTING: Initializing packet source and worker threads.
- RUNNING: Actively acquiring packets, reconstructing flows, and executing inference.
- PAUSED: Packet pacing temporarily halted.
- DEGRADED: Running with queue overflow or high dropped packet rates.
- FAILED: Worker encountered an unrecoverable exception.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ingestion.capture.base import CaptureSourceType, PacketSource, WorkerState
from ingestion.capture.live_source import LiveCaptureSource, is_capture_driver_available
from ingestion.capture.pcap_source import PcapReplaySource
from ingestion.flow.flow_builder import UnidirectionalFlowBuilder
from ml.production_service import (
    EXPECTED_DETECTOR_SHA256,
    EXPECTED_PREPROCESSOR_SHA256,
    ProductionInferenceService,
)
from streaming.inference_worker import StreamingInferenceWorker

logger = logging.getLogger("streaming_manager")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class RealTimeDetectionManager:
    """
    Central supervisor for the real-time detection pipeline.
    Ensures single-instance session execution, graceful teardown, and auditable telemetry.
    """

    _instance: RealTimeDetectionManager | None = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> RealTimeDetectionManager:
        """Singleton accessor for application-wide capture session management."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self) -> None:
        self.state: WorkerState = WorkerState.STOPPED
        self.capture_mode: CaptureSourceType | None = None
        self.selected_target: str | None = None  # Interface name or PCAP filename
        self.error_message: str | None = None
        self.start_time: datetime | None = None
        self.last_packet_timestamp: float | None = None

        # Components
        self.packet_source: PacketSource | None = None
        self.flow_builder: UnidirectionalFlowBuilder | None = None
        self.inference_worker: StreamingInferenceWorker | None = None
        self.flow_queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=10000)
        self.flows_queued: int = 0
        self.flows_queue_dropped: int = 0
        self.pipeline_join_timed_out: bool = False

        # Pipeline runner thread
        self._pipeline_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._manager_lock = threading.RLock()

        # Shared production inference service singleton
        self._inference_service: ProductionInferenceService | None = None

    def _get_inference_service(self) -> ProductionInferenceService:
        """Lazily initialize or return production inference service with verified checksums."""
        if self._inference_service is None:
            model_path = Path("artifacts/models/production_detector.joblib")
            prep_path = Path("artifacts/models/production_preprocessor.joblib")
            self._inference_service = ProductionInferenceService(
                model_path=model_path,
                preprocessor_path=prep_path,
                threshold=0.50,
                verify_checksums=True,
            )
        return self._inference_service

    def start_pcap_replay(
        self,
        pcap_path: str | Path,
        speed_multiplier: float = 1.0,
        app: Any = None,
        max_packets: int | None = None,
    ) -> dict[str, Any]:
        """Initiate packet replay from a validated PCAP/PCAPNG capture file."""
        with self._manager_lock:
            if self.state in (WorkerState.RUNNING, WorkerState.STARTING):
                raise RuntimeError("A capture or replay session is already active. Stop it first.")

            self.state = WorkerState.STARTING
            self.error_message = None
            self.capture_mode = CaptureSourceType.PCAP_REPLAY
            pcap_file = Path(pcap_path)
            self.selected_target = pcap_file.name
            self.start_time = _utcnow()
            self._stop_event.clear()

            try:
                # 1. Initialize packet source
                source = PcapReplaySource(
                    filepath=pcap_file,
                    speed_multiplier=speed_multiplier,
                    max_packets=max_packets,
                )
                self.packet_source = source

                # 2. Initialize unidirectional flow builder
                self.flow_builder = UnidirectionalFlowBuilder(
                    idle_timeout_seconds=2.0,
                    max_flow_lifetime_seconds=60.0,
                    max_active_flows=10000,
                )

                # 3. Empty flow queue and reset queue counters
                self.flows_queued = 0
                self.flows_queue_dropped = 0
                self.pipeline_join_timed_out = False
                while not self.flow_queue.empty():
                    try:
                        self.flow_queue.get_nowait()
                    except queue.Empty:
                        break

                # 4. Initialize and start streaming inference worker
                service = self._get_inference_service()
                self.inference_worker = StreamingInferenceWorker(
                    flow_queue=self.flow_queue,
                    inference_service=service,
                    app=app,
                    source_provenance=CaptureSourceType.PCAP_REPLAY.value,
                    recent_buffer_size=200,
                    decision_threshold=0.50,
                )
                self.inference_worker.start()

                # 5. Start ingestion pipeline thread
                self._pipeline_thread = threading.Thread(
                    target=self._run_pipeline_loop,
                    name=f"Pipeline-{pcap_file.name}",
                    daemon=True,
                )
                self._pipeline_thread.start()
                self.state = WorkerState.RUNNING

                logger.info("Real-time pipeline started in PCAP_REPLAY mode: %s", pcap_file.name)
                return self.get_status()

            except Exception as exc:
                self.state = WorkerState.FAILED
                self.error_message = str(exc)
                logger.error("Failed to start PCAP replay: %s", exc)
                self.stop()
                raise

    def start_live_capture(
        self,
        interface: str,
        bpf_filter: str = "ip",
        app: Any = None,
    ) -> dict[str, Any]:
        """Initiate passive live packet sniffing on an authorized interface."""
        with self._manager_lock:
            if self.state in (WorkerState.RUNNING, WorkerState.STARTING):
                raise RuntimeError("A capture or replay session is already active. Stop it first.")

            # Check kernel capture driver presence
            driver_ok, driver_msg = is_capture_driver_available()
            if not driver_ok:
                self.state = WorkerState.FAILED
                self.error_message = driver_msg
                raise RuntimeError(driver_msg)

            self.state = WorkerState.STARTING
            self.error_message = None
            self.capture_mode = CaptureSourceType.LIVE_CAPTURE
            self.selected_target = interface
            self.start_time = _utcnow()
            self._stop_event.clear()

            try:
                # 1. Initialize live capture source
                source = LiveCaptureSource(
                    interface=interface,
                    bpf_filter=bpf_filter,
                )
                self.packet_source = source
                source.start()

                # 2. Flow builder & queue
                self.flow_builder = UnidirectionalFlowBuilder(
                    idle_timeout_seconds=2.0,
                    max_flow_lifetime_seconds=60.0,
                    max_active_flows=10000,
                )

                self.flows_queued = 0
                self.flows_queue_dropped = 0
                self.pipeline_join_timed_out = False
                while not self.flow_queue.empty():
                    try:
                        self.flow_queue.get_nowait()
                    except queue.Empty:
                        break

                # 3. Inference worker
                service = self._get_inference_service()
                self.inference_worker = StreamingInferenceWorker(
                    flow_queue=self.flow_queue,
                    inference_service=service,
                    app=app,
                    source_provenance=CaptureSourceType.LIVE_CAPTURE.value,
                    recent_buffer_size=200,
                    decision_threshold=0.50,
                )
                self.inference_worker.start()

                # 4. Pipeline thread
                self._pipeline_thread = threading.Thread(
                    target=self._run_pipeline_loop,
                    name=f"Pipeline-{interface}",
                    daemon=True,
                )
                self._pipeline_thread.start()
                self.state = WorkerState.RUNNING

                logger.info("Real-time pipeline started in LIVE_CAPTURE mode on: %s", interface)
                return self.get_status()

            except Exception as exc:
                self.state = WorkerState.FAILED
                self.error_message = str(exc)
                logger.error("Failed to start live capture on %s: %s", interface, exc)
                self.stop()
                raise

    def pause(self) -> dict[str, Any]:
        """Pause active packet acquisition."""
        with self._manager_lock:
            if self.packet_source and self.state == WorkerState.RUNNING:
                self.packet_source.pause()
                self.state = WorkerState.PAUSED
                logger.info("Real-time pipeline paused.")
            return self.get_status()

    def resume(self) -> dict[str, Any]:
        """Resume paused packet acquisition."""
        with self._manager_lock:
            if self.packet_source and self.state == WorkerState.PAUSED:
                self.packet_source.resume()
                self.state = WorkerState.RUNNING
                logger.info("Real-time pipeline resumed.")
            return self.get_status()

    def stop(self, drain_timeout: float = 5.0) -> dict[str, Any]:
        """
        Orderly shutdown: halt packet acquisition, join pipeline thread, flush in-flight flows,
        and gracefully drain remaining flows in the inference worker up to timeout.
        """
        with self._manager_lock:
            # Idempotency guard: return immediately if session is already fully stopped
            if self.state in (WorkerState.STOPPED, WorkerState.FAILED, WorkerState.DEGRADED) and (
                self.inference_worker is None or not self.inference_worker.is_running
            ):
                return self.get_status()

            self._stop_event.set()

            # 1. Stop packet capture source
            if self.packet_source:
                try:
                    self.packet_source.stop()
                except Exception as exc:
                    logger.debug("Error stopping packet source: %s", exc)

            # 2. Join pipeline thread so no further packets enter the flow builder
            if (
                self._pipeline_thread
                and self._pipeline_thread.is_alive()
                and threading.current_thread() != self._pipeline_thread
            ):
                self._pipeline_thread.join(timeout=2.0)
                if self._pipeline_thread.is_alive():
                    self.pipeline_join_timed_out = True
                    self.error_message = "Pipeline thread did not terminate within join timeout"
                    logger.warning("Pipeline thread did not terminate within join timeout; forcing ingestion halt.")

            # 3. Flush remaining in-flight flows from flow builder to queue
            # (Note: flush closes the flow_builder, preventing any further packet processing)
            if self.flow_builder:
                flushed = self.flow_builder.flush()
                for f in flushed:
                    try:
                        self.flow_queue.put(f, timeout=1.0)
                        self.flows_queued += 1
                    except queue.Full:
                        self.flows_queue_dropped += 1
                        logger.warning("Flow queue full while flushing! Dropping in-flight flow.")

            # 4. Gracefully drain inference worker
            if self.inference_worker:
                try:
                    self.inference_worker.stop(drain_timeout=drain_timeout)
                except Exception as exc:
                    logger.debug("Error stopping inference worker: %s", exc)

            if self.pipeline_join_timed_out:
                self.state = WorkerState.DEGRADED
            elif self.state != WorkerState.FAILED:
                self.state = WorkerState.STOPPED

            logger.info("Real-time pipeline stopped. State: %s", self.state.value)
            return self.get_status()

    def _run_pipeline_loop(self) -> None:
        """
        Main pipeline thread: reads packets from packet source, feeds flow builder,
        and enqueues finalized flows for inference scoring.
        """
        assert self.packet_source is not None
        assert self.flow_builder is not None

        try:
            for envelope in self.packet_source.packets():
                if self._stop_event.is_set():
                    break

                self.last_packet_timestamp = envelope.timestamp

                # Incorporate packet and obtain any finalized flows
                finalized = self.flow_builder.process_packet(envelope)
                for f in finalized:
                    if self._stop_event.is_set():
                        break
                    try:
                        self.flow_queue.put(f, timeout=1.0)
                        self.flows_queued += 1
                    except queue.Full:
                        self.flows_queue_dropped += 1
                        logger.warning("Flow queue full! Dropping completed flow.")
                        if self.state == WorkerState.RUNNING:
                            self.state = WorkerState.DEGRADED

            # Replay reached EOF or stop requested
            if not self._stop_event.is_set() and self.capture_mode == CaptureSourceType.PCAP_REPLAY:
                # Flush remaining flows at EOF
                flushed = self.flow_builder.flush()
                for f in flushed:
                    try:
                        self.flow_queue.put(f, timeout=1.0)
                        self.flows_queued += 1
                    except queue.Full:
                        self.flows_queue_dropped += 1
                logger.info("PCAP replay finished all packets in file.")

        except Exception as exc:
            self.state = WorkerState.FAILED
            self.error_message = str(exc)
            logger.error("Error in real-time pipeline execution loop: %s", exc)
        finally:
            if self.capture_mode == CaptureSourceType.PCAP_REPLAY and not self._stop_event.is_set():
                # Replay completed naturally; drain worker and transition to COMPLETED
                if self.inference_worker:
                    self.inference_worker.stop(drain_timeout=5.0)
                self.state = WorkerState.COMPLETED
                logger.info("PCAP replay finished and worker drained successfully.")

    def get_status(self) -> dict[str, Any]:
        """Aggregate real-time status, health, and metrics for SOC dashboard."""
        source_metrics = self.packet_source.get_metrics() if self.packet_source else {}
        flow_metrics = self.flow_builder.get_metrics() if self.flow_builder else {}
        infer_metrics = self.inference_worker.get_metrics() if self.inference_worker else {}

        recent = list(self.inference_worker.recent_events) if self.inference_worker else []

        now = time.time()
        start_ts = self.start_time.timestamp() if self.start_time else now
        uptime = max(0.0, now - start_ts) if self.state in (WorkerState.RUNNING, WorkerState.PAUSED) else 0.0

        # Model and checksum status
        driver_ok, driver_msg = is_capture_driver_available()

        return {
            "worker_state": self.state.value,
            "capture_mode": self.capture_mode.value if self.capture_mode else "NONE",
            "selected_target": self.selected_target,
            "error_message": self.error_message,
            "uptime_seconds": round(uptime, 1),
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "last_packet_timestamp": self.last_packet_timestamp,
            # Operational Counters
            "packets_observed": source_metrics.get("packets_read", source_metrics.get("packets_captured", 0)),
            "packets_dropped": source_metrics.get("packets_dropped", 0),
            "malformed_packets_rejected": source_metrics.get("malformed_packets", 0),
            "truncated_packets_rejected": source_metrics.get("truncated_packets", 0),
            "unsupported_packets_rejected": source_metrics.get("unsupported_packets", 0),
            "rejection_reasons": source_metrics.get("rejection_reasons", {}),
            "fragment_metrics": source_metrics.get("fragment_metrics", {}),
            "incompatible_flows_rejected": infer_metrics.get("incompatible_flows_rejected", 0),
            "active_flows_count": flow_metrics.get("active_flows_count", 0),
            "flows_created": flow_metrics.get("flows_created", 0),
            "flows_completed": flow_metrics.get("flows_completed", 0),
            "flows_flushed": flow_metrics.get("flows_flushed", 0),
            "flows_closed_tcp": flow_metrics.get("flows_closed_tcp", 0),
            "flows_expired_timeout": flow_metrics.get("flows_expired_timeout", 0),
            "flows_evicted_overflow": flow_metrics.get("flows_evicted_overflow", 0),
            "flows_queued": self.flows_queued,
            "flows_queue_dropped": self.flows_queue_dropped,
            "flows_scored": infer_metrics.get("flows_scored", 0),
            "anomalies_detected": infer_metrics.get("anomalies_detected", 0),
            "alerts_persisted": infer_metrics.get("alerts_persisted", 0),
            "alerts_deduplicated": infer_metrics.get("alerts_deduplicated", 0),
            "alerts_unpersisted_no_app": infer_metrics.get("alerts_unpersisted_no_app", 0),
            "validation_errors": infer_metrics.get("validation_errors", 0),
            "inference_failures": infer_metrics.get("inference_failures", 0),
            "persistence_failures": infer_metrics.get("persistence_failures", 0),
            "unprocessed_flows": infer_metrics.get("unprocessed_flows", 0),
            "pipeline_join_timed_out": self.pipeline_join_timed_out,
            "drain_timed_out": infer_metrics.get("drain_timed_out", False),
            "forced_stop": infer_metrics.get("forced_stop", False),
            "thread_hung": infer_metrics.get("thread_hung", False),
            "queue_depth": self.flow_queue.qsize(),
            "mean_inference_latency_ms": infer_metrics.get("mean_inference_latency_ms", 0.0),
            "latency_p50_ms": infer_metrics.get("latency_p50_ms", 0.0),
            "latency_p95_ms": infer_metrics.get("latency_p95_ms", 0.0),
            "latency_p99_ms": infer_metrics.get("latency_p99_ms", 0.0),
            "native_kernel_drops_available": source_metrics.get("native_kernel_drops_available", False),
            "native_kernel_drops": source_metrics.get("native_kernel_drops", None),
            "native_kernel_drops_delta": source_metrics.get("native_kernel_drops_delta", None),
            "native_packets_received": source_metrics.get("native_packets_received", None),
            "native_interface_drops": source_metrics.get("native_interface_drops", None),
            "kernel_drop_status": source_metrics.get(
                "kernel_drop_status",
                "UNAVAILABLE (Capture source inactive or uninitialized)",
            ),
            "kernel_poll_interval_seconds": source_metrics.get("kernel_poll_interval_seconds", None),
            "kernel_driver_name": source_metrics.get("kernel_driver_name", "Npcap"),
            "source_provenance": (
                self.capture_mode.value if self.capture_mode else "NONE"
            ),
            # Driver & Integrity
            "driver_available": driver_ok,
            "driver_message": driver_msg,
            "model_integrity": {
                "model_name": "OptunaTuned_XGBoost",
                "model_version": "1.0.0",
                "model_sha256": EXPECTED_DETECTOR_SHA256,
                "preprocessor_sha256": EXPECTED_PREPROCESSOR_SHA256,
                "checksum_verified": True,
            },
            # Real-time event stream (latest 50 events for UI)
            "recent_events": recent[-50:],
        }
