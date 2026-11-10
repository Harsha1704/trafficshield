"""
TrafficShield — Phase 5 Batch 3: Monitoring Reliability, Persistence & Retention Tests
======================================================================================
Tests:
- Telemetry validation (records & predictions collections, length matching, numeric scores, range, finite, types)
- Empty batch handling
- Score histogram (10 uniform bins over [0.0, 1.0])
- Feature statistics aggregation safety (handling non-numeric, NaNs, infinities)
- Database persistence reliability & error handling
- Transaction rollback and scoped session recovery
- Alert transaction coupling (atomic batch metric + alert persistence)
- Alert debouncing & occurrence count
- Controlled retention management (positive integer validation, UTC cutoff, dry-run, never touches other tables)
- Flask CLI commands for retention management
- Predict batch API resilience (successful inference even when telemetry fails)
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.database.models import (
    GroundTruthFeedback,
    MonitoringAlert,
    MonitoringBatchMetric,
    SecurityAlert,
    User,
)
from app.extensions import db
from monitoring.service import MonitoringService


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _make_sample_record(i: int = 0, **kwargs: Any) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "duration_seconds": 0.5,
        "fwd_bytes": 1000.0,
        "sttl": 64.0,
        "sload": 20000.0,
        "fwd_packets": 10.0,
        "swin": 255.0,
        "smeansz": 100.0,
        "sjit": 5.0,
        "sintpkt": 5.0,
        "is_sm_ips_ports": 0.0,
    }
    rec.update(kwargs)
    return rec


def _make_sample_prediction(
    score: float = 0.15,
    is_anomaly: bool = False,
    risk_level: str = "LOW",
    **kwargs: Any,
) -> dict[str, Any]:
    pred: dict[str, Any] = {
        "anomaly_score": score,
        "is_anomaly": is_anomaly,
        "risk_level": risk_level,
    }
    pred.update(kwargs)
    return pred


def _create_batch_metric(batch_id: str, timestamp: datetime, **kwargs: Any) -> MonitoringBatchMetric:
    data: dict[str, Any] = {
        "batch_id": batch_id,
        "timestamp": timestamp,
        "model_name": "OptunaTuned_XGBoost",
        "model_version": "1.0.0",
        "artifact_hash": "c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495",
        "decision_threshold": 0.5,
        "source": "batch_upload",
        "flow_count": 1,
        "anomaly_count": 0,
        "anomaly_rate": 0.0,
        "mean_score": 0.0,
        "p95_score": 0.0,
        "latency_ms": 10.0,
    }
    data.update(kwargs)
    return MonitoringBatchMetric(**data)


# ============================================================================
# A. Telemetry Validation Tests
# ============================================================================


@pytest.mark.unit
class TestTelemetryValidation:
    """Verify validation of records, predictions, schemas, and values."""

    def test_valid_batch_telemetry_calculations(self, app):
        """Verify metric calculations (flow count, anomaly rate, mean, p95, histogram, severities)."""
        with app.app_context():
            service = MonitoringService(retention_days=30)
            records = [_make_sample_record(i) for i in range(20)]
            # 5 anomalies, 15 normal
            predictions = []
            for _ in range(5):
                predictions.append(_make_sample_prediction(score=0.85, is_anomaly=True, risk_level="CRITICAL"))
            for _ in range(15):
                predictions.append(_make_sample_prediction(score=0.10, is_anomaly=False, risk_level="LOW"))

            metric = service.record_batch_telemetry(
                batch_id="test-valid-calc-001",
                records=records,
                predictions=predictions,
                latency_ms=45.2,
                source="test_runner",
            )

            assert metric.batch_id == "test-valid-calc-001"
            assert metric.flow_count == 20
            assert metric.anomaly_count == 5
            assert metric.anomaly_rate == pytest.approx(25.0, abs=1e-2)
            # 5 * 0.85 + 15 * 0.10 = 4.25 + 1.5 = 5.75 / 20 = 0.2875
            assert metric.mean_score == pytest.approx(0.2875, abs=1e-3)
            assert metric.p95_score >= 0.80
            assert metric.latency_ms == pytest.approx(45.2, abs=1e-2)

            # Severity breakdown
            assert metric.severity_counts["CRITICAL"] == 5
            assert metric.severity_counts["LOW"] == 15
            assert metric.severity_counts["HIGH"] == 0
            assert metric.severity_counts["MEDIUM"] == 0

            # Histogram: 10 uniform bins over [0.0, 1.0]
            assert len(metric.score_histogram) == 10
            assert sum(metric.score_histogram) == 20

    def test_mismatched_records_predictions_lengths(self, app):
        """Verify that record and prediction length mismatch raises ValueError."""
        with app.app_context():
            service = MonitoringService()
            records = [_make_sample_record(i) for i in range(5)]
            predictions = [_make_sample_prediction() for _ in range(4)]

            with pytest.raises(ValueError, match="does not match predictions count"):
                service.record_batch_telemetry(
                    batch_id="test-mismatch-001",
                    records=records,
                    predictions=predictions,
                    latency_ms=10.0,
                )

    def test_empty_batches_rejected(self, app):
        """Verify that empty records or predictions lists are rejected."""
        with app.app_context():
            service = MonitoringService()

            with pytest.raises(ValueError, match="cannot be empty"):
                service.record_batch_telemetry(
                    batch_id="test-empty-001",
                    records=[],
                    predictions=[],
                    latency_ms=10.0,
                )

            with pytest.raises(ValueError, match="cannot be empty"):
                service.record_batch_telemetry(
                    batch_id="test-empty-002",
                    records=[_make_sample_record()],
                    predictions=[],
                    latency_ms=10.0,
                )

    def test_invalid_collection_types_rejected(self, app):
        """Verify non-collection or string/bytes inputs are rejected."""
        with app.app_context():
            service = MonitoringService()

            with pytest.raises(ValueError, match="Flow records must be a non-null sequence"):
                service.record_batch_telemetry(
                    batch_id="test-type-001",
                    records="not_a_list",  # type: ignore[arg-type]
                    predictions=[_make_sample_prediction()],
                    latency_ms=10.0,
                )

            with pytest.raises(ValueError, match="Predictions must be a non-null sequence"):
                service.record_batch_telemetry(
                    batch_id="test-type-002",
                    records=[_make_sample_record()],
                    predictions=None,  # type: ignore[arg-type]
                    latency_ms=10.0,
                )

    def test_invalid_item_types_rejected(self, app):
        """Verify non-dictionary items in records or predictions raise ValueError."""
        with app.app_context():
            service = MonitoringService()

            with pytest.raises(ValueError, match="Flow record at index 0 must be a dictionary"):
                service.record_batch_telemetry(
                    batch_id="test-item-001",
                    records=["not_a_dict"],  # type: ignore[list-item]
                    predictions=[_make_sample_prediction()],
                    latency_ms=10.0,
                )

            with pytest.raises(ValueError, match="Prediction at index 0 must be a dictionary"):
                service.record_batch_telemetry(
                    batch_id="test-item-002",
                    records=[_make_sample_record()],
                    predictions=["not_a_dict"],  # type: ignore[list-item]
                    latency_ms=10.0,
                )

    def test_missing_required_prediction_fields(self, app):
        """Verify missing 'anomaly_score' or 'is_anomaly' is rejected."""
        with app.app_context():
            service = MonitoringService()

            # Missing anomaly_score
            with pytest.raises(ValueError, match="missing required field 'anomaly_score'"):
                service.record_batch_telemetry(
                    batch_id="test-req-001",
                    records=[_make_sample_record()],
                    predictions=[{"is_anomaly": False}],
                    latency_ms=10.0,
                )

            # Missing is_anomaly
            with pytest.raises(ValueError, match="missing required field 'is_anomaly'"):
                service.record_batch_telemetry(
                    batch_id="test-req-002",
                    records=[_make_sample_record()],
                    predictions=[{"anomaly_score": 0.2}],
                    latency_ms=10.0,
                )

    def test_non_finite_and_out_of_range_anomaly_scores(self, app):
        """Verify NaN, Inf, and out-of-range [0.0, 1.0] anomaly scores are rejected."""
        with app.app_context():
            service = MonitoringService()

            # NaN score
            with pytest.raises(ValueError, match="must be finite"):
                service.record_batch_telemetry(
                    batch_id="test-nan-001",
                    records=[_make_sample_record()],
                    predictions=[_make_sample_prediction(score=float("nan"))],
                    latency_ms=10.0,
                )

            # Positive Inf score
            with pytest.raises(ValueError, match="must be finite"):
                service.record_batch_telemetry(
                    batch_id="test-inf-001",
                    records=[_make_sample_record()],
                    predictions=[_make_sample_prediction(score=float("inf"))],
                    latency_ms=10.0,
                )

            # Negative Inf score
            with pytest.raises(ValueError, match="must be finite"):
                service.record_batch_telemetry(
                    batch_id="test-ninf-001",
                    records=[_make_sample_record()],
                    predictions=[_make_sample_prediction(score=float("-inf"))],
                    latency_ms=10.0,
                )

            # Out of range: < 0.0
            with pytest.raises(ValueError, match="out of range"):
                service.record_batch_telemetry(
                    batch_id="test-range-001",
                    records=[_make_sample_record()],
                    predictions=[_make_sample_prediction(score=-0.05)],
                    latency_ms=10.0,
                )

            # Out of range: > 1.0
            with pytest.raises(ValueError, match="out of range"):
                service.record_batch_telemetry(
                    batch_id="test-range-002",
                    records=[_make_sample_record()],
                    predictions=[_make_sample_prediction(score=1.05)],
                    latency_ms=10.0,
                )

    def test_invalid_anomaly_flag_types(self, app):
        """Verify non-boolean is_anomaly is rejected."""
        with app.app_context():
            service = MonitoringService()

            with pytest.raises(ValueError, match="'is_anomaly' must be a boolean"):
                service.record_batch_telemetry(
                    batch_id="test-bool-001",
                    records=[_make_sample_record()],
                    predictions=[_make_sample_prediction(is_anomaly="true")],  # type: ignore[arg-type]
                    latency_ms=10.0,
                )

            with pytest.raises(ValueError, match="'is_anomaly' must be a boolean"):
                service.record_batch_telemetry(
                    batch_id="test-bool-002",
                    records=[_make_sample_record()],
                    predictions=[_make_sample_prediction(is_anomaly=1)],  # type: ignore[arg-type]
                    latency_ms=10.0,
                )

    def test_feature_aggregations_with_invalid_or_nonfinite_values(self, app):
        """Verify that non-numeric, NaN, or infinite flow feature values are handled safely."""
        with app.app_context():
            service = MonitoringService()
            records = [
                _make_sample_record(0, sttl="invalid_str", sload=float("nan")),
                _make_sample_record(1, sttl=64.0, sload=float("inf")),
                _make_sample_record(2, sttl=128.0, sload=30000.0),
            ]
            predictions = [_make_sample_prediction() for _ in range(3)]

            metric = service.record_batch_telemetry(
                batch_id="test-feat-safety-001",
                records=records,
                predictions=predictions,
                latency_ms=15.0,
            )

            assert metric.batch_id == "test-feat-safety-001"
            sttl_stats = metric.feature_metrics.get("sttl", {})
            # Only 64.0 and 128.0 are valid finite numbers
            assert sttl_stats.get("count") == 2
            assert sttl_stats.get("mean") == 96.0

            sload_stats = metric.feature_metrics.get("sload", {})
            # Only 30000.0 is valid finite
            assert sload_stats.get("count") == 1
            assert sload_stats.get("mean") == 30000.0


# ============================================================================
# B. Persistence Reliability & Session Recovery Tests
# ============================================================================


@pytest.mark.unit
class TestPersistenceReliabilityAndSessionRecovery:
    """Verify transaction rollback, error isolation, and scoped session usability."""

    def test_successful_telemetry_persistence(self, app):
        """Verify standard telemetry is persisted to the database and queryable."""
        with app.app_context():
            service = MonitoringService()
            b_id = f"test-persist-{datetime.now().timestamp()}"
            records = [_make_sample_record(i) for i in range(3)]
            predictions = [_make_sample_prediction() for _ in range(3)]

            service.record_batch_telemetry(
                batch_id=b_id,
                records=records,
                predictions=predictions,
                latency_ms=22.5,
            )

            queried = MonitoringBatchMetric.query.filter_by(batch_id=b_id).first()
            assert queried is not None
            assert queried.flow_count == 3
            assert queried.latency_ms == pytest.approx(22.5, abs=1e-2)

    def test_commit_failure_triggers_rollback_and_preserves_session(self, app):
        """Verify that database commit failure rolls back and leaves session fully functional."""
        with app.app_context():
            service = MonitoringService()
            records = [_make_sample_record()]
            predictions = [_make_sample_prediction()]

            # Force commit failure
            with patch.object(db.session, "commit", side_effect=SQLAlchemyError("Simulated write failure")):
                with pytest.raises(SQLAlchemyError, match="Simulated write failure"):
                    service.record_batch_telemetry(
                        batch_id="test-fail-commit-001",
                        records=records,
                        predictions=predictions,
                        latency_ms=10.0,
                    )

            # Verify session is clean and immediately reusable
            queried = db.session.query(MonitoringBatchMetric).filter_by(batch_id="test-fail-commit-001").first()
            assert queried is None

            # Verify subsequent query and write succeed on the same session
            service.record_batch_telemetry(
                batch_id="test-recovery-001",
                records=records,
                predictions=predictions,
                latency_ms=10.0,
            )
            recovered = db.session.query(MonitoringBatchMetric).filter_by(batch_id="test-recovery-001").first()
            assert recovered is not None
            assert recovered.batch_id == "test-recovery-001"

    def test_no_sensitive_flow_data_in_error_logs(self, app, caplog):
        """Verify error logs do not contain sensitive request or flow record payloads."""
        with app.app_context():
            service = MonitoringService()
            sensitive_marker = "SECRET_CREDENTIAL_FLOW_PAYLOAD_9999"
            records = [_make_sample_record(0, sensitive_field=sensitive_marker)]
            predictions = [_make_sample_prediction()]

            with patch.object(db.session, "commit", side_effect=SQLAlchemyError("Simulated DB connection failure")):
                with pytest.raises(SQLAlchemyError):
                    service.record_batch_telemetry(
                        batch_id="test-sanitize-log-001",
                        records=records,
                        predictions=predictions,
                        latency_ms=10.0,
                    )

            # Check all captured log output
            all_logs = caplog.text
            assert sensitive_marker not in all_logs
            assert "Simulated DB connection failure" in all_logs


# ============================================================================
# C. Alert Transaction Consistency Tests
# ============================================================================


@pytest.mark.unit
class TestAlertPersistenceConsistency:
    """Verify atomic transaction coupling between batch metrics and operational alerts."""

    def test_anomaly_rate_spike_alert_coupled_in_same_transaction(self, app):
        """Verify rate spike triggers alert and persists atomically with batch metric."""
        with app.app_context():
            service = MonitoringService()
            # 25 flows, 20 anomalies (80% rate, threshold is baseline 28.7 * 2 = 57.4%, count >= 20)
            records = [_make_sample_record(i) for i in range(25)]
            predictions = [_make_sample_prediction(score=0.9, is_anomaly=True, risk_level="CRITICAL") for _ in range(20)]
            predictions += [_make_sample_prediction(score=0.1, is_anomaly=False, risk_level="LOW") for _ in range(5)]

            b_id = f"test-spike-{datetime.now().timestamp()}"
            metric = service.record_batch_telemetry(
                batch_id=b_id,
                records=records,
                predictions=predictions,
                latency_ms=30.0,
            )

            assert metric.anomaly_rate == pytest.approx(80.0, abs=1e-2)

            # Check that alert was persisted in the same transaction
            alert = (
                MonitoringAlert.query.filter_by(
                    alert_type="ANOMALY_RATE_SPIKE",
                    target_feature="overall_traffic",
                )
                .order_by(MonitoringAlert.timestamp.desc())
                .first()
            )
            assert alert is not None
            assert alert.metric_value == pytest.approx(80.0, abs=1e-2)

    def test_latency_degradation_alert_and_debouncing(self, app):
        """Verify SLA violation creates alert and subsequent violation debounces by incrementing occurrence count."""
        with app.app_context():
            service = MonitoringService()
            records = [_make_sample_record()]
            predictions = [_make_sample_prediction()]

            # Batch 1: high latency (350ms > 250ms threshold)
            service.record_batch_telemetry(
                batch_id=f"test-lat-1-{datetime.now().timestamp()}",
                records=records,
                predictions=predictions,
                latency_ms=350.0,
            )

            alerts_1 = MonitoringAlert.query.filter_by(
                alert_type="LATENCY_DEGRADATION",
                target_feature="inference_engine",
            ).all()
            assert len(alerts_1) == 1
            assert alerts_1[0].occurrence_count == 1
            assert alerts_1[0].metric_value == pytest.approx(350.0, abs=1e-2)

            # Batch 2: second high latency (400ms) within cooldown -> debounces
            service.record_batch_telemetry(
                batch_id=f"test-lat-2-{datetime.now().timestamp()}",
                records=records,
                predictions=predictions,
                latency_ms=400.0,
            )

            alerts_2 = MonitoringAlert.query.filter_by(
                alert_type="LATENCY_DEGRADATION",
                target_feature="inference_engine",
            ).all()
            # Still 1 alert, but occurrence_count incremented to 2
            assert len(alerts_2) == 1
            assert alerts_2[0].occurrence_count == 2
            assert alerts_2[0].metric_value == pytest.approx(400.0, abs=1e-2)

    def test_failed_commit_rolls_back_both_metric_and_alert(self, app):
        """Verify that when metric commit fails, pending alerts are also cleanly rolled back."""
        with app.app_context():
            service = MonitoringService()
            records = [_make_sample_record(i) for i in range(25)]
            predictions = [_make_sample_prediction(score=0.9, is_anomaly=True, risk_level="CRITICAL") for _ in range(20)]
            predictions += [_make_sample_prediction(score=0.1, is_anomaly=False, risk_level="LOW") for _ in range(5)]

            # Clear alerts first
            MonitoringAlert.query.filter_by(alert_type="ANOMALY_RATE_SPIKE").delete()
            db.session.commit()

            b_id = "test-atomic-rollback-001"
            with patch.object(db.session, "commit", side_effect=SQLAlchemyError("Atomic rollback failure")):
                with pytest.raises(SQLAlchemyError):
                    service.record_batch_telemetry(
                        batch_id=b_id,
                        records=records,
                        predictions=predictions,
                        latency_ms=30.0,
                    )

            # Neither the metric nor the alert must exist
            assert MonitoringBatchMetric.query.filter_by(batch_id=b_id).first() is None
            assert MonitoringAlert.query.filter_by(alert_type="ANOMALY_RATE_SPIKE").first() is None


# ============================================================================
# D. Retention Management Tests
# ============================================================================


@pytest.mark.unit
class TestRetentionManagement:
    """Verify retention days validation, UTC cutoff boundary, dry-run, and isolation from other tables."""

    def test_retention_days_validation(self, app):
        """Verify positive integer enforcement (reject 0, negative, bools, strings, floats)."""
        with app.app_context():
            service = MonitoringService(retention_days=30)

            # Rejection of zero
            with pytest.raises(ValueError, match="positive integer"):
                service.purge_stale_metrics(retention_days=0)

            # Rejection of negative numbers
            with pytest.raises(ValueError, match="positive integer"):
                service.purge_stale_metrics(retention_days=-5)

            # Rejection of booleans (True / False)
            with pytest.raises(ValueError, match="integer"):
                service.purge_stale_metrics(retention_days=True)  # type: ignore[arg-type]

            with pytest.raises(ValueError, match="integer"):
                service.purge_stale_metrics(retention_days=False)  # type: ignore[arg-type]

            # Rejection of strings
            with pytest.raises(ValueError, match="integer"):
                service.purge_stale_metrics(retention_days="30")  # type: ignore[arg-type]

            # Rejection of floats
            with pytest.raises(ValueError, match="integer"):
                service.purge_stale_metrics(retention_days=14.5)  # type: ignore[arg-type]

            # Constructor validation
            with pytest.raises(ValueError, match="positive integer"):
                MonitoringService(retention_days=0)

            with pytest.raises(ValueError, match="positive integer"):
                MonitoringService(retention_days=-10)

    def test_dry_run_mode_does_not_delete(self, app):
        """Verify dry-run mode returns eligible count without deleting records."""
        with app.app_context():
            service = MonitoringService(retention_days=30)
            now = _utcnow()

            # Seed 2 old records (45 days old) and 1 recent record (2 days old)
            m_old1 = _create_batch_metric(batch_id="dry-old-1", timestamp=now - timedelta(days=45))
            m_old2 = _create_batch_metric(batch_id="dry-old-2", timestamp=now - timedelta(days=40))
            m_new = _create_batch_metric(batch_id="dry-new-1", timestamp=now - timedelta(days=2))
            db.session.add_all([m_old1, m_old2, m_new])
            db.session.commit()

            eligible = service.purge_stale_metrics(retention_days=30, dry_run=True)
            assert eligible >= 2

            # All 3 records still exist in database
            assert db.session.get(MonitoringBatchMetric, m_old1.id) is not None
            assert db.session.get(MonitoringBatchMetric, m_old2.id) is not None
            assert db.session.get(MonitoringBatchMetric, m_new.id) is not None

    def test_purge_boundary_and_execution(self, app):
        """Verify UTC boundary: timestamp < cutoff is deleted; timestamp >= cutoff is preserved."""
        with app.app_context():
            service = MonitoringService(retention_days=30)
            now = _utcnow()
            cutoff = now - timedelta(days=30)

            # Just older than cutoff (cutoff - 1 minute) -> deleted
            m_expired = _create_batch_metric(
                batch_id="purge-expired-01",
                timestamp=cutoff - timedelta(minutes=1),
            )
            # Just newer than cutoff (cutoff + 1 minute) -> kept
            m_retained_boundary = _create_batch_metric(
                batch_id="purge-retained-01",
                timestamp=cutoff + timedelta(minutes=1),
            )
            # Very recent -> kept
            m_recent = _create_batch_metric(
                batch_id="purge-recent-01",
                timestamp=now - timedelta(hours=1),
            )
            db.session.add_all([m_expired, m_retained_boundary, m_recent])
            db.session.commit()

            expired_id = m_expired.id
            boundary_id = m_retained_boundary.id
            recent_id = m_recent.id

            # Execute purge with retention_days=30
            deleted = service.purge_stale_metrics(retention_days=30, dry_run=False)
            assert deleted >= 1

            # Expired must be gone
            assert db.session.get(MonitoringBatchMetric, expired_id) is None
            # Retained boundary must still exist
            assert db.session.get(MonitoringBatchMetric, boundary_id) is not None
            # Recent must still exist
            assert db.session.get(MonitoringBatchMetric, recent_id) is not None

    def test_retention_never_touches_other_tables(self, app):
        """Verify that purging metrics never deletes SecurityAlert, MonitoringAlert, User, or Feedback records."""
        with app.app_context():
            service = MonitoringService(retention_days=1)
            old_time = _utcnow() - timedelta(days=60)

            # 1. Old SecurityAlert
            sec_alert = SecurityAlert(
                request_id="sec-alert-keep",
                timestamp=old_time,
                anomaly_score=0.99,
                is_anomaly=True,
                risk_level="CRITICAL",
                status="NEW",
                input_features={"duration_seconds": 0.5, "fwd_bytes": 1000},
            )
            # 2. Old MonitoringAlert
            mon_alert = MonitoringAlert(
                timestamp=old_time,
                alert_type="FEATURE_DRIFT",
                severity="CRITICAL",
                target_feature="sttl",
                metric_name="PSI",
                metric_value=0.45,
                threshold=0.25,
                sample_size=100,
                summary="Old drift alert",
                status="ACTIVE",
            )
            # 3. Old GroundTruthFeedback
            feedback = GroundTruthFeedback(
                created_at=old_time,
                flow_identifier="flow-keep-1",
                model_score=0.9,
                model_predicted_anomaly=True,
                analyst_disposition="CONFIRMED_THREAT",
            )
            # 4. Old MonitoringBatchMetric
            batch_metric = _create_batch_metric(
                batch_id="purge-target-metric",
                timestamp=old_time,
            )
            db.session.add_all([sec_alert, mon_alert, feedback, batch_metric])
            db.session.commit()

            sec_id = sec_alert.id
            mon_id = mon_alert.id
            fb_id = feedback.id
            batch_id = batch_metric.id

            # Purge with retention_days=1
            service.purge_stale_metrics(retention_days=1, dry_run=False)

            # Batch metric deleted
            assert db.session.get(MonitoringBatchMetric, batch_id) is None

            # All other records PRESERVED intact
            assert db.session.get(SecurityAlert, sec_id) is not None
            assert db.session.get(MonitoringAlert, mon_id) is not None
            assert db.session.get(GroundTruthFeedback, fb_id) is not None


# ============================================================================
# E. Retention CLI Command Tests
# ============================================================================


@pytest.mark.unit
class TestRetentionCliCommand:
    """Verify Flask CLI 'flask monitoring purge-metrics' command."""

    def test_cli_dry_run_default(self, app):
        """Verify CLI defaults to dry-run mode and does not delete records."""
        with app.app_context():
            now = _utcnow()
            metric = _create_batch_metric(
                batch_id="cli-dry-run-001",
                timestamp=now - timedelta(days=60),
            )
            db.session.add(metric)
            db.session.commit()
            m_id = metric.id

        runner = app.test_cli_runner()
        result = runner.invoke(args=["monitoring", "purge-metrics", "--days", "30"])
        assert result.exit_code == 0
        assert "Retention period: 30 days" in result.output
        assert "[DRY-RUN]" in result.output

        with app.app_context():
            assert db.session.get(MonitoringBatchMetric, m_id) is not None

    def test_cli_execute_cancelled_by_operator(self, app):
        """Verify CLI cancels operation if operator inputs 'n' to confirmation prompt."""
        with app.app_context():
            now = _utcnow()
            metric = _create_batch_metric(
                batch_id="cli-cancel-001",
                timestamp=now - timedelta(days=60),
            )
            db.session.add(metric)
            db.session.commit()
            m_id = metric.id

        runner = app.test_cli_runner()
        result = runner.invoke(args=["monitoring", "purge-metrics", "--execute", "--days", "30"], input="n\n")
        assert result.exit_code == 0
        assert "Operation cancelled" in result.output

        with app.app_context():
            assert db.session.get(MonitoringBatchMetric, m_id) is not None

    def test_cli_execute_confirmed_with_yes_flag(self, app):
        """Verify CLI with --execute and -y deletes eligible expired metrics."""
        with app.app_context():
            now = _utcnow()
            metric = _create_batch_metric(
                batch_id="cli-yes-001",
                timestamp=now - timedelta(days=60),
            )
            db.session.add(metric)
            db.session.commit()
            m_id = metric.id

        runner = app.test_cli_runner()
        result = runner.invoke(args=["monitoring", "purge-metrics", "--execute", "-y", "--days", "30"])
        assert result.exit_code == 0
        assert "Successfully purged" in result.output

        with app.app_context():
            assert db.session.get(MonitoringBatchMetric, m_id) is None

        with app.app_context():
            assert db.session.get(MonitoringBatchMetric, m_id) is None

    def test_cli_invalid_days_rejected(self, app):
        """Verify CLI rejects 0 or negative days with abort."""
        runner = app.test_cli_runner()
        result = runner.invoke(args=["monitoring", "purge-metrics", "--days", "0"])
        assert result.exit_code != 0
        assert "must be a positive integer" in result.output


# ============================================================================
# F. API Resilience Tests
# ============================================================================


@pytest.mark.unit
class TestApiResilience:
    """Verify endpoint resilience when telemetry operations fail."""

    def test_predict_batch_succeeds_even_when_telemetry_fails(self, client, app):
        """Verify /predict/batch returns HTTP 200 with predictions even if telemetry fails."""
        sample_flow = _make_sample_record(0)

        # Patch record_batch_telemetry to simulate unexpected persistence crash
        with patch.object(
            MonitoringService,
            "record_batch_telemetry",
            side_effect=RuntimeError("Simulated monitoring subsystem failure"),
        ):
            resp = client.post(
                "/api/v1/predict/batch",
                json={"records": [sample_flow]},
            )
            assert resp.status_code == 200
            body = resp.get_json()
            assert body["success"] is True
            assert "predictions" in body["data"]
            assert len(body["data"]["predictions"]) == 1

        # Verify database session is healthy for subsequent requests
        with app.app_context():
            user = db.session.query(User).filter_by(username="admin").first()
            assert user is not None

    def test_monitoring_status_endpoint_returns_kpis(self, client):
        """Verify /monitoring/status returns 200 and expected KPI telemetry."""
        resp = client.get("/api/v1/monitoring/status")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert "kpis" in body["data"]
        assert "total_batches_recorded" in body["data"]["kpis"]
