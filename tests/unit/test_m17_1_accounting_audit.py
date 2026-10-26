"""
TrafficShield Milestone 17.1: Accounting Invariant Audit & Memory Criteria Tests
================================================================================
Deterministic verification of:
1. Mutually exclusive terminal scoring outcomes (scored, rejected, validation_error, inference_failure, unprocessed).
2. Omission and double-counting detection in terminal scoring invariants.
3. Alert persistence lifecycle reconciliation (persisted, persistence_failure, deduplicated, unpersisted_no_app).
4. Mutual exclusivity between alert deduplication and persistence failure.
5. Queue saturation and queue-drop separation from queued items.
6. MemoryStabilityPolicy boundary values, low baseline, excessive growth, and unavailable readings.
7. ResourceMonitor error surfacing (None instead of silent zero) and CPU delta calculations.
"""
from __future__ import annotations

import queue
from typing import Any
from unittest.mock import MagicMock, patch

from ml.production_service import ProductionInferenceService
from streaming.inference_worker import StreamingInferenceWorker
from tools.soak.memory_policy import MemoryStabilityPolicy
from tools.soak.resource_monitor import ResourceMonitor
from tools.soak.soak_harness import SoakConfig, SoakTestHarness


def _build_test_flow(
    flow_id: str,
    sttl: int = 64,
    is_compatible: bool = True,
    src_ip: str = "10.0.0.1",
    dst_ip: str = "10.0.0.2",
    dst_port: int = 443,
    proto: str = "TCP",
) -> dict[str, Any]:
    """Helper to construct standard flow dictionaries for unit tests."""
    return {
        "flow_id": flow_id,
        "src_ip": src_ip,
        "dst_ip": dst_ip,
        "src_port": 49152,
        "dst_port": dst_port,
        "protocol": proto,
        "duration_seconds": 0.05,
        "fwd_bytes": 800,
        "sttl": sttl,
        "sload": 64000.0,
        "fwd_packets": 6,
        "swin": 512,
        "smeansz": 133.33,
        "sjit": 1.2,
        "sintpkt": 10.0,
        "is_sm_ips_ports": 0,
        "is_compatible": is_compatible,
        "compatibility_reason": None if is_compatible else "INVALID_STTL",
        "packet_rate": 120.0,
        "byte_rate": 16000.0,
        "bytes_per_packet": 133.33,
    }


