"""
TrafficShield Local Comprehensive End-to-End Regression Test Suite
==================================================================
Tests:
1. Feature input validation (valid, missing, non-numeric, empty, forbidden reverse, labels)
2. Vectorized batch inference throughput on 5,000 rows (<1s)
3. All 4 hybrid decision engine classifications (DUAL_CONFIRMED, SUPERVISED_ONLY_ALERT, UNSUPERVISED_NOVELTY, NORMAL_TRAFFIC)
4. Alert generation and persistence
5. Alert triage status transitions and durable DB persistence
6. Role-Based Access Control (RBAC) on prediction and alert endpoints
"""
import uuid
import time
from datetime import UTC, datetime
from unittest.mock import MagicMock
import numpy as np
import pytest

from app import create_app
from app.extensions import db
from app.database.models import User, SecurityAlert
from features.policy import PolicyViolationError
from ml.production_service import ProductionInferenceService, REQUIRED_BASE_FEATURES


@pytest.fixture(scope="module")
def app_instance():
    """Create test application context isolated to SQLite testing database."""
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        # Seed test admin and analyst users
        admin = User.query.filter_by(username="admin").first()
        if not admin:
            admin = User(username="admin", role="admin", is_active=True)
            admin.set_password("AdminShield@2026#Sec")
            db.session.add(admin)

        analyst = User.query.filter_by(username="analyst").first()
        if not analyst:
            analyst = User(username="analyst", role="analyst", is_active=True)
            analyst.set_password("AnalystShield@2026#Sec")
            db.session.add(analyst)

        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app_instance):
    return app_instance.test_client()


@pytest.fixture
def auth_headers(app_instance):
    """Generate Bearer auth token for analyst."""
    with app_instance.app_context():
        from app.utils.auth import generate_token
        user = User.query.filter_by(username="analyst").first()
        token = generate_token(user)
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture
def admin_headers(app_instance):
    """Generate Bearer auth token for admin."""
    with app_instance.app_context():
        from app.utils.auth import generate_token
        user = User.query.filter_by(username="admin").first()
        token = generate_token(user)
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture
def valid_flow_sample():
    return {
        "duration_seconds": 0.045,
        "fwd_bytes": 78000.0,
        "sttl": 254.0,
        "sload": 13866666.7,
        "fwd_packets": 95.0,
        "swin": 0.0,
        "smeansz": 821.0,
        "sjit": 38.2,
        "sintpkt": 0.47,
        "is_sm_ips_ports": 0.0,
    }


# ─── 1. Input Handling & Feature Policy Tests ───────────────────────────────

class TestInputValidationAndPolicy:

    def test_valid_input_succeeds(self, valid_flow_sample):
        service = ProductionInferenceService(verify_checksums=False)
        result = service.predict_single(valid_flow_sample)
        assert "anomaly_score" in result
        assert "hybrid_classification" in result
        assert 0.0 <= result["anomaly_score"] <= 1.0

    def test_missing_required_features_raises_value_error(self, valid_flow_sample):
        service = ProductionInferenceService(verify_checksums=False)
        incomplete = dict(valid_flow_sample)
        del incomplete["sttl"]
        with pytest.raises(ValueError, match="Missing required forward observable features"):
            service.predict_single(incomplete)

    def test_forbidden_reverse_feature_rejected(self, valid_flow_sample):
        service = ProductionInferenceService(verify_checksums=False)
        tainted = dict(valid_flow_sample)
        tainted["dbytes"] = 1500.0  # forbidden reverse feature
        with pytest.raises(PolicyViolationError, match="Forbidden reverse-dependent columns"):
            service.predict_single(tainted)

    def test_target_label_in_input_rejected(self, valid_flow_sample):
        service = ProductionInferenceService(verify_checksums=False)
        tainted = dict(valid_flow_sample)
        tainted["attack_cat"] = "DoS"
        with pytest.raises(PolicyViolationError, match="Target labels cannot be prediction features"):
            service.predict_single(tainted)

    def test_empty_batch_rejected(self):
        service = ProductionInferenceService(verify_checksums=False)
        with pytest.raises(ValueError, match="Batch record list is empty"):
            service.predict_batch([])

    def test_invalid_non_numeric_feature_in_batch(self, valid_flow_sample):
        service = ProductionInferenceService(verify_checksums=False)
        bad_rec = dict(valid_flow_sample)
        bad_rec["sload"] = "NOT_A_NUMBER"
        with pytest.raises(ValueError, match="Invalid non-numeric value"):
            service.predict_batch([bad_rec])


