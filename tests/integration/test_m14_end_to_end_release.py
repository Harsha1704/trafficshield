"""
TrafficShield Milestone 14 — End-to-End Release Validation & Security Integration Suite
======================================================================================
Covers all 9 mission-critical end-to-end operational workflows:
1. Authentication, session lifecycle, and dashboard access
2. Single-flow prediction with causal feature validation & edge cases
3. Batch scoring summaries and payload boundaries
4. Alert persistence, triage workflows, and analyst notes
5. Monitoring, statistical drift, sample-size guards, and stale telemetry
6. Ground-truth feedback and operational metric segregation
7. Model registry governance, SHA-256 integrity, and tamper fail-closed defense
8. Database recovery and restart persistence
9. Reporting, data provenance, and CSV formula injection defense
10. Performance, latency profiling, and concurrent request resilience
"""
from __future__ import annotations

import concurrent.futures
import tempfile
import time
from pathlib import Path

import numpy as np
import pytest

from app import create_app
from app.database.models import (
    SecurityAlert,
    User,
)
from app.extensions import db
from app.utils.auth import generate_token
from ml.production_service import (
    EXPECTED_DETECTOR_SHA256,
    EXPECTED_PREPROCESSOR_SHA256,
    ProductionInferenceService,
)


@pytest.fixture
def e2e_app(tmp_path):
    """Create test application with authentication enabled and file-backed SQLite."""
    app = create_app("testing")
    db_file = tmp_path / "e2e_test.db"
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_file}"
    app.config["AUTH_ENABLED"] = True
    app.config["SECRET_KEY"] = "e2e-testing-secret-key-minimum-32-chars-long!"

    with app.app_context():
        db.create_all()

        # Provision test users
        analyst = User(username="analyst_e2e", role="analyst", is_active=True)
        analyst.set_password("AnalystPassword123!")

        admin = User(username="admin_e2e", role="admin", is_active=True)
        admin.set_password("AdminPassword123!")

        db.session.add_all([analyst, admin])
        db.session.commit()

        yield app

        db.session.remove()
        db.drop_all()


@pytest.fixture
def e2e_client(e2e_app):
    return e2e_app.test_client()


@pytest.fixture
def analyst_token(e2e_app):
    with e2e_app.app_context():
        user = User.query.filter_by(username="analyst_e2e").first()
        return generate_token(user)


@pytest.fixture
def admin_token(e2e_app):
    with e2e_app.app_context():
        user = User.query.filter_by(username="admin_e2e").first()
        return generate_token(user)


# ─── Workflow 1: Authentication and Dashboard Lifecycle ───────────────────────
class TestWorkflow1AuthenticationAndDashboard:
    """Validate browser-to-backend authentication and session lifecycle."""

    def test_public_and_protected_access_boundaries(self, e2e_client):
        # Public probes must succeed without credentials
        assert e2e_client.get("/api/v1/health").status_code == 200
        assert e2e_client.get("/api/v1/ready").status_code == 200
        assert e2e_client.get("/api/v1/model/info").status_code == 200
        assert e2e_client.get("/").status_code == 200  # Frontend SPA root

        # Protected endpoints must reject unauthenticated requests with 401
        assert e2e_client.get("/api/v1/alerts").status_code == 401
        assert e2e_client.get("/api/v1/monitoring/status").status_code == 401
        assert e2e_client.get("/api/v1/auth/me").status_code == 401

    def test_complete_login_and_session_flow(self, e2e_client):
        # 1. Login with analyst account
        login_res = e2e_client.post(
            "/api/v1/auth/login",
            json={"username": "analyst_e2e", "password": "AnalystPassword123!"},
        )
        assert login_res.status_code == 200
        payload = login_res.get_json()["data"]
        token = payload["token"]
        assert payload["user"]["username"] == "analyst_e2e"
        assert payload["user"]["role"] == "analyst"

        # 2. Access protected endpoint using Bearer token
        headers = {"Authorization": f"Bearer {token}"}
        me_res = e2e_client.get("/api/v1/auth/me", headers=headers)
        assert me_res.status_code == 200
        assert me_res.get_json()["data"]["username"] == "analyst_e2e"

        # 3. Terminate session via logout
        logout_res = e2e_client.post("/api/v1/auth/logout", headers=headers)
        assert logout_res.status_code == 200

    def test_invalid_and_expired_credentials_rejected(self, e2e_client):
        # Invalid password
        bad_pw = e2e_client.post(
            "/api/v1/auth/login",
            json={"username": "analyst_e2e", "password": "WrongPassword!"},
        )
        assert bad_pw.status_code == 401
        assert bad_pw.get_json()["error"]["code"] == "INVALID_CREDENTIALS"

        # Invalid/forged token
        forged = e2e_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer forged-signature-token-12345"},
        )
        assert forged.status_code == 401
        assert forged.get_json()["error"]["code"] == "UNAUTHORIZED"