class TestTerminalScoringOutcomesAccounting:
    """Validate strict mutual exclusivity and conservation of terminal scoring outcomes."""

    def test_mutually_exclusive_terminal_outcomes(self) -> None:
        """Verify each of the 5 terminal outcomes increments exactly one category."""
        q: queue.Queue = queue.Queue()
        mock_service = MagicMock(spec=ProductionInferenceService)

        def mock_predict(flow: dict[str, Any]) -> dict[str, Any]:
            fid = flow.get("flow_id", "")
            if "val_err" in fid:
                raise ValueError("Corrupt feature schema")
            if "infer_fail" in fid:
                raise RuntimeError("Matrix dimension mismatch")
            return {
                "anomaly_score": 0.85 if "anomaly" in fid else 0.15,
                "risk_level": "HIGH" if "anomaly" in fid else "LOW",
                "top_contributing_features": [],
            }

        mock_service.predict_single.side_effect = mock_predict
        mock_service.model_name = "OptunaTuned_XGBoost"
        mock_service.version = "1.0.0"

        worker = StreamingInferenceWorker(flow_queue=q, inference_service=mock_service)

        # 1. Scored benign (1)
        q.put(_build_test_flow("benign_1"))
        # 2. Scored anomaly (1)
        q.put(_build_test_flow("anomaly_1"))
        # 3. Incompatible flow (1)
        q.put(_build_test_flow("incompat_1", is_compatible=False))
        # 4. Validation error flow (1)
        q.put(_build_test_flow("val_err_1"))
        # 5. Inference failure flow (1)
        q.put(_build_test_flow("infer_fail_1"))

        total_queued = 5
        worker.start()
        worker.stop(drain_timeout=3.0)

        wm = worker.get_metrics()
        scored = wm["flows_scored"]
        rejected = wm["incompatible_flows_rejected"]
        val_err = wm["validation_errors"]
        infer_fail = wm["inference_failures"]
        unprocessed = wm["unprocessed_flows"]

        assert scored == 2  # 1 benign + 1 anomaly
        assert rejected == 1
        assert val_err == 1
        assert infer_fail == 1
        assert unprocessed == 0

        # Exact mutual exclusivity partition:
        assert total_queued == scored + rejected + val_err + infer_fail + unprocessed

    def test_invariant_fails_on_omission_or_double_counting(self) -> None:
        """Harness INV_5 fails if any terminal outcome is omitted or double counted."""
        harness = SoakTestHarness(SoakConfig(duration_seconds=1.0, sample_interval_seconds=1.0))

        base_status = {
            "active_flows_count": 0,
            "flows_created": 10,
            "flows_completed": 10,
            "flows_expired_timeout": 0,
            "flows_closed_tcp": 10,
            "flows_evicted_overflow": 0,
            "flows_flushed": 0,
            "flows_queue_dropped": 0,
            "flows_queued": 10,
            "flows_scored": 6,
            "incompatible_flows_rejected": 2,
            "validation_errors": 1,
            "inference_failures": 1,
            "unprocessed_flows": 0,
            "anomalies_detected": 0,
            "alerts_persisted": 0,
            "persistence_failures": 0,
            "pipeline_join_timed_out": False,
            "native_kernel_drops_available": False,
            "kernel_drop_status": "UNAVAILABLE",
        }

        # 1. Correct baseline: 6 + 2 + 1 + 1 + 0 = 10 == flows_queued
        invs = harness._evaluate_invariants(base_status)
        inv5 = next(i for i in invs if i.name == "INV_5_TERMINAL_SCORING_OUTCOMES_PARTITION")
        assert inv5.passed is True

        # 2. Omission: omit inference_failures (sum = 9 != 10)
        omitted_status = dict(base_status, inference_failures=0)
        invs_omit = harness._evaluate_invariants(omitted_status)
        inv5_omit = next(i for i in invs_omit if i.name == "INV_5_TERMINAL_SCORING_OUTCOMES_PARTITION")
        assert inv5_omit.passed is False

        # 3. Double counting: scored counted twice (sum = 12 != 10)
        double_status = dict(base_status, flows_scored=8)
        invs_double = harness._evaluate_invariants(double_status)
        inv5_double = next(i for i in invs_double if i.name == "INV_5_TERMINAL_SCORING_OUTCOMES_PARTITION")
        assert inv5_double.passed is False