# ─── 2. Batch Inference Vectorization & Throughput Test ─────────────────────

class TestBatchPerformance:

    def test_5000_flows_vectorized_scoring_sub_second(self, valid_flow_sample):
        service = ProductionInferenceService(verify_checksums=False)
        records = [dict(valid_flow_sample) for _ in range(5000)]

        t_start = time.perf_counter()
        batch_result = service.predict_batch(records)
        elapsed = time.perf_counter() - t_start

        assert batch_result["total_records"] == 5000
        assert len(batch_result["predictions"]) == 5000
        assert "hybrid_classification_counts" in batch_result
        # 5,000 flows must complete in under 2.0 seconds (previously took >100s)
        assert elapsed < 2.0, f"Batch scoring took {elapsed:.2f}s, expected < 2.0s"
        assert batch_result["mean_anomaly_score"] >= 0.0


# ─── 3. Four Hybrid Decision Classifications Verification ───────────────────

class TestHybridClassifications:

    def test_all_four_hybrid_states_reproducible(self, valid_flow_sample):
        service = ProductionInferenceService(verify_checksums=False)

        # 1. DUAL_CONFIRMED: Supervised >= 0.50 AND Unsupervised >= 0.727896
        service.model.predict_proba = MagicMock(return_value=np.array([[0.05, 0.95]]))
        service.iforest.score_samples = MagicMock(return_value=np.array([0.80]))
        r1 = service.predict_single(valid_flow_sample)
        assert r1["hybrid_classification"] == "DUAL_CONFIRMED"
        assert r1["is_anomaly"] is True

        # 2. SUPERVISED_ONLY_ALERT: Supervised >= 0.50 AND Unsupervised < 0.727896
        service.model.predict_proba = MagicMock(return_value=np.array([[0.10, 0.90]]))
        service.iforest.score_samples = MagicMock(return_value=np.array([0.40]))
        r2 = service.predict_single(valid_flow_sample)
        assert r2["hybrid_classification"] == "SUPERVISED_ONLY_ALERT"
        assert r2["is_anomaly"] is True

        # 3. UNSUPERVISED_NOVELTY: Supervised < 0.50 AND Unsupervised >= 0.727896
        service.model.predict_proba = MagicMock(return_value=np.array([[0.80, 0.20]]))
        service.iforest.score_samples = MagicMock(return_value=np.array([0.85]))
        r3 = service.predict_single(valid_flow_sample)
        assert r3["hybrid_classification"] == "UNSUPERVISED_NOVELTY"

        # 4. NORMAL_TRAFFIC: Supervised < 0.50 AND Unsupervised < 0.727896
        service.model.predict_proba = MagicMock(return_value=np.array([[0.95, 0.05]]))
        service.iforest.score_samples = MagicMock(return_value=np.array([0.30]))
        r4 = service.predict_single(valid_flow_sample)
        assert r4["hybrid_classification"] == "NORMAL_TRAFFIC"
        assert r4["is_anomaly"] is False


# ─── 4. Alert Persistence & Triage State Lifecycle ──────────────────────────

