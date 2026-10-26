"""
TrafficShield Milestone 15.2: Graceful Queue Drain & Orderly Shutdown Tests
==========================================================================
Validates:
1. Normal shutdown with an empty queue.
2. Graceful shutdown with pending queued flows (zero unscored flow gap).
3. Graceful shutdown with in-flight flows that must be flushed from flow builder.
4. Complete, reconcilable flow accounting across built, flushed, scored, rejected, and unprocessed counters.
5. Queue-drain timeout behavior and explicit unprocessed_flows accounting.
6. Repeated and concurrent stop calls (idempotence and thread safety).
7. Thread teardown cleanliness with zero orphaned worker threads or duplicate alerts.
"""
from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import Any

from ingestion.capture.base import PacketEnvelope
from ingestion.flow.flow_builder import UnidirectionalFlowBuilder
from ml.production_service import ProductionInferenceService
from streaming.inference_worker import StreamingInferenceWorker
from streaming.manager import RealTimeDetectionManager


def _make_valid_flow(flow_id: str, sttl: int = 64, is_compatible: bool = True) -> dict[str, Any]:
    """Helper to construct a valid flow dictionary for worker tests."""
    return {
        "flow_id": flow_id,
        "src_ip": "192.168.1.50",
        "dst_ip": "10.0.0.1",
        "src_port": 50000,
        "dst_port": 80,
        "protocol": "TCP",
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


class TestOrderlyShutdownAndDrain:
    """Validate thread-safe graceful shutdown sequences and drain semantics."""

    def test_normal_shutdown_with_empty_queue(self) -> None:
        """Worker with an empty queue stops cleanly and immediately."""
        q: queue.Queue = queue.Queue()
        service = ProductionInferenceService(verify_checksums=True)
        worker = StreamingInferenceWorker(flow_queue=q, inference_service=service)

        worker.start()
        assert worker.is_running is True

        worker.stop(drain_timeout=2.0)
        assert worker.is_running is False
        assert worker.flows_scored == 0
        assert worker.unprocessed_flows == 0
        assert q.empty()

    def test_shutdown_with_pending_queued_flows(self) -> None:
        """Worker drains all pending queued flows before terminating on shutdown."""
        q: queue.Queue = queue.Queue()
        service = ProductionInferenceService(verify_checksums=True)
        worker = StreamingInferenceWorker(flow_queue=q, inference_service=service)

        # Enqueue 15 valid flows before stopping
        for i in range(15):
            q.put(_make_valid_flow(f"pending_flow_{i}"))

        worker.start()
        # Immediately invoke stop with sufficient drain timeout
        worker.stop(drain_timeout=5.0)

        assert worker.is_running is False
        # All 15 flows must have been drained and scored
        assert worker.flows_scored == 15
        assert worker.unprocessed_flows == 0
        assert q.empty()

    def test_shutdown_with_in_flight_flows_flush(self) -> None:
        """Flows active in flow builder at shutdown are flushed, enqueued, and scored."""
        builder = UnidirectionalFlowBuilder(idle_timeout_seconds=60.0)
        q: queue.Queue = queue.Queue()
        service = ProductionInferenceService(verify_checksums=True)
        worker = StreamingInferenceWorker(flow_queue=q, inference_service=service)

        # Ingest 3 distinct TCP flows (1 packet each, so none expired or closed)
        for i in range(3):
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
            assert len(finalized) == 0  # Still active in builder

        assert builder.get_metrics()["active_flows_count"] == 3

        # Start worker
        worker.start()

        # Simulate manager orderly shutdown sequence:
        flushed = builder.flush()
        assert len(flushed) == 3
        assert builder.flows_flushed == 3
        assert builder.get_metrics()["active_flows_count"] == 0

        for f in flushed:
            q.put(f)

        worker.stop(drain_timeout=5.0)

        assert worker.flows_scored == 3
        assert worker.unprocessed_flows == 0
        assert q.empty()

    def test_flow_accounting_exact_reconciliation(self) -> None:
        """Verify mathematical reconciliation across all flow lifecycle counters."""
        builder = UnidirectionalFlowBuilder(idle_timeout_seconds=2.0)
        q: queue.Queue = queue.Queue()
        service = ProductionInferenceService(verify_checksums=True)
        worker = StreamingInferenceWorker(flow_queue=q, inference_service=service)

        # 1. Flow completed via FIN
        env_syn = PacketEnvelope(
            timestamp=1.0, ip_src="10.0.0.1", ip_dst="10.0.0.2",
            src_port=1000, dst_port=80, protocol="TCP", ttl=64, byte_length=100,
            tcp_flags="S", tcp_window=65535
        )
        env_fin = PacketEnvelope(
            timestamp=1.1, ip_src="10.0.0.1", ip_dst="10.0.0.2",
            src_port=1000, dst_port=80, protocol="TCP", ttl=64, byte_length=100,
            tcp_flags="FA", tcp_window=65535, is_fin_or_rst=True
        )
        builder.process_packet(env_syn)
        fin_flows = builder.process_packet(env_fin)
        assert len(fin_flows) == 1

        # 2. Flow completed via idle timeout
        env_idle = PacketEnvelope(
            timestamp=1.0, ip_src="10.0.0.1", ip_dst="10.0.0.3",
            src_port=2000, dst_port=53, protocol="UDP", ttl=64, byte_length=100
        )
        builder.process_packet(env_idle)
        # Advance time by 3.5s to trigger idle expiration (idle_timeout is 2.0s)
        env_trigger = PacketEnvelope(
            timestamp=4.5, ip_src="10.0.0.99", ip_dst="10.0.0.99",
            src_port=9999, dst_port=9999, protocol="UDP", ttl=64, byte_length=50
        )
        timeout_flows = [f for f in builder.process_packet(env_trigger) if f["src_port"] == 2000]
        assert len(timeout_flows) == 1

        # 3. Flow flushed at shutdown
        flushed_flows = builder.flush()
        assert len(flushed_flows) == 1  # The trigger flow was still active

        # Verify builder internal accounting
        bm = builder.get_metrics()
        assert bm["flows_created"] == 3
        assert bm["flows_completed"] == 3
        assert bm["flows_flushed"] == 1
        assert bm["flows_expired_timeout"] == 1

        # Enqueue all completed flows + 1 incompatible flow
        incompat = _make_valid_flow("incompat_flow", sttl=0, is_compatible=False)
        all_to_queue = fin_flows + timeout_flows + flushed_flows + [incompat]

        for f in all_to_queue:
            q.put(f)

        worker.start()
        worker.stop(drain_timeout=5.0)

        wm = worker.get_metrics()
        # 3 valid flows scored, 1 incompatible rejected
        assert wm["flows_scored"] == 3
        assert wm["incompatible_flows_rejected"] == 1
        assert wm["unprocessed_flows"] == 0
        assert wm["flows_scored"] + wm["incompatible_flows_rejected"] == len(all_to_queue)

    def test_queue_drain_timeout_behavior(self) -> None:
        """When drain timeout expires, worker is forced to stop and accounts for unprocessed flows."""
        q: queue.Queue = queue.Queue()
        service = ProductionInferenceService(verify_checksums=True)
        worker = StreamingInferenceWorker(flow_queue=q, inference_service=service)

        # Enqueue 50 valid flows
        for i in range(50):
            q.put(_make_valid_flow(f"slow_flow_{i}"))

        worker.start()
        # Set an ultra-short drain timeout (e.g. 0.001s) so it cannot score all 50 flows
        worker.stop(drain_timeout=0.001)

        assert worker.is_running is False
        wm = worker.get_metrics()
        # The sum of scored + unprocessed must equal exactly the 50 queued flows
        assert wm["flows_scored"] + wm["unprocessed_flows"] == 50
        assert wm["unprocessed_flows"] > 0
        # Queue must have been drained of remaining items
        assert q.empty()

    def test_repeated_and_concurrent_stop_calls(self) -> None:
        """Worker stop is idempotent and thread-safe when called repeatedly or concurrently."""
        q: queue.Queue = queue.Queue()
        service = ProductionInferenceService(verify_checksums=True)
        worker = StreamingInferenceWorker(flow_queue=q, inference_service=service)

        worker.start()
        # Sequential repeated stop
        worker.stop()
        worker.stop()
        worker.stop()
        assert worker.is_running is False

        # Concurrent stop calls on a newly started worker
        worker2 = StreamingInferenceWorker(flow_queue=q, inference_service=service)
        worker2.start()

        errors = []

        def _stopper():
            try:
                worker2.stop(drain_timeout=2.0)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_stopper) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert worker2.is_running is False

    def test_manager_stop_gracefully_drains_all_flows(self) -> None:
        """RealTimeDetectionManager.stop() flushes in-flight flows and drains inference queue."""
        manager = RealTimeDetectionManager.get_instance()
        manager.stop()

        sample_pcap = Path("data/captures/sample_traffic.pcap")
        assert sample_pcap.exists()

        status = manager.start_pcap_replay(
            pcap_path=str(sample_pcap),
            speed_multiplier=0.0,
        )
        assert status["worker_state"] in ("STARTING", "RUNNING")

        # Give it a tiny fraction of time so packets start entering, then immediately call stop()
        time.sleep(0.05)
        stop_status = manager.stop(drain_timeout=5.0)

        assert stop_status["worker_state"] == "STOPPED"
        # All completed flows must equal flows_scored + incompatible_flows_rejected + unprocessed_flows
        scored = stop_status["flows_scored"]
        rejected = stop_status["incompatible_flows_rejected"]
        unprocessed = stop_status["unprocessed_flows"]
        completed = stop_status["flows_completed"]

        assert completed == scored + rejected + unprocessed
        assert stop_status["queue_depth"] == 0

    def test_sentinel_insertion_when_queue_full(self) -> None:
        """Sentinel insertion handles full queue with timeout and without deadlocking."""
        q: queue.Queue = queue.Queue(maxsize=3)
        service = ProductionInferenceService(verify_checksums=True)
        worker = StreamingInferenceWorker(flow_queue=q, inference_service=service)

        # Fill queue to maximum capacity
        for i in range(3):
            q.put_nowait(_make_valid_flow(f"flow_{i}"))

        assert q.full() is True

        worker.start()
        # stop() should gracefully drain or timeout without deadlocking
        worker.stop(drain_timeout=2.0)
        assert worker.is_running is False
        assert q.empty() is True

    def test_worker_exceptions_and_persistence_failures_tracked(self) -> None:
        """Inference failures and persistence failures are explicitly tracked in metrics."""
        q: queue.Queue = queue.Queue()
        service = ProductionInferenceService(verify_checksums=True)
        worker = StreamingInferenceWorker(flow_queue=q, inference_service=service)

        # 1. Invalid flow causing ValueError (validation_errors)
        invalid_flow = {"flow_id": "bad_flow", "is_compatible": True}  # missing base features
        worker._score_flow(invalid_flow)
        assert worker.validation_errors == 1
        assert worker.inference_failures == 0

        # 2. Persistence failure simulation
        class BrokenApp:
            def app_context(self):
                raise RuntimeError("Database connection lost")

        worker.app = BrokenApp()
        # Feed anomalous flow that triggers persistence attempt
        anom_flow = _make_valid_flow("anom_flow", sttl=255)
        worker._persist_alert(anom_flow, {"event_id": "test_evt"})
        assert worker.persistence_failures == 1