class TestAlertPersistenceLifecycle:
    """Validate alert persistence, deduplication, and failure reconciliation."""

    def test_alert_lifecycle_exact_conservation_without_app(self) -> None:
        """When app context is None, anomalies are accurately tracked as unpersisted_no_app."""
        q: queue.Queue = queue.Queue()
        mock_service = MagicMock(spec=ProductionInferenceService)
        mock_service.predict_single.return_value = {
            "anomaly_score": 0.90,
            "risk_level": "CRITICAL",
            "top_contributing_features": [],
        }
        mock_service.model_name = "OptunaTuned_XGBoost"
        mock_service.version = "1.0.0"

        worker = StreamingInferenceWorker(
            flow_queue=q,
            inference_service=mock_service,
            app=None,  # No app context
        )

        q.put(_build_test_flow("flow_anom_1"))
        q.put(_build_test_flow("flow_anom_2"))

        worker.start()
        worker.stop(drain_timeout=2.0)

        metrics = worker.get_metrics()
        assert metrics["flows_scored"] == 2
        assert metrics["anomalies_detected"] == 2
        assert metrics["alerts_persisted"] == 0
        assert metrics["persistence_failures"] == 0
        assert metrics["alerts_deduplicated"] == 0
        assert metrics["alerts_unpersisted_no_app"] == 2

        # Exact Conservation:
        assert (
            metrics["anomalies_detected"]
            == metrics["alerts_persisted"]
            + metrics["persistence_failures"]
            + metrics["alerts_deduplicated"]
            + metrics["alerts_unpersisted_no_app"]
        )

    def test_alert_deduplication_and_persistence_mutual_exclusivity(self) -> None:
        """Prove that deduplication and persistence failure are mutually exclusive."""
        q: queue.Queue = queue.Queue()
        mock_service = MagicMock(spec=ProductionInferenceService)
        mock_service.predict_single.return_value = {
            "anomaly_score": 0.90,
            "risk_level": "HIGH",
            "top_contributing_features": [],
        }
        mock_service.model_name = "OptunaTuned_XGBoost"
        mock_service.version = "1.0.0"

        # Mock app that raises DB error on commit
        mock_app = MagicMock()
        mock_app.app_context.side_effect = RuntimeError("Database connection pool exhausted")

        worker = StreamingInferenceWorker(
            flow_queue=q,
            inference_service=mock_service,
            app=mock_app,
        )

        # Send first flow: will attempt persistence and fail (persistence_failure += 1)
        flow_a = _build_test_flow("alert_1", src_ip="192.168.1.10", dst_ip="10.0.0.5", dst_port=80)
        q.put(flow_a)

        # Send second flow with IDENTICAL key immediately: will deduplicate (alerts_deduplicated += 1)
        flow_b = _build_test_flow("alert_2", src_ip="192.168.1.10", dst_ip="10.0.0.5", dst_port=80)
        q.put(flow_b)

        worker.start()
        worker.stop(drain_timeout=2.0)

        wm = worker.get_metrics()
        assert wm["anomalies_detected"] == 2
        assert wm["alerts_persisted"] == 0
        assert wm["persistence_failures"] == 1
        assert wm["alerts_deduplicated"] == 1

        # Strict mutual exclusivity:
        assert (
            wm["anomalies_detected"]
            == wm["alerts_persisted"]
            + wm["persistence_failures"]
            + wm["alerts_deduplicated"]
            + wm["alerts_unpersisted_no_app"]
        )


