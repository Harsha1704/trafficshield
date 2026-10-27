"""
TrafficShield Real-Time Network Traffic and Anomaly Correlation Tests
======================================================================
Validates:
1. Aligned 5-second UTC interval delta accounting.
2. Accurate counter differences for packets, bytes, Mbps, flows, anomalies, alerts, drops, and errors.
3. Resilience against counter resets and restarts (negative values clamped to 0).
4. Multi-interval gaps and burst attribution.
5. Session freeze into HISTORICAL summary upon stopping.
6. API routes /api/v1/capture/status and /api/v1/capture/telemetry.
7. Strict preservation of frozen XGBoost and preprocessor SHA-256 baselines.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app import create_app
from ingestion.capture.base import WorkerState
from ml.production_service import (
    EXPECTED_DETECTOR_SHA256,
    EXPECTED_PREPROCESSOR_SHA256,
)
from streaming.manager import RealTimeDetectionManager


class TestIntervalDeltaAccounting:
    """Validate aligned 5-second window progression and delta calculations."""

    def test_aligned_window_progression_and_deltas(self) -> None:
        manager = RealTimeDetectionManager()

        # Mock dependencies
        mock_source = MagicMock()
        mock_source.get_metrics.return_value = {
            "packets_captured": 100,
            "bytes_captured": 50_000,
            "packets_dropped": 2,
            "native_kernel_drops_available": True,
        }
        mock_flow_builder = MagicMock()
        mock_flow_builder.get_metrics.return_value = {
            "flows_created": 40,
        }
        mock_worker = MagicMock()
        mock_worker.get_metrics.return_value = {
            "flows_scored": 35,
            "anomalies_detected": 5,
            "alerts_persisted": 4,
            "alerts_deduplicated": 1,
            "validation_errors": 0,
            "inference_failures": 0,
            "mean_inference_latency_ms": 15.2,
            "latency_p50_ms": 14.8,
            "latency_p95_ms": 18.5,
            "latency_p99_ms": 22.1,
        }

        manager.packet_source = mock_source
        manager.flow_builder = mock_flow_builder
        manager.inference_worker = mock_worker
        manager.flows_queue_dropped = 1
        manager.state = WorkerState.RUNNING

        # Initialize at window 1000
        manager._current_window_start = 1000.0
        manager._window_start_totals = {
            "packets_observed": 0,
            "bytes_observed": 0,
            "flows_created": 0,
            "flows_scored": 0,
            "anomalies_detected": 0,
            "alerts_persisted": 0,
            "alerts_deduplicated": 0,
            "drops": 0,
            "errors": 0,
            "native_stats_available": True,
        }

        # Advance to time 1006.0 (crosses 1005 boundary)
        intervals = manager._update_intervals_locked(1006.0)

        # 1 completed window (1000..1005) + 1 current partial window (1005..1006)
        assert len(intervals) >= 1
        closed = intervals[0]
        assert closed["interval_seconds"] == 5.0
        assert closed["packets_captured"] == 100
        assert closed["bytes_captured"] == 50_000
        # Mbps = (50000 * 8) / (5.0 * 1_000_000) = 400000 / 5_000_000 = 0.08 Mbps
        assert closed["throughput_mbps"] == pytest.approx(0.08, rel=1e-3)
        assert closed["flows_created"] == 40
        assert closed["flows_scored"] == 35
        assert closed["anomalies_detected"] == 5
        assert closed["alerts_persisted"] == 4
        assert closed["alerts_deduplicated"] == 1
        assert closed["drops"] == 3  # 2 packet drops + 1 flow queue drop
        assert closed["errors"] == 0
        assert closed["native_stats_available"] is True

    def test_counter_resets_and_clamp_protection(self) -> None:
        """Ensure negative counter deltas from restarts or wraps clamp to zero."""
        manager = RealTimeDetectionManager()

        mock_source = MagicMock()
        # Source counters reset from 1000 to 10
        mock_source.get_metrics.return_value = {
            "packets_captured": 10,
            "bytes_captured": 200,
            "packets_dropped": 0,
            "native_kernel_drops_available": False,
        }
        mock_flow_builder = MagicMock()
        mock_flow_builder.get_metrics.return_value = {"flows_created": 0}
        mock_worker = MagicMock()
        mock_worker.get_metrics.return_value = {
            "flows_scored": 0,
            "anomalies_detected": 0,
            "alerts_persisted": 0,
            "alerts_deduplicated": 0,
            "validation_errors": 0,
            "inference_failures": 0,
        }

        manager.packet_source = mock_source
        manager.flow_builder = mock_flow_builder
        manager.inference_worker = mock_worker
        manager.flows_queue_dropped = 0
        manager.state = WorkerState.RUNNING

        manager._current_window_start = 1000.0
        # Baseline was higher before reset
        manager._window_start_totals = {
            "packets_observed": 500,
            "bytes_observed": 200_000,
            "flows_created": 100,
            "flows_scored": 100,
            "anomalies_detected": 10,
            "alerts_persisted": 10,
            "alerts_deduplicated": 0,
            "drops": 5,
            "errors": 2,
            "native_stats_available": False,
        }

        intervals = manager._update_intervals_locked(1006.0)
        closed = intervals[0]
        # Must be clamped to 0, not negative
        assert closed["packets_captured"] == 0
        assert closed["bytes_captured"] == 0
        assert closed["throughput_mbps"] == 0.0
        assert closed["drops"] == 0
        assert closed["errors"] == 0

    def test_multi_window_skip_produces_zero_delta_intermediate_intervals(self) -> None:
        """When time advances across multiple intervals, intermediate intervals are preserved with 0 deltas."""
        manager = RealTimeDetectionManager()

        mock_source = MagicMock()
        mock_source.get_metrics.return_value = {
            "packets_captured": 50,
            "bytes_captured": 10_000,
            "packets_dropped": 0,
            "native_kernel_drops_available": False,
        }
        mock_flow_builder = MagicMock()
        mock_flow_builder.get_metrics.return_value = {"flows_created": 10}
        mock_worker = MagicMock()
        mock_worker.get_metrics.return_value = {
            "flows_scored": 10,
            "anomalies_detected": 0,
            "alerts_persisted": 0,
            "alerts_deduplicated": 0,
            "validation_errors": 0,
            "inference_failures": 0,
        }

        manager.packet_source = mock_source
        manager.flow_builder = mock_flow_builder
        manager.inference_worker = mock_worker
        manager.flows_queue_dropped = 0
        manager.state = WorkerState.RUNNING

        manager._current_window_start = 1000.0
        manager._window_start_totals = {
            "packets_observed": 0,
            "bytes_observed": 0,
            "flows_created": 0,
            "flows_scored": 0,
            "anomalies_detected": 0,
            "alerts_persisted": 0,
            "alerts_deduplicated": 0,
            "drops": 0,
            "errors": 0,
            "native_stats_available": False,
        }

        # Jump from 1000 to 1021 (crosses 1005, 1010, 1015, 1020)
        manager._update_intervals_locked(1021.0)
        history = list(manager._interval_history)
        # Should have intervals for 1000, 1005, 1010, 1015
        assert len(history) == 4
        assert history[0]["packets_captured"] == 50
        assert history[1]["packets_captured"] == 0
        assert history[2]["packets_captured"] == 0
        assert history[3]["packets_captured"] == 0

    def test_session_freeze_and_historical_demarcation(self) -> None:
        """Stopping capture freezes cumulative numbers into HISTORICAL session summary."""
        manager = RealTimeDetectionManager()

        mock_source = MagicMock()
        mock_source.get_metrics.return_value = {
            "packets_captured": 987,
            "bytes_captured": 1_234_567,
            "packets_dropped": 15,
            "native_kernel_drops_available": True,
        }
        mock_worker = MagicMock()
        mock_worker.get_metrics.return_value = {
            "flows_scored": 987,
            "anomalies_detected": 404,
            "alerts_persisted": 300,
            "alerts_deduplicated": 104,
            "validation_errors": 1,
            "inference_failures": 0,
            "mean_inference_latency_ms": 16.4,
            "latency_p50_ms": 15.9,
            "latency_p95_ms": 21.0,
            "latency_p99_ms": 28.5,
        }

        manager.packet_source = mock_source
        manager.inference_worker = mock_worker
        manager.flows_queue_dropped = 2
        manager.state = WorkerState.STOPPED

        manager._finalize_session_summary_locked()
        summary = manager._session_summary

        assert summary is not None
        assert summary["is_historical"] is True
        assert summary["end_time"] is not None
        assert summary["total_packets"] == 987
        assert summary["total_bytes"] == 1_234_567
        assert summary["total_flows_scored"] == 987
        assert summary["total_anomalies"] == 404
        assert summary["total_alerts_persisted"] == 300
        assert summary["total_alerts_deduplicated"] == 104
        assert summary["mean_inference_latency_ms"] == 16.4
        assert summary["latency_p50_ms"] == 15.9
        assert summary["latency_p95_ms"] == 21.0
        assert summary["latency_p99_ms"] == 28.5
        assert summary["total_drops"] == 17  # 15 packet + 2 flow queue
        assert summary["total_errors"] == 1  # 1 validation + 0 infer


class TestCaptureApiTelemetryEndpoints:
    """Validate HTTP API status and telemetry endpoints return intervals and summary."""

    @pytest.fixture
    def client(self):
        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client

    def test_status_endpoint_includes_intervals_and_summary(self, client) -> None:
        res = client.get("/api/v1/capture/status")
        assert res.status_code == 200
        body = res.get_json()
        assert body["success"] is True
        data = body["data"]

        assert "bytes_observed" in data
        assert "intervals" in data
        assert isinstance(data["intervals"], list)
        assert "session_summary" in data

    def test_telemetry_endpoint_returns_granular_intervals(self, client) -> None:
        res = client.get("/api/v1/capture/telemetry")
        assert res.status_code == 200
        body = res.get_json()
        assert body["success"] is True
        data = body["data"]

        assert "worker_state" in data
        assert "bytes_observed" in data
        assert "packets_observed" in data
        assert "intervals" in data
        assert "session_summary" in data


class TestFrozenModelIntegrityPreservation:
    """Ensure frozen XGBoost and preprocessor artifacts remain completely unmodified."""

    def test_frozen_artifacts_strictly_preserved(self) -> None:
        detector_path = Path("artifacts/models/production_detector.joblib")
        prep_path = Path("artifacts/models/production_preprocessor.joblib")

        assert detector_path.exists(), "production_detector.joblib missing"
        assert prep_path.exists(), "production_preprocessor.joblib missing"

        with open(detector_path, "rb") as f:
            det_sha = hashlib.sha256(f.read()).hexdigest()
        assert det_sha == EXPECTED_DETECTOR_SHA256, (
            f"Detector checksum mismatch! Got {det_sha}, expected {EXPECTED_DETECTOR_SHA256}"
        )

        with open(prep_path, "rb") as f:
            prep_sha = hashlib.sha256(f.read()).hexdigest()
        assert prep_sha == EXPECTED_PREPROCESSOR_SHA256, (
            f"Preprocessor checksum mismatch! Got {prep_sha}, expected {EXPECTED_PREPROCESSOR_SHA256}"
        )