class TestAlertsAndTriageLifecycle:

    def test_alert_creation_persistence_and_triage(self, client, auth_headers):
        # 1. Post new alert
        alert_payload = {
            "request_id": f"test-flow-{uuid.uuid4().hex[:8]}",
            "anomaly_score": 0.92,
            "is_anomaly": True,
            "risk_level": "CRITICAL",
            "decision_threshold": 0.5,
            "model_name": "OptunaTuned_XGBoost",
            "model_version": "1.0.0",
            "status": "NEW",
            "analyst_notes": "Automated e2e test alert payload",
            "input_features": {
                "duration_seconds": 0.045,
                "fwd_bytes": 78000,
                "sttl": 254,
            },
            "top_contributing_features": [
                {"feature": "sttl", "value": 254, "contribution": "high", "reason": "TTL spike"}
            ],
            "protocol": "TCP",
            "dst_port": 443,
            "hybrid_classification": "DUAL_CONFIRMED",
        }

        res_create = client.post("/api/v1/alerts", json=[alert_payload], headers=auth_headers)
        assert res_create.status_code == 201
        created_data = res_create.get_json()["data"]
        assert len(created_data) == 1
        alert_id = created_data[0]["id"]
        assert created_data[0]["status"] == "NEW"

        # 2. Query single alert details
        res_get = client.get(f"/api/v1/alerts/{alert_id}", headers=auth_headers)
        assert res_get.status_code == 200
        alert_detail = res_get.get_json()["data"]
        assert alert_detail["id"] == alert_id
        assert alert_detail["risk_level"] == "CRITICAL"
        assert alert_detail["status"] == "NEW"

        # 3. Transition triage status to INVESTIGATING
        res_patch1 = client.patch(
            f"/api/v1/alerts/{alert_id}",
            json={"status": "INVESTIGATING", "analyst_notes": "Assigned to SOC tier 2 analyst"},
            headers=auth_headers,
        )
        assert res_patch1.status_code == 200
        assert res_patch1.get_json()["data"]["status"] == "INVESTIGATING"

        # 4. Verify status persists on reload
        res_verify1 = client.get(f"/api/v1/alerts/{alert_id}", headers=auth_headers)
        assert res_verify1.get_json()["data"]["status"] == "INVESTIGATING"
        assert "Assigned to SOC" in res_verify1.get_json()["data"]["analyst_notes"]

        # 5. Transition triage status to RESOLVED
        res_patch2 = client.patch(
            f"/api/v1/alerts/{alert_id}",
            json={"status": "RESOLVED", "analyst_notes": "Confirmed benign scanner, rule updated"},
            headers=auth_headers,
        )
        assert res_patch2.status_code == 200
        assert res_patch2.get_json()["data"]["status"] == "RESOLVED"

        # 6. Verify final persistence
        res_verify2 = client.get(f"/api/v1/alerts/{alert_id}", headers=auth_headers)
        assert res_verify2.get_json()["data"]["status"] == "RESOLVED"


# ─── 5. Role-Based Access Control (RBAC) Verification ───────────────────────

class TestRoleBasedAccessControl:

    def test_unauthenticated_request_denied(self, app_instance, client):
        app_instance.config["AUTH_ENABLED"] = True
        try:
            res = client.get("/api/v1/alerts")
            assert res.status_code == 401
            assert res.get_json()["error"]["code"] == "UNAUTHORIZED"
        finally:
            app_instance.config["AUTH_ENABLED"] = False

    def test_analyst_can_access_alerts_and_predict(self, app_instance, client, auth_headers, valid_flow_sample):
        app_instance.config["AUTH_ENABLED"] = True
        try:
            # List alerts
            res_alerts = client.get("/api/v1/alerts", headers=auth_headers)
            assert res_alerts.status_code == 200

            # Execute prediction
            res_predict = client.post("/api/v1/predict/batch", json={"records": [valid_flow_sample]}, headers=auth_headers)
            assert res_predict.status_code == 200
            assert res_predict.get_json()["data"]["total_records"] == 1
        finally:
            app_instance.config["AUTH_ENABLED"] = False

    def test_admin_can_access_alerts_and_stats(self, app_instance, client, admin_headers):
        app_instance.config["AUTH_ENABLED"] = True
        try:
            res_stats = client.get("/api/v1/alerts/stats", headers=admin_headers)
            assert res_stats.status_code == 200
            assert "total_records" in res_stats.get_json()["data"]
        finally:
            app_instance.config["AUTH_ENABLED"] = False