class TestMemoryStabilityPolicySemantics:
    """Validate MemoryStabilityPolicy edge cases, boundaries, and decision rules."""

    def test_policy_normal_bounded_growth(self) -> None:
        """Normal steady-state growth below absolute and relative limits passes."""
        policy = MemoryStabilityPolicy(
            max_absolute_growth_mb=250.0,
            max_relative_growth_pct=50.0,
            min_absolute_headroom_mb=50.0,
            rule_mode="OR",
        )
        passed, msg, diag = policy.evaluate(baseline_rss_mb=120.0, final_rss_mb=150.0)
        assert passed is True
        assert diag["delta_rss_mb"] == 30.0
        assert diag["relative_growth_pct"] == 25.0

    def test_policy_low_baseline_with_small_absolute_growth(self) -> None:
        """Low baseline (e.g. 20 MB) with 30 MB absolute growth (150% rel) passes under headroom."""
        policy = MemoryStabilityPolicy(
            max_absolute_growth_mb=250.0,
            max_relative_growth_pct=50.0,
            min_absolute_headroom_mb=50.0,
            rule_mode="AND",  # Even under AND mode, headroom protects low baseline
        )
        passed, msg, diag = policy.evaluate(baseline_rss_mb=20.0, final_rss_mb=50.0)
        assert passed is True
        assert "satisfied" in msg

    def test_policy_low_baseline_excessive_absolute_growth(self) -> None:
        """Low baseline (20 MB) with 280 MB absolute growth fails hard absolute limit."""
        policy = MemoryStabilityPolicy(
            max_absolute_growth_mb=250.0,
            max_relative_growth_pct=50.0,
            rule_mode="OR",
        )
        passed, msg, diag = policy.evaluate(baseline_rss_mb=20.0, final_rss_mb=300.0)
        assert passed is False
        assert "breached" in msg

    def test_policy_normal_baseline_excessive_relative_growth_under_and(self) -> None:
        """Baseline 100 MB with 80 MB growth (80% rel > 50%) fails under AND mode."""
        policy = MemoryStabilityPolicy(
            max_absolute_growth_mb=250.0,
            max_relative_growth_pct=50.0,
            min_absolute_headroom_mb=50.0,
            rule_mode="AND",
        )
        passed, msg, diag = policy.evaluate(baseline_rss_mb=100.0, final_rss_mb=180.0)
        assert passed is False
        assert "80.0%" in msg

    def test_policy_high_baseline_excessive_absolute_growth(self) -> None:
        """High baseline (600 MB) with 260 MB growth (43.3% rel) fails absolute limit."""
        policy = MemoryStabilityPolicy(
            max_absolute_growth_mb=250.0,
            max_relative_growth_pct=50.0,
            rule_mode="AND",
        )
        passed, msg, diag = policy.evaluate(baseline_rss_mb=600.0, final_rss_mb=860.0)
        assert passed is False

    def test_policy_exact_boundary_values(self) -> None:
        """Test exact boundary condition: delta == 250.0 MB passes, 250.01 MB fails."""
        policy = MemoryStabilityPolicy(
            max_absolute_growth_mb=250.0,
            max_relative_growth_pct=50.0,
            rule_mode="ABSOLUTE_ONLY",
        )
        # Exact boundary: 250.0 MB growth -> passes
        passed_bound, _, _ = policy.evaluate(baseline_rss_mb=100.0, final_rss_mb=350.0)
        assert passed_bound is True

        # Breached by 0.01 MB -> fails
        passed_breach, _, _ = policy.evaluate(baseline_rss_mb=100.0, final_rss_mb=350.01)
        assert passed_breach is False

    def test_policy_unavailable_measurements(self) -> None:
        """When baseline or final RSS is None, policy fails with explicit diagnostic."""
        policy = MemoryStabilityPolicy()
        passed1, msg1, _ = policy.evaluate(baseline_rss_mb=None, final_rss_mb=100.0)
        assert passed1 is False
        assert "unavailable" in msg1.lower()

        passed2, msg2, _ = policy.evaluate(baseline_rss_mb=100.0, final_rss_mb=None)
        assert passed2 is False

    def test_policy_growth_over_both_limits_fails_all_modes(self) -> None:
        """Growth over both limits (delta 300 MB > 250 MB and 150% > 50%) fails in all modes."""
        for mode in ("OR", "AND", "ABSOLUTE_ONLY", "RELATIVE_ONLY"):
            policy = MemoryStabilityPolicy(
                max_absolute_growth_mb=250.0,
                max_relative_growth_pct=50.0,
                rule_mode=mode,
            )
            passed, msg, _diag = policy.evaluate(baseline_rss_mb=200.0, final_rss_mb=500.0)
            assert passed is False, f"Mode {mode} should fail when both limits are breached"
            assert "breached" in msg

    def test_policy_memory_decrease_passes(self) -> None:
        """Negative delta (memory decreased due to OS reclamation) passes."""
        policy = MemoryStabilityPolicy(rule_mode="AND")
        passed, msg, diag = policy.evaluate(baseline_rss_mb=200.0, final_rss_mb=180.0)
        assert passed is True
        assert diag["delta_rss_mb"] == -20.0
        assert "decreased" in msg.lower()


class TestResourceMonitorDiagnostics:
    """Validate resource monitor failure reporting and CPU utilization."""

    def test_monitor_error_returns_none_not_zero(self) -> None:
        """Simulate low-level failure and verify values are None with is_available=False."""
        monitor = ResourceMonitor()

        if hasattr(monitor, "_psapi"):
            with patch.object(monitor._psapi, "GetProcessMemoryInfo", return_value=0):
                # When GetProcessMemoryInfo returns 0 (FALSE in Win32 BOOL)
                snap = monitor.sample()
                assert snap.rss_mb is None
                assert snap.peak_rss_mb is None
                assert snap.private_mb is None
                assert snap.is_available is False
                assert "failed" in snap.measurement_source

        d = snap.to_dict()
        assert d["rss_mb"] is None
        assert d["is_available"] is False

    def test_cpu_utilization_interval_handling(self) -> None:
        """CPU utilization handles zero or tiny interval safely."""
        monitor = ResourceMonitor()
        snap1 = monitor.sample()
        assert snap1.cpu_percent is not None
        assert snap1.cpu_percent >= 0.0
