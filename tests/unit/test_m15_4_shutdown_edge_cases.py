"""
TrafficShield Milestone 15.4: Shutdown Edge-Case Verification & Concurrency Hardening
====================================================================================
Deterministic automated test suite covering:
1. Normal shutdown with an empty queue.
2. Normal shutdown with queued flows.
3. Active-flow flushing during shutdown.
4. A queue filled to capacity.
5. Pipeline thread join timeout.
6. Worker drain timeout.
7. Worker exception during inference.
8. Persistence failure.
9. Concurrent stop requests.
10. Repeated stop calls.
11. No duplicate scoring or alert persistence.
12. Exact final accounting for every test.
13. No unexpected worker or pipeline threads remaining after successful teardown.
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Any
from unittest.mock import MagicMock

from ingestion.capture.base import PacketEnvelope, PacketSource
from ingestion.flow.flow_builder import UnidirectionalFlowBuilder
from ml.production_service import ProductionInferenceService
from streaming.inference_worker import StreamingInferenceWorker
from streaming.manager import RealTimeDetectionManager, WorkerState


def _make_valid_flow(
    flow_id: str,
    sttl: int = 64,
    is_compatible: bool = True,
    src_ip: str = "192.168.1.50",
    dst_ip: str = "10.0.0.1",
    dst_port: int = 80,
    proto: str = "TCP",
) -> dict[str, Any]:
    """Helper to construct a valid flow dictionary for worker tests."""
    return {
        "flow_id": flow_id,
        "src_ip": src_ip,
        "dst_ip": dst_ip,
        "src_port": 50000,
        "dst_port": dst_port,
        "protocol": proto,
        "duration_seconds": 0.1,
        "fwd_bytes": 1200,
        "sttl": sttl,
        "sload": 96000.0,
        "fwd_packets": 10,
        "swin": 255,
        "smeansz": 120.0,
        "sjit": 2.5,
        "sintpkt": 10.0,
        "is_sm_ips_ports": 0,
        "is_compatible": is_compatible,
        "compatibility_reason": None if is_compatible else "TEST_INCOMPATIBLE",
        "packet_rate": 100.0,
        "byte_rate": 12000.0,
        "bytes_per_packet": 120.0,
    }


class TestShutdownEdgeCasesAndConcurrencyHardening:
    """Rigorous verification of shutdown edge cases, concurrency, and flow accounting."""

    def test_1_normal_shutdown_with_empty_queue(self) -> None:
        """1. Normal shutdown with an empty queue."""
        q: queue.Queue = queue.Queue()
        service = ProductionInferenceService(verify_checksums=True)
        worker = StreamingInferenceWorker(flow_queue=q, inference_service=service)

        worker.start()
        assert worker.is_running is True
        assert worker._thread is not None and worker._thread.is_alive()

        worker.stop(drain_timeout=2.0)
        assert worker.is_running is False
        assert worker._thread is None or not worker._thread.is_alive()
        assert worker.flows_scored == 0
        assert worker.unprocessed_flows == 0
        assert q.empty()

        # Invariant check
        assert worker.flows_scored + worker.unprocessed_flows == 0

    def test_2_normal_shutdown_with_queued_flows(self) -> None:
        """2. Normal shutdown with pending queued flows."""
        q: queue.Queue = queue.Queue()
        service = ProductionInferenceService(verify_checksums=True)
        worker = StreamingInferenceWorker(flow_queue=q, inference_service=service)

        num_flows = 10
        for i in range(num_flows):
            q.put(_make_valid_flow(f"pending_flow_{i}"))

        worker.start()
        worker.stop(drain_timeout=5.0)

        assert worker.is_running is False
        assert worker._thread is None or not worker._thread.is_alive()
        assert worker.flows_scored == num_flows
        assert worker.unprocessed_flows == 0
        assert q.empty()

        # Invariant check: flows_queued == flows_scored + unprocessed
        assert worker.flows_scored + worker.unprocessed_flows == num_flows

    def test_3_active_flow_flushing_during_shutdown(self) -> None:
        """3. Active-flow flushing during shutdown and protection against late packets."""
        builder = UnidirectionalFlowBuilder(idle_timeout_seconds=60.0)

        # Ingest 4 distinct flows (1 packet each, unfinalized)
        for i in range(4):
            env = PacketEnvelope(
                timestamp=100.0 + i,
                ip_src="192.168.1.10",
                ip_dst=f"10.0.0.{i+1}",
                src_port=40000 + i,
                dst_port=80,
                protocol="TCP",
                ttl=64,
                byte_length=100,
                tcp_window=65535,
                tcp_flags="S",
            )
            finalized = builder.process_packet(env)
            assert len(finalized) == 0

        assert builder.get_metrics()["active_flows_count"] == 4
        assert builder.flows_created == 4

        # Flush active flows
        flushed = builder.flush()
        assert len(flushed) == 4
        assert builder.flows_flushed == 4
        assert builder.flows_completed == 4
        assert builder.get_metrics()["active_flows_count"] == 0
        assert builder.get_metrics()["is_closed"] is True

        # Late packet arriving after flush must be dropped cleanly without creating flows
        late_env = PacketEnvelope(
            timestamp=200.0,
            ip_src="192.168.1.99",
            ip_dst="10.0.0.99",
            src_port=55555,
            dst_port=80,
            protocol="TCP",
            ttl=64,
            byte_length=100,
        )
        late_finalized = builder.process_packet(late_env)
        assert len(late_finalized) == 0
        assert builder.flows_created == 4  # Unchanged
        assert builder.get_metrics()["active_flows_count"] == 0

        # Drain flushed flows in worker
        q: queue.Queue = queue.Queue()
        service = ProductionInferenceService(verify_checksums=True)
        worker = StreamingInferenceWorker(flow_queue=q, inference_service=service)

        for f in flushed:
            q.put(f)

        worker.start()
        worker.stop(drain_timeout=5.0)

        assert worker.flows_scored == 4
        assert worker.unprocessed_flows == 0
        assert q.empty()

        # Invariant check: flows_created == flows_completed == flows_flushed == flows_scored
        assert builder.flows_created == builder.flows_completed == worker.flows_scored == 4

    def test_4_queue_filled_to_capacity(self) -> None:
        """4. Queue filled to capacity: sentinel insertion waits and does not block indefinitely."""
        cap = 4
        q: queue.Queue = queue.Queue(maxsize=cap)
        service = ProductionInferenceService(verify_checksums=True)
        worker = StreamingInferenceWorker(flow_queue=q, inference_service=service)

        for i in range(cap):
            q.put_nowait(_make_valid_flow(f"cap_flow_{i}"))

        assert q.full() is True

        worker.start()
        # Sentinel wait allows worker to consume, opening slots so sentinel fits
        worker.stop(drain_timeout=5.0)

        assert worker.is_running is False
        assert worker.flows_scored == cap
        assert worker.unprocessed_flows == 0
        assert q.empty()

    def test_5_pipeline_thread_join_timeout(self) -> None:
        """5. Pipeline thread join timeout is explicitly recorded and does not falsely report clean stop."""
        manager = RealTimeDetectionManager.get_instance()
        manager.stop()

        unblock_event = threading.Event()

        class BlockedPacketSource(PacketSource):
            @property
            def source_type(self):
                from ingestion.capture.base import CaptureSourceType
                return CaptureSourceType.PCAP_REPLAY

            @property
            def is_running(self):
                return True

            def start(self):
                pass

            def pause(self):
                pass

            def resume(self):
                pass

            def packets(self):
                # Yield 1 envelope, then block until unblock_event is set
                yield PacketEnvelope(
                    timestamp=100.0,
                    ip_src="10.0.0.1",
                    ip_dst="10.0.0.2",
                    src_port=1000,
                    dst_port=80,
                    protocol="TCP",
                    ttl=64,
                    byte_length=100,
                )
                unblock_event.wait(timeout=10.0)

            def stop(self):
                pass

            def get_metrics(self):
                return {}

        # Set up manager manually with blocked source
        with manager._manager_lock:
            manager.state = WorkerState.STARTING
            manager.packet_source = BlockedPacketSource()
            manager.flow_builder = UnidirectionalFlowBuilder()
            manager.flows_queued = 0
            manager.flows_queue_dropped = 0
            manager.pipeline_join_timed_out = False
            service = manager._get_inference_service()
            manager.inference_worker = StreamingInferenceWorker(
                flow_queue=manager.flow_queue,
                inference_service=service,
            )
            manager.inference_worker.start()
            manager._stop_event.clear()

            manager._pipeline_thread = threading.Thread(
                target=manager._run_pipeline_loop,
                name="BlockedPipelineThread",
                daemon=True,
            )
            manager._pipeline_thread.start()
            manager.state = WorkerState.RUNNING

        # Give the pipeline thread a moment to ingest the 1 packet and block
        time.sleep(0.05)

        try:
            # Stop manager: pipeline thread will not terminate within 2.0s join timeout
            # To make test fast, monkeypatch join timeout temporarily on _pipeline_thread
            orig_join = manager._pipeline_thread.join

            def fast_join(timeout=None):
                orig_join(timeout=0.05)

            manager._pipeline_thread.join = fast_join

            status = manager.stop(drain_timeout=1.0)

            # Verification:
            assert manager.pipeline_join_timed_out is True
            assert status["pipeline_join_timed_out"] is True
            assert status["worker_state"] == "DEGRADED"
            assert "Pipeline thread did not terminate" in (manager.error_message or "")

            # Flow builder was closed on flush, protecting from concurrent ingestion
            assert manager.flow_builder._is_closed is True

        finally:
            # Unblock the thread so it can exit cleanly
            unblock_event.set()
            manager._stop_event.set()
            if manager._pipeline_thread:
                manager._pipeline_thread.join(timeout=2.0)
            manager.pipeline_join_timed_out = False
            manager.state = WorkerState.STOPPED

    def test_6_worker_drain_timeout(self) -> None:
        """6. Worker drain timeout: forced stop is triggered and unprocessed flows are accounted for."""
        q: queue.Queue = queue.Queue()

        # Controlled service mock with artificial delay
        mock_service = MagicMock(spec=ProductionInferenceService)

        def slow_predict(flow):
            time.sleep(0.05)  # 50 ms per flow
            return {"anomaly_score": 0.1, "risk_level": "LOW", "top_contributing_features": []}

        mock_service.predict_single.side_effect = slow_predict
        mock_service.model_name = "OptunaTuned_XGBoost"
        mock_service.version = "1.0.0"

        worker = StreamingInferenceWorker(flow_queue=q, inference_service=mock_service)

        # Enqueue 20 flows: at 50ms each, draining 20 would require ~1.0 second
        for i in range(20):
            q.put(_make_valid_flow(f"slow_flow_{i}"))

        worker.start()
        # Set ultra-short drain timeout (0.05s) to guarantee drain timeout fires
        worker.stop(drain_timeout=0.05)

        assert worker.is_running is False
        assert worker.drain_timed_out is True
        assert worker.forced_stop is True

        wm = worker.get_metrics()
        # Total accounted flows must equal exactly the 20 queued flows
        assert wm["flows_scored"] + wm["unprocessed_flows"] == 20
        assert wm["unprocessed_flows"] > 0
        assert q.empty()

    def test_7_worker_exception_during_inference(self) -> None:
        """7. Worker exception during inference: increment inference_failures and continue/stop safely."""
        q: queue.Queue = queue.Queue()
        mock_service = MagicMock(spec=ProductionInferenceService)
        # Throw unexpected exception (e.g. GPU out of memory / runtime crash)
        mock_service.predict_single.side_effect = RuntimeError("Fatal model inference error")
        mock_service.model_name = "OptunaTuned_XGBoost"
        mock_service.version = "1.0.0"

        worker = StreamingInferenceWorker(flow_queue=q, inference_service=mock_service)
        q.put(_make_valid_flow("crash_flow_1"))
        q.put(_make_valid_flow("crash_flow_2"))

        worker.start()
        worker.stop(drain_timeout=2.0)

        assert worker.is_running is False
        assert worker.inference_failures == 2
        assert worker.flows_scored == 0
        assert worker.unprocessed_flows == 0

        # Exact accounting: flows_queued (2) == inference_failures (2)
        assert worker.inference_failures + worker.flows_scored + worker.unprocessed_flows == 2

    def test_8_persistence_failure(self) -> None:
        """8. Persistence failure: flow is scored, anomaly detected, but persistence_failures incremented."""
        q: queue.Queue = queue.Queue()
        service = ProductionInferenceService(verify_checksums=True)
        worker = StreamingInferenceWorker(flow_queue=q, inference_service=service)

        class FailingApp:
            def app_context(self):
                raise RuntimeError("Database connection unreachable")

        worker.app = FailingApp()
        # High TTL (255) ensures an anomaly is detected, which triggers persistence attempt
        flow = _make_valid_flow("anom_flow", sttl=255)
        q.put(flow)

        worker.start()
        worker.stop(drain_timeout=2.0)

        assert worker.flows_scored == 1
        assert worker.anomalies_detected == 1
        assert worker.persistence_failures == 1
        assert worker.alerts_persisted == 0

        # Distinguish: flow WAS scored, but alert persistence failed
        # Mutually exclusive queue outcomes: flows_queued (1) == flows_scored (1)
        assert worker.flows_scored + worker.unprocessed_flows == 1

    def test_9_concurrent_stop_requests(self) -> None:
        """9. Concurrent stop requests: teardown is idempotent and single owner executes drain."""
        q: queue.Queue = queue.Queue()
        service = ProductionInferenceService(verify_checksums=True)
        worker = StreamingInferenceWorker(flow_queue=q, inference_service=service)

        for i in range(15):
            q.put(_make_valid_flow(f"concurrent_flow_{i}"))

        worker.start()

        exceptions: list[Exception] = []

        def _concurrent_stop():
            try:
                worker.stop(drain_timeout=5.0)
            except Exception as e:
                exceptions.append(e)

        threads = [threading.Thread(target=_concurrent_stop) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(exceptions) == 0
        assert worker.is_running is False
        assert worker._thread is None or not worker._thread.is_alive()
        assert worker.flows_scored == 15
        assert worker.unprocessed_flows == 0
        assert q.empty()

    def test_10_repeated_stop_calls(self) -> None:
        """10. Repeated stop calls on manager and worker are strictly idempotent."""
        manager = RealTimeDetectionManager.get_instance()
        manager.stop()

        # Sequential repeated stops on worker
        q: queue.Queue = queue.Queue()
        service = ProductionInferenceService(verify_checksums=True)
        worker = StreamingInferenceWorker(flow_queue=q, inference_service=service)
        worker.start()
        worker.stop()
        metrics1 = worker.get_metrics()
        worker.stop()
        worker.stop()
        metrics2 = worker.get_metrics()

        assert metrics1["flows_scored"] == metrics2["flows_scored"]
        assert metrics1["unprocessed_flows"] == metrics2["unprocessed_flows"]
        assert worker.is_running is False

        # Sequential repeated stops on manager
        status1 = manager.stop()
        status2 = manager.stop()
        assert status1["worker_state"] == status2["worker_state"] == "STOPPED"

    def test_11_no_duplicate_scoring_or_alert_persistence(self) -> None:
        """11. No duplicate scoring or duplicate alert persistence under concurrent calls."""
        q: queue.Queue = queue.Queue()
        service = ProductionInferenceService(verify_checksums=True)
        worker = StreamingInferenceWorker(flow_queue=q, inference_service=service)

        # Enqueue 5 flows with different ports
        for i in range(5):
            q.put(_make_valid_flow(f"unique_flow_{i}", dst_port=80 + i))

        worker.start()

        def _stop_worker():
            worker.stop(drain_timeout=5.0)

        t1 = threading.Thread(target=_stop_worker)
        t2 = threading.Thread(target=_stop_worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert worker.flows_scored == 5
        assert worker.unprocessed_flows == 0
        # Check that recent_events buffer has exactly 5 events, no duplicates
        event_ids = [e["flow_id"] for e in worker.recent_events]
        assert len(event_ids) == 5
        assert len(set(event_ids)) == 5

    def test_12_exact_final_accounting_comprehensive(self) -> None:
        """12. Exact final accounting across all terminal outcomes."""
        q: queue.Queue = queue.Queue()

        # Mock service that handles different flow IDs differently
        mock_service = MagicMock(spec=ProductionInferenceService)

        def mock_predict(flow):
            fid = flow.get("flow_id", "")
            if "runtime_fail" in fid:
                raise RuntimeError("Engine fault")
            if "validation_fail" in fid:
                raise ValueError("Bad field value")
            return {"anomaly_score": 0.2, "risk_level": "LOW", "top_contributing_features": []}

        mock_service.predict_single.side_effect = mock_predict
        mock_service.model_name = "OptunaTuned_XGBoost"
        mock_service.version = "1.0.0"

        worker = StreamingInferenceWorker(flow_queue=q, inference_service=mock_service)

        # 1. Valid normal flows (2)
        q.put(_make_valid_flow("normal_1"))
        q.put(_make_valid_flow("normal_2"))

        # 2. Incompatible flow (1)
        q.put(_make_valid_flow("incompat_1", is_compatible=False))

        # 3. Validation error flow (1)
        q.put(_make_valid_flow("validation_fail_1"))

        # 4. Inference failure flow (1)
        q.put(_make_valid_flow("runtime_fail_1"))

        total_queued = 5
        worker.start()
        worker.stop(drain_timeout=5.0)

        wm = worker.get_metrics()
        scored = wm["flows_scored"]
        rejected = wm["incompatible_flows_rejected"]
        val_err = wm["validation_errors"]
        infer_fail = wm["inference_failures"]
        unprocessed = wm["unprocessed_flows"]

        assert scored == 2
        assert rejected == 1
        assert val_err == 1
        assert infer_fail == 1
        assert unprocessed == 0

        # Rigorous Mutually Exclusive Invariant:
        assert total_queued == scored + rejected + val_err + infer_fail + unprocessed

    def test_13_no_unexpected_threads_remaining_after_teardown(self) -> None:
        """13. No unexpected worker or pipeline threads remaining after successful teardown."""
        threads_before_count = threading.active_count()

        q: queue.Queue = queue.Queue()
        service = ProductionInferenceService(verify_checksums=True)
        worker = StreamingInferenceWorker(flow_queue=q, inference_service=service)

        worker.start()
        assert worker._thread is not None and worker._thread.is_alive()

        worker.stop(drain_timeout=2.0)
        assert worker._thread is None or not worker._thread.is_alive()

        # Allow brief moment for OS thread cleanup
        time.sleep(0.05)
        threads_after = threading.enumerate()

        # Worker thread must NOT be present in active threads
        active_names = [t.name for t in threads_after if t.is_alive()]
        assert "StreamingInferenceWorker" not in active_names
        assert "BlockedPipelineThread" not in active_names
        assert threading.active_count() <= threads_before_count + 1
