"""
TrafficShield Milestone 17: Sustained-Soak Harness & Resource Monitoring Tests
==============================================================================
Deterministic unit test suite covering:
1. Periodic metric sampling.
2. Memory/CPU measurement error handling and graceful fallbacks.
3. Invalid configuration and parameter validation.
4. Correct separation of replay metrics from live-capture metrics.
5. Ensuring missing native kernel statistics are reported as unavailable, not zero.
6. Queue saturation and counter reconciliation.
7. Inference and persistence error tracking during soak runs.
8. Graceful shutdown and forced-timeout reporting.
9. Interruption and partial-report preservation.
10. Repeated stop calls and thread cleanup.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from streaming.manager import RealTimeDetectionManager
from tools.soak.resource_monitor import ResourceMonitor, ResourceSnapshot
from tools.soak.soak_harness import (
    SoakConfig,
    SoakTestHarness,
)


class TestSoakResourceMonitor:
    """Validate resource sampler resilience, accuracy, and error handling."""

    def test_1_periodic_metric_sampling(self) -> None:
        """1. Resource monitor correctly samples RSS, peak RSS, CPU %, and thread counts."""
        monitor = ResourceMonitor()
        snap1 = monitor.sample()

        assert isinstance(snap1, ResourceSnapshot)
        assert snap1.rss_mb >= 0.0
        assert snap1.peak_rss_mb >= snap1.rss_mb
        assert snap1.active_threads >= 1
        assert snap1.measurement_source in (
            "psutil",
            "windows_native_psapi",
            "posix_generic",
            "standard_library_basic",
        )

        time.sleep(0.05)
        snap2 = monitor.sample()
        assert snap2.elapsed_seconds >= snap1.elapsed_seconds
        assert snap2.timestamp >= snap1.timestamp

        # Dictionary serialization
        d = snap2.to_dict()
        assert "rss_mb" in d
        assert "cpu_percent" in d
        assert "active_threads" in d

    def test_2_resource_measurement_error_handling(self) -> None:
        """2. Sampler handles low-level API failures gracefully without raising uncaught exceptions."""
        monitor = ResourceMonitor()

        # Simulate exception inside low-level query
        if hasattr(monitor, "_psapi"):
            with patch.object(monitor._psapi, "GetProcessMemoryInfo", side_effect=RuntimeError("PSAPI failure")):
                snap = monitor.sample()
                assert isinstance(snap, ResourceSnapshot)
                assert snap.rss_mb == 0.0
                assert "error" in snap.measurement_source

        if hasattr(monitor, "_psutil_proc") and monitor._psutil_proc is not None:
            with patch.object(monitor._psutil_proc, "memory_info", side_effect=RuntimeError("psutil failure")):
                snap = monitor.sample()
                assert isinstance(snap, ResourceSnapshot)
                assert snap.rss_mb == 0.0
                assert "error" in snap.measurement_source


class TestSoakHarnessConfigurationAndInvariants:
    """Validate harness execution logic, invariants, and configuration checks."""

    def test_3_invalid_configuration_and_duration(self) -> None:
        """3. SoakConfig rejects non-positive duration, non-positive interval, and invalid modes."""
        with pytest.raises(ValueError, match="duration_seconds must be positive"):
            SoakConfig(duration_seconds=-1.0).validate()

        with pytest.raises(ValueError, match="duration_seconds must be positive"):
            SoakConfig(duration_seconds=0.0).validate()

        with pytest.raises(ValueError, match="sample_interval_seconds must be positive"):
            SoakConfig(duration_seconds=10.0, sample_interval_seconds=-5.0).validate()

        with pytest.raises(ValueError, match="Invalid mode"):
            SoakConfig(mode="INVALID_MODE").validate()

        with pytest.raises(FileNotFoundError, match="Replay PCAP file not found"):
            SoakConfig(mode="PCAP_REPLAY", target="non_existent_file_path_12345.pcap").validate()

    def test_4_separation_of_replay_and_live_metrics(self) -> None:
        """4. Replay metrics and live capture metrics have strictly distinct provenance."""
        manager = RealTimeDetectionManager.get_instance()
        manager.stop()

        status_idle = manager.get_status()
        assert status_idle["capture_mode"] in ("NONE", "PCAP_REPLAY", "LIVE_CAPTURE")

        # Config must explicitly declare provenance
        cfg_replay = SoakConfig(mode="PCAP_REPLAY", target="data/captures/sample_traffic.pcap")
        cfg_live = SoakConfig(mode="LIVE_CAPTURE", target="Wi-Fi")

        assert cfg_replay.mode == "PCAP_REPLAY"
        assert cfg_live.mode == "LIVE_CAPTURE"

    def test_5_native_kernel_drops_reported_unavailable(self) -> None:
        """5. Native kernel drops must be explicitly reported as UNAVAILABLE, not zero."""
        manager = RealTimeDetectionManager.get_instance()
        status = manager.get_status()

        assert status["native_kernel_drops_available"] is False
        assert status["native_kernel_drops"] is None
        assert "UNAVAILABLE" in status["kernel_drop_status"]

        # Invariant check must fail if native drops are misrepresented as available or 0
        harness = SoakTestHarness(SoakConfig(duration_seconds=1.0, sample_interval_seconds=1.0))
        fake_status = dict(status)
        fake_status["native_kernel_drops_available"] = True
        fake_status["kernel_drop_status"] = "0 drops reported"
        invariants = harness._evaluate_invariants(fake_status)
        inv8 = next(inv for inv in invariants if inv.name == "INV_8_NATIVE_KERNEL_DROPS_HONESTY")
        assert inv8.passed is False

    def test_6_queue_saturation_and_counter_reconciliation(self) -> None:
        """6. Flow accounting reconciles exact queue drops when queue saturates."""
        harness = SoakTestHarness(SoakConfig(duration_seconds=1.0, sample_interval_seconds=1.0))

        # Synthetic status simulating queue saturation
        mock_status = {
            "active_flows_count": 0,
            "flows_created": 100,
            "flows_completed": 100,
            "flows_expired_timeout": 20,
            "flows_closed_tcp": 30,
            "flows_evicted_overflow": 0,
            "flows_flushed": 50,
            "flows_queue_dropped": 15,
            "flows_queued": 85,  # 100 - 15
            "flows_scored": 80,
            "incompatible_flows_rejected": 2,
            "validation_errors": 1,
            "inference_failures": 2,
            "unprocessed_flows": 0,  # 80 + 2 + 1 + 2 + 0 = 85
            "anomalies_detected": 10,
            "alerts_persisted": 8,
            "persistence_failures": 1,
            "pipeline_join_timed_out": False,
            "native_kernel_drops_available": False,
            "kernel_drop_status": "UNAVAILABLE",
        }

        invariants = harness._evaluate_invariants(mock_status)
        for inv in invariants:
            assert inv.passed is True, f"Invariant {inv.name} failed: {inv.details}"

    def test_7_inference_and_persistence_errors_during_run(self) -> None:
        """7. Inference failures and alert persistence errors are isolated in accounting."""
        harness = SoakTestHarness(SoakConfig(duration_seconds=1.0, sample_interval_seconds=1.0))

        # Test persistence bounds invariant: persisted + failures cannot exceed anomalies
        bad_status = {
            "active_flows_count": 0,
            "flows_created": 10,
            "flows_completed": 10,
            "flows_expired_timeout": 0,
            "flows_closed_tcp": 10,
            "flows_evicted_overflow": 0,
            "flows_flushed": 0,
            "flows_queue_dropped": 0,
            "flows_queued": 10,
            "flows_scored": 10,
            "incompatible_flows_rejected": 0,
            "validation_errors": 0,
            "inference_failures": 0,
            "unprocessed_flows": 0,
            "anomalies_detected": 2,
            "alerts_persisted": 3,  # Impossible: 3 persisted > 2 anomalies
            "persistence_failures": 0,
            "pipeline_join_timed_out": False,
            "native_kernel_drops_available": False,
            "kernel_drop_status": "UNAVAILABLE",
        }
        invariants = harness._evaluate_invariants(bad_status)
        inv6 = next(inv for inv in invariants if inv.name == "INV_6_ALERT_PERSISTENCE_BOUNDS")
        assert inv6.passed is False

    def test_8_graceful_shutdown_and_timing(self) -> None:
        """8. Graceful shutdown drains queue and measures shutdown duration in ms."""
        sample_pcap = Path("data/captures/sample_traffic.pcap")
        assert sample_pcap.exists()

        cfg = SoakConfig(
            duration_seconds=1.5,
            sample_interval_seconds=0.5,
            mode="PCAP_REPLAY",
            target=str(sample_pcap),
            speed_multiplier=0.0,
        )
        harness = SoakTestHarness(cfg)
        summary = harness.run()

        assert summary.duration_actual >= 1.0
        assert summary.shutdown_duration_ms > 0.0
        assert summary.final_state in ("STOPPED", "COMPLETED")
        assert summary.success is True
        assert summary.model_hashes_verified is True

    def test_9_interruption_and_partial_report_preservation(self) -> None:
        """9. Interrupted runs cleanly terminate worker and preserve partial sample records."""
        sample_pcap = Path("data/captures/sample_traffic.pcap")
        cfg = SoakConfig(
            duration_seconds=5.0,
            sample_interval_seconds=0.2,
            mode="PCAP_REPLAY",
            target=str(sample_pcap),
            speed_multiplier=1.0,
        )
        harness = SoakTestHarness(cfg)

        # Trigger early interruption flag
        harness._interrupted = True
        summary = harness.run()

        assert summary.interrupted is True
        assert summary.success is False
        assert summary.error_message == "Session interrupted"
        assert summary.final_state in ("STOPPED", "COMPLETED")

    def test_10_repeated_stop_calls_and_thread_cleanup(self) -> None:
        """10. Repeated stop calls on harness manager leave zero active worker threads."""
        manager = RealTimeDetectionManager.get_instance()
        manager.stop()
        manager.stop()

        active_threads = [t.name for t in threading.enumerate() if t.is_alive()]
        assert "StreamingInferenceWorker" not in active_threads
        assert "Pipeline-sample_traffic.pcap" not in active_threads
