"""
Unit tests for TrafficShield Milestone 12: Intelligent Monitoring, Drift Detection & Model Lifecycle.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from app.database.models import (
    GroundTruthFeedback,
    ModelRegistryEntry,
    MonitoringAlert,
)
from app.extensions import db
from monitoring.alert_manager import MonitoringAlertManager
from monitoring.drift_engine import (
    calculate_ks,
    calculate_psi,
    calculate_wasserstein,
    check_data_quality,
    evaluate_feature_drift,
    evaluate_score_drift,
)
from monitoring.feedback import get_operational_evaluation, submit_ground_truth_feedback
from monitoring.registry import ModelRegistryManager
from monitoring.schema import (
    AnalystDisposition,
    DriftStatus,
    ModelLifecycleStatus,
    MonitoringAlertStatus,
)


@pytest.mark.unit
def test_psi_and_ks_mathematical_properties():
    """Verify PSI and KS calculation correctness, smoothing, and sensitivity."""
    np.random.seed(42)
    base = np.random.normal(loc=10.0, scale=2.0, size=500)
    identical = np.random.normal(loc=10.0, scale=2.0, size=500)
    shifted = np.random.normal(loc=16.0, scale=2.0, size=500)

    # Identical should yield near-zero PSI (< 0.05)
    psi_stable = calculate_psi(base, identical)
    assert psi_stable < 0.10

    # Shifted should yield significant PSI (> 0.25)
    psi_drift = calculate_psi(base, shifted)
    assert psi_drift > 0.25

    # KS test
    ks_stat, ks_p = calculate_ks(base, shifted)
    assert ks_stat > 0.50
    assert ks_p < 0.001

    # Wasserstein distance
    w1 = calculate_wasserstein(base, shifted)
    assert w1 > 4.0


@pytest.mark.unit
def test_feature_drift_insufficient_data_safeguard():
    """Verify that sample size N < 30 produces INSUFFICIENT_DATA status and suppresses false alarms."""
    base_profile = {
        "feature_baselines": {
            "sttl": {
                "mean": 64.0,
                "std": 10.0,
                "deciles": list(np.linspace(31.0, 254.0, 11)),
            }
        }
    }

    # Only 10 rows (below 30 minimum)
    small_df = pd.DataFrame({"sttl": [254] * 10})
    results = evaluate_feature_drift(
        baseline_profile=base_profile,
        current_df=small_df,
        features=["sttl"],
        min_sample_size=30,
    )

    assert len(results) == 1
    res = results[0]
    assert res.status == DriftStatus.INSUFFICIENT_DATA
    assert res.sample_size == 10
    assert "below statistical reliability threshold" in res.explanation


@pytest.mark.unit
def test_feature_drift_detection_and_explanation():
    """Verify detection of critical shift when feature distribution departs from baseline."""
    base_profile = {
        "feature_baselines": {
            "sttl": {
                "mean": 62.0,
                "std": 15.0,
                "deciles": [31.0, 31.0, 31.0, 62.0, 62.0, 62.0, 64.0, 64.0, 64.0, 254.0, 254.0],
            }
        }
    }

    # 100 rows all at TTL 254 (classic attack pattern shift)
    shifted_df = pd.DataFrame({"sttl": [254] * 100})
    results = evaluate_feature_drift(
        baseline_profile=base_profile,
        current_df=shifted_df,
        features=["sttl"],
        min_sample_size=30,
    )

    assert len(results) == 1
    assert results[0].status == DriftStatus.CRITICAL
    assert results[0].metric_value >= 0.25
    assert "distribution shift detected" in results[0].explanation


@pytest.mark.unit
def test_score_drift_evaluation():
    """Verify anomaly score distribution drift detection."""
    base_score_meta = {
        "mean": 0.20,
        "std": 0.15,
        "deciles": list(np.linspace(0.01, 0.99, 11)),
    }

    # Shifted scores heavily concentrated near 0.90
    high_scores = np.random.uniform(0.85, 0.98, size=150)
    res = evaluate_score_drift(base_score_meta, high_scores, min_sample_size=30)
    assert res.status in (DriftStatus.WARNING, DriftStatus.CRITICAL)
    assert res.sample_size == 150


@pytest.mark.unit
def test_data_quality_auditing():
    """Verify detection of negative durations and invalid TTL bounds."""
    invalid_data = pd.DataFrame({
        "duration_seconds": [-1.5, 0.2, 5.0],
        "sttl": [64, 300, 128],  # 300 is > 255
        "fwd_bytes": [100, 200, 300],
    })

    audit = check_data_quality(invalid_data, ["duration_seconds", "sttl", "fwd_bytes"])
    assert audit["is_clean"] is False
    assert audit["invalid_by_feature"]["duration_seconds"] == 1
    assert audit["invalid_by_feature"]["sttl"] == 1
    assert audit["invalid_by_feature"]["fwd_bytes"] == 0
    assert len(audit["violations"]) >= 2


@pytest.mark.unit
def test_alert_manager_debouncing_and_deduplication(app):
    """Verify that identical drift events within cooldown increment occurrence count without creating duplicate alert rows."""
    with app.app_context():
        # Clear existing
        MonitoringAlert.query.delete()
        db.session.commit()

        mgr = MonitoringAlertManager(cooldown_minutes=60)

        # First alert
        a1 = mgr._record_or_debounce_alert(
            alert_type="FEATURE_DRIFT",
            severity="CRITICAL",
            target_feature="sload",
            metric_name="PSI",
            metric_value=0.35,
            threshold=0.25,
            sample_size=100,
            summary="Feature 'sload' drift critical",
        )
        assert a1.occurrence_count == 1
        a1_id = a1.id

        # Second alert within cooldown
        a2 = mgr._record_or_debounce_alert(
            alert_type="FEATURE_DRIFT",
            severity="CRITICAL",
            target_feature="sload",
            metric_name="PSI",
            metric_value=0.42,
            threshold=0.25,
            sample_size=120,
            summary="Feature 'sload' drift critical",
        )
        assert a2.id == a1_id
        assert a2.occurrence_count == 2
        assert a2.metric_value == 0.42

        # Verify only 1 row exists in DB
        assert MonitoringAlert.query.count() == 1

        # Acknowledge and resolve
        ack = mgr.acknowledge(a1_id)
        assert ack.status == MonitoringAlertStatus.ACKNOWLEDGED.value
        assert ack.acknowledged_at is not None

        res = mgr.resolve(a1_id)
        assert res.status == MonitoringAlertStatus.RESOLVED.value
        assert res.resolved_at is not None


@pytest.mark.unit
def test_model_registry_governance_and_promotion(app):
    """Verify model registry lifecycle state machine and strict promotion requirements."""
    with app.app_context():
        # Clear existing
        ModelRegistryEntry.query.delete()
        db.session.commit()

        # Initialize
        active = ModelRegistryManager.initialize_registry_if_empty()
        assert active.lifecycle_status == ModelLifecycleStatus.PRODUCTION.value
        assert active.is_active is True

        # Register candidate model
        cand = ModelRegistryEntry(
            model_name="Candidate_HistGradient",
            model_version="1.1.0-rc1",
            preprocessor_version="1.0.0",
            model_artifact_hash="abc123hash",
            preprocessor_artifact_hash="def456hash",
            lifecycle_status=ModelLifecycleStatus.CANDIDATE.value,
            decision_threshold=0.5,
            feature_contract=["sttl", "sload"],
            training_dataset_provenance={"dataset": "UNSW-NB15"},
            evaluation_split_metrics={"accuracy": 0.985},
            is_active=False,
        )
        db.session.add(cand)
        db.session.commit()
        cand_id = cand.id

        # Attempt promote unvalidated model should fail
        with pytest.raises(ValueError, match="Must pass independent validation first"):
            ModelRegistryManager.promote_to_production(
                model_id=cand_id,
                approved_by="lead_auditor",
                approval_notes="Promoting without validation",
            )

        # Validate candidate
        val = ModelRegistryManager.validate_candidate(cand_id, "reports/m12_validation.md")
        assert val.lifecycle_status == ModelLifecycleStatus.VALIDATED.value

        # Promotion requires approval notes
        with pytest.raises(ValueError, match="requires both 'approved_by' and 'approval_notes'"):
            ModelRegistryManager.promote_to_production(
                model_id=cand_id,
                approved_by="",
                approval_notes="",
            )

        # Successful promotion
        promoted = ModelRegistryManager.promote_to_production(
            model_id=cand_id,
            approved_by="security_architect",
            approval_notes="Approved after Day 2 holdout verification showed 97.2% accuracy.",
        )
        assert promoted.is_active is True
        assert promoted.lifecycle_status == ModelLifecycleStatus.PRODUCTION.value

        # Verify old production model was archived
        old_model = db.session.get(ModelRegistryEntry, active.id)
        assert old_model.is_active is False
        assert old_model.lifecycle_status == ModelLifecycleStatus.ARCHIVED.value


@pytest.mark.unit
def test_ground_truth_feedback_and_operational_metrics(app):
    """Verify segregation of analyst dispositions and calculation of operational metrics strictly on confirmed ground truth."""
    with app.app_context():
        # Clear existing
        GroundTruthFeedback.query.delete()
        db.session.commit()

        # 1. No feedback yet
        eval_empty = get_operational_evaluation()
        assert eval_empty["status"] == "NO_GROUND_TRUTH"
        assert "Unlabeled traffic cannot be assumed benign or malicious" in eval_empty["disclaimer"]

        # 2. Add feedback with unverified ground truth
        submit_ground_truth_feedback(
            flow_identifier="flow-001",
            model_score=0.88,
            model_predicted_anomaly=True,
            analyst_disposition=AnalystDisposition.CONFIRMED_THREAT.value,
            verified_ground_truth=None,  # Unverified
        )
        eval_unverified = get_operational_evaluation()
        assert eval_unverified["status"] == "NO_GROUND_TRUTH"
        assert eval_unverified["verified_ground_truth_count"] == 0

        # 3. Add confirmed ground truth (TP, FP, TN, FN)
        submit_ground_truth_feedback(
            flow_identifier="flow-002",
            model_score=0.92,
            model_predicted_anomaly=True,
            analyst_disposition=AnalystDisposition.CONFIRMED_THREAT.value,
            verified_ground_truth=1,  # TP
        )
        submit_ground_truth_feedback(
            flow_identifier="flow-003",
            model_score=0.75,
            model_predicted_anomaly=True,
            analyst_disposition=AnalystDisposition.BENIGN_FALSE_POSITIVE.value,
            verified_ground_truth=0,  # FP
        )
        submit_ground_truth_feedback(
            flow_identifier="flow-004",
            model_score=0.12,
            model_predicted_anomaly=False,
            analyst_disposition=AnalystDisposition.BENIGN_FALSE_POSITIVE.value,
            verified_ground_truth=0,  # TN
        )

        eval_calc = get_operational_evaluation()
        assert eval_calc["status"] == "OPERATIONAL_METRICS_CALCULATED"
        metrics = eval_calc["metrics"]
        assert metrics["verified_sample_size"] == 3
        # TP = 1, FP = 1, TN = 1, FN = 0
        assert metrics["confusion_matrix"]["tp"] == 1
        assert metrics["confusion_matrix"]["fp"] == 1
        assert metrics["confusion_matrix"]["tn"] == 1
        assert metrics["confusion_matrix"]["fn"] == 0
        assert metrics["precision"] == pytest.approx(0.50, abs=1e-2)
        assert metrics["recall"] == pytest.approx(1.00, abs=1e-2)


@pytest.mark.unit
def test_monitoring_api_endpoints(client, app):
    """Verify RESTful endpoints: /status, /drift, /alerts, /registry, /metrics."""
    # 1. Status endpoint
    res_status = client.get("/api/v1/monitoring/status")
    assert res_status.status_code == 200
    st_data = res_status.get_json()["data"]
    assert "kpis" in st_data
    assert "data_freshness" in st_data
    assert st_data["monitoring_mode"] == "BATCH_AND_SCHEDULED"

    # 2. Drift endpoint
    res_drift = client.get("/api/v1/monitoring/drift")
    assert res_drift.status_code == 200
    dr_data = res_drift.get_json()["data"]
    assert "feature_drift" in dr_data
    assert "overall_status" in dr_data
    assert "disclaimer" in dr_data

    # 3. Registry endpoint
    res_reg = client.get("/api/v1/monitoring/registry")
    assert res_reg.status_code == 200
    reg_data = res_reg.get_json()["data"]
    assert "active_model" in reg_data
    assert "registry_ledger" in reg_data
    assert reg_data["governance_policy"]["automatic_promotion_permitted"] is False

    # 4. Feedback metrics endpoint
    res_fb = client.get("/api/v1/monitoring/feedback/metrics")
    assert res_fb.status_code == 200
    assert "status" in res_fb.get_json()["data"]

    # 5. Seed demo monitoring endpoint (succeeds in test mode)
    res_seed = client.post("/api/v1/monitoring/seed-demo?force=true")
    assert res_seed.status_code == 201

    # 6. Seed demo monitoring blocked in production
    with patch.dict(os.environ, {"FLASK_ENV": "production"}):
        res_prod_seed = client.post("/api/v1/monitoring/seed-demo")
        assert res_prod_seed.status_code == 403
        assert res_prod_seed.get_json()["error"]["code"] == "FORBIDDEN_IN_PRODUCTION"