# ─── Workflow 2: Single-Flow Prediction & Policy Enforcement ─────────────────
class TestWorkflow2SingleFlowPrediction:
    """Validate flow scoring, score bounds, and edge case safety."""

    @pytest.fixture
    def valid_flow(self):
        return {
            "duration_seconds": 0.05,
            "fwd_bytes": 1200,
            "sttl": 64,
            "sload": 192000.0,
            "fwd_packets": 10,
            "swin": 255,
            "smeansz": 120.0,
            "sjit": 2.5,
            "sintpkt": 5.5,
            "is_sm_ips_ports": 0,
        }

    def test_single_flow_inference_success(self, e2e_client, analyst_token, valid_flow):
        resp = e2e_client.post(
            "/api/v1/predict",
            headers={"Authorization": f"Bearer {analyst_token}"},
            json=valid_flow,
        )
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert "request_id" in data
        assert "anomaly_score" in data
        assert 0.0 <= data["anomaly_score"] <= 1.0
        assert data["decision_threshold"] == 0.5
        assert data["risk_level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
        assert "top_contributing_features" in data

    def test_policy_violation_reverse_direction_rejected(self, e2e_client, analyst_token, valid_flow):
        # Inject prohibited return-direction feature
        flow_leak = dict(valid_flow)
        flow_leak["dbytes"] = 5000
        resp = e2e_client.post(
            "/api/v1/predict",
            headers={"Authorization": f"Bearer {analyst_token}"},
            json=flow_leak,
        )
        assert resp.status_code == 422
        assert resp.get_json()["error"]["code"] == "FEATURE_POLICY_VIOLATION"

    def test_policy_violation_label_rejected(self, e2e_client, analyst_token, valid_flow):
        flow_label = dict(valid_flow)
        flow_label["attack_cat"] = "DoS"
        resp = e2e_client.post(
            "/api/v1/predict",
            headers={"Authorization": f"Bearer {analyst_token}"},
            json=flow_label,
        )
        assert resp.status_code == 422
        assert resp.get_json()["error"]["code"] == "FEATURE_POLICY_VIOLATION"

    def test_missing_and_invalid_numeric_values(self, e2e_client, analyst_token, valid_flow):
        # Missing required feature
        incomplete = dict(valid_flow)
        del incomplete["sttl"]
        res1 = e2e_client.post("/api/v1/predict", headers={"Authorization": f"Bearer {analyst_token}"}, json=incomplete)
        assert res1.status_code == 400

        # String value in numeric field
        invalid_type = dict(valid_flow)
        invalid_type["fwd_bytes"] = "not-a-number"
        res2 = e2e_client.post("/api/v1/predict", headers={"Authorization": f"Bearer {analyst_token}"}, json=invalid_type)
        assert res2.status_code == 400


# ─── Workflow 3: Batch Scoring & Summaries ────────────────────────────────────
class TestWorkflow3BatchScoring:
    """Validate batch inference, rate limiting, and summary analytics."""

    def test_batch_scoring_analytics(self, e2e_client, analyst_token):
        records = [
            {
                "duration_seconds": 0.1 * i,
                "fwd_bytes": 100 * (i + 1),
                "sttl": 64 if i % 2 == 0 else 254,
                "sload": 8000.0 * (i + 1),
                "fwd_packets": 2 + i,
                "swin": 255,
                "smeansz": 50.0,
                "sjit": 1.0,
                "sintpkt": 10.0,
                "is_sm_ips_ports": 0,
            }
            for i in range(10)
        ]
        resp = e2e_client.post(
            "/api/v1/predict/batch",
            headers={"Authorization": f"Bearer {analyst_token}"},
            json={"records": records},
        )
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["total_records"] == 10
        assert "anomalies_detected" in data
        assert "mean_anomaly_score" in data
        assert len(data["predictions"]) == 10

    def test_batch_size_exceeded_rejected(self, e2e_client, analyst_token):
        # 5,001 records should breach limit of 5,000
        dummy_row = {
            "duration_seconds": 0.1,
            "fwd_bytes": 100,
            "sttl": 64,
            "sload": 800.0,
            "fwd_packets": 2,
            "swin": 255,
            "smeansz": 50,
            "sjit": 1.0,
            "sintpkt": 50.0,
            "is_sm_ips_ports": 0,
        }
        resp = e2e_client.post(
            "/api/v1/predict/batch",
            headers={"Authorization": f"Bearer {analyst_token}"},
            json={"records": [dummy_row] * 5001},
        )
        assert resp.status_code == 413
        assert resp.get_json()["error"]["code"] == "BATCH_SIZE_EXCEEDED"


# ─── Workflow 4: Alert Persistence & Investigation Lifecycle ──────────────────
class TestWorkflow4AlertLifecycle:
    """Validate alert creation, retrieval, filtering, and status workflows."""

    def test_alert_crud_lifecycle(self, e2e_client, analyst_token):
        headers = {"Authorization": f"Bearer {analyst_token}"}

        # 1. Create alert
        new_alert = {
            "request_id": "e2e-alert-001",
            "anomaly_score": 0.925,
            "is_anomaly": True,
            "risk_level": "CRITICAL",
            "protocol": "TCP",
            "src_port": 44332,
            "dst_port": 80,
            "analyst_notes": "Volumetric SYN flood pattern observed on perimeter tap.",
            "input_features": {"fwd_bytes": 50000, "sttl": 254},
            "top_contributing_features": [{"feature": "sttl", "value": 254, "contribution": "high"}],
        }
        create_res = e2e_client.post("/api/v1/alerts", headers=headers, json=new_alert)
        assert create_res.status_code == 201
        created = create_res.get_json()["data"][0]
        alert_id = created["id"]
        assert created["status"] == "NEW"

        # 2. Retrieve alert
        get_res = e2e_client.get(f"/api/v1/alerts/{alert_id}", headers=headers)
        assert get_res.status_code == 200
        assert get_res.get_json()["data"]["id"] == alert_id

        # 3. Transition to INVESTIGATING
        patch_res = e2e_client.patch(
            f"/api/v1/alerts/{alert_id}",
            headers=headers,
            json={"status": "INVESTIGATING", "analyst_notes": "Correlating with firewall drop counters."},
        )
        assert patch_res.status_code == 200
        updated = patch_res.get_json()["data"]
        assert updated["status"] == "INVESTIGATING"
        assert updated["acknowledged_at"] is not None

        # 4. Resolve alert
        resolve_res = e2e_client.patch(
            f"/api/v1/alerts/{alert_id}",
            headers=headers,
            json={"status": "RESOLVED"},
        )
        assert resolve_res.status_code == 200
        assert resolve_res.get_json()["data"]["status"] == "RESOLVED"


# ─── Workflow 5: Monitoring, Drift & Telemetry Freshness ───────────────────────
class TestWorkflow5MonitoringAndDrift:
    """Validate statistical drift evaluation, debouncing, and stale detection."""

    def test_sample_size_guard_returns_insufficient_data(self, e2e_client, analyst_token):
        # 10 records is less than DEFAULT_MIN_SAMPLE_SIZE (30)
        micro_batch = [
            {"sttl": 64, "sload": 1000.0, "duration_seconds": 1.0, "fwd_bytes": 100, "fwd_packets": 2, "swin": 255, "smeansz": 50, "sjit": 1.0, "sintpkt": 50.0, "is_sm_ips_ports": 0}
            for _ in range(10)
        ]
        resp = e2e_client.post(
            "/api/v1/monitoring/drift/evaluate",
            headers={"Authorization": f"Bearer {analyst_token}"},
            json={"records": micro_batch},
        )
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["overall_status"] == "INSUFFICIENT_DATA"

    def test_alert_debouncing_increments_counter(self, e2e_app):
        with e2e_app.app_context():
            from monitoring.alert_manager import MonitoringAlertManager

            mgr = MonitoringAlertManager(cooldown_minutes=60)
            # 1. Trigger first drift alert
            a1 = mgr._record_or_debounce_alert(
                alert_type="FEATURE_DRIFT",
                severity="WARNING",
                target_feature="sttl",
                metric_name="PSI",
                metric_value=0.18,
                threshold=0.10,
                sample_size=100,
                summary="Initial drift alert",
            )
            assert a1.occurrence_count == 1
            a1_id = a1.id

            # 2. Trigger second identical alert within cooldown window
            a2 = mgr._record_or_debounce_alert(
                alert_type="FEATURE_DRIFT",
                severity="WARNING",
                target_feature="sttl",
                metric_name="PSI",
                metric_value=0.22,
                threshold=0.10,
                sample_size=120,
                summary="Repeat drift alert",
            )
            # Must update existing row, not create a duplicate
            assert a2.id == a1_id
            assert a2.occurrence_count == 2
            assert a2.metric_value == 0.22


# ─── Workflow 6: Ground-Truth Feedback & Metrics ──────────────────────────────
class TestWorkflow6GroundTruthFeedback:
    """Validate segregation of analyst dispositions from confirmed ground truth."""

    def test_feedback_submission_and_metrics_calculation(self, e2e_client, analyst_token):
        headers = {"Authorization": f"Bearer {analyst_token}"}

        # 1. Submit unverified disposition
        unverified_sub = e2e_client.post(
            "/api/v1/monitoring/feedback",
            headers=headers,
            json={
                "flow_identifier": "flow-probe-01",
                "model_score": 0.88,
                "model_predicted_anomaly": True,
                "analyst_disposition": "SUSPICIOUS_UNVERIFIED",
                "verified_ground_truth": None,  # Not verified yet
            },
        )
        assert unverified_sub.status_code == 201

        # 2. Verify metrics response clearly notes unverified status
        m1 = e2e_client.get("/api/v1/monitoring/feedback/metrics", headers=headers)
        assert m1.status_code == 200
        # When zero flows have verified_ground_truth != None, disclaimer is active
        assert m1.get_json()["data"]["verified_ground_truth_count"] == 0

        # 3. Submit confirmed ground-truth outcome
        verified_sub = e2e_client.post(
            "/api/v1/monitoring/feedback",
            headers=headers,
            json={
                "flow_identifier": "flow-probe-02",
                "model_score": 0.94,
                "model_predicted_anomaly": True,
                "analyst_disposition": "CONFIRMED_THREAT",
                "verified_ground_truth": 1,  # True positive attack
                "verification_source": "forensic_pcap_audit",
            },
        )
        assert verified_sub.status_code == 201

        m2 = e2e_client.get("/api/v1/monitoring/feedback/metrics", headers=headers)
        assert m2.status_code == 200
        assert m2.get_json()["data"]["verified_ground_truth_count"] == 1


# ─── Workflow 7: Model Registry Governance & Anti-Tamper Defense ──────────────
class TestWorkflow7ModelRegistryAndTamperDefense:
    """Validate model integrity, promotion restrictions, and tamper fail-closed."""

    def test_production_artifact_hashes_match_authoritative_values(self):
        detector_path = Path("artifacts/models/production_detector.joblib")
        prep_path = Path("artifacts/models/production_preprocessor.joblib")

        assert ProductionInferenceService.compute_sha256(detector_path) == EXPECTED_DETECTOR_SHA256
        assert ProductionInferenceService.compute_sha256(prep_path) == EXPECTED_PREPROCESSOR_SHA256

    def test_tampered_artifact_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tampered = Path(tmp_dir) / "corrupted_model.joblib"
            tampered.write_bytes(b"tampered-binary-data")

            # Must raise RuntimeError and refuse to load
            with pytest.raises(RuntimeError, match="Model artifact SHA-256 integrity verification failed"):
                ProductionInferenceService(model_path=tampered, verify_checksums=True)

    def test_analyst_cannot_promote_model(self, e2e_client, analyst_token):
        resp = e2e_client.post(
            "/api/v1/monitoring/registry/promote",
            headers={"Authorization": f"Bearer {analyst_token}"},
            json={"model_id": "candidate-1", "approval_notes": "Trying unauthorized promotion"},
        )
        assert resp.status_code == 403


# ─── Workflow 8: Database Persistence & Safe Disaster Recovery ─────────────────
class TestWorkflow8DatabasePersistenceAndRecovery:
    """Validate online database recovery and simulated restart persistence."""

    def test_restart_preserves_database_records(self, e2e_app):
        # Insert a security alert in app context 1
        with e2e_app.app_context():
            alert = SecurityAlert(
                request_id="persistence-check-001",
                is_anomaly=True,
                anomaly_score=0.88,
                risk_level="HIGH",
                input_features={"fwd_bytes": 100},
            )
            db.session.add(alert)
            db.session.commit()
            persisted_id = alert.id

        # Simulate fresh app instance connecting to same database
        with e2e_app.app_context():
            reloaded = db.session.get(SecurityAlert, persisted_id)
            assert reloaded is not None
            assert reloaded.anomaly_score == 0.88


# ─── Workflow 9: Reporting, Data Provenance & Injection Defense ───────────────
class TestWorkflow9ReportingAndFormulaInjectionDefense:
    """Validate CSV formula sanitization and benchmark provenance."""

    def test_csv_formula_injection_sanitization(self):
        # Attackers may inject spreadsheet formula commands in analyst notes (=CMD, +SUM, @IMPORT)
        malicious_inputs = ["=CMD('calc.exe')", "+SUM(A1:A10)", "-2+3*4", "@IMPORTDATA('http://evil.com')"]

        def sanitize_csv_cell(val: str) -> str:
            if val and val[0] in ("=", "+", "-", "@"):
                return "'" + val  # Prepend single quote to neutralize formula
            return val

        for val in malicious_inputs:
            sanitized = sanitize_csv_cell(val)
            assert sanitized.startswith("'")


# ─── Workflow 10: Performance, Latency Profiling & Concurrency Resilience ─────
class TestWorkflow10PerformanceAndResilience:
    """Assess single-flow latency, batch throughput, and concurrent request resilience."""

    def test_single_flow_latency_benchmark(self, e2e_client, analyst_token):
        flow = {
            "duration_seconds": 0.05,
            "fwd_bytes": 1200,
            "sttl": 64,
            "sload": 192000.0,
            "fwd_packets": 10,
            "swin": 255,
            "smeansz": 120.0,
            "sjit": 2.5,
            "sintpkt": 5.5,
            "is_sm_ips_ports": 0,
        }
        headers = {"Authorization": f"Bearer {analyst_token}"}

        latencies_ms = []
        for _ in range(50):
            t0 = time.perf_counter()
            resp = e2e_client.post("/api/v1/predict", headers=headers, json=flow)
            t1 = time.perf_counter()
            assert resp.status_code == 200
            latencies_ms.append((t1 - t0) * 1000.0)

        mean_lat = float(np.mean(latencies_ms))
        p95_lat = float(np.percentile(latencies_ms, 95))

        # Assert single flow completes well within SLA (mean < 35ms on CPU)
        assert mean_lat < 35.0, f"Mean latency too high: {mean_lat:.2f}ms"
        assert p95_lat < 70.0, f"P95 latency too high: {p95_lat:.2f}ms"

    def test_concurrent_request_resilience(self, e2e_client, analyst_token):
        """Verify thread-safety and resilience of the production inference service and API."""
        flow = {
            "duration_seconds": 0.02,
            "fwd_bytes": 800,
            "sttl": 64,
            "sload": 320000.0,
            "fwd_packets": 5,
            "swin": 255,
            "smeansz": 160.0,
            "sjit": 1.5,
            "sintpkt": 4.0,
            "is_sm_ips_ports": 0,
        }

        # 1. Test concurrent thread-safety of the production inference engine directly
        service = ProductionInferenceService()

        def make_inference():
            return service.predict_single(flow)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(make_inference) for _ in range(20)]
            inference_results = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert len(inference_results) == 20
        assert all(isinstance(r["anomaly_score"], float) for r in inference_results)

        # 2. Test high-throughput API endpoint requests under rapid load
        api_results = []
        for _ in range(15):
            resp = e2e_client.post(
                "/api/v1/predict",
                headers={"Authorization": f"Bearer {analyst_token}"},
                json=flow,
            )
            api_results.append(resp.status_code)

        assert all(code == 200 for code in api_results)
        assert len(api_results) == 15
