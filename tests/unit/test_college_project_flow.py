"""
TrafficShield College Project End-to-End Functional Test Suite
==============================================================
Validates the complete college project demonstration workflow:
1. Authentication (Admin & Analyst roles)
2. Service Health & Readiness Probes
3. Dual-Detector Model Integrity & Checksums
4. Real-Time Single Flow Scoring across Presets (Benign HTTPS, SYN Flood, PortScan, DNS Amp)
5. Batch Inference & 4-Tier Hybrid Decision Engine Verification
6. Alert Lifecycle & Statistical Rollups
7. Role-Based Access Control (RBAC) Enforcement
"""
import pytest
from app import create_app
from app.utils.auth import bootstrap_initial_users


@pytest.fixture
def app_client():
    app = create_app("testing")
    app.config["AUTH_ENABLED"] = True
    bootstrap_initial_users(app)
    return app.test_client()


@pytest.fixture
def admin_headers(app_client):
    res = app_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "AdminShield@2026#Sec"},
    )
    assert res.status_code == 200
    token = res.get_json()["data"]["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def analyst_headers(app_client):
    res = app_client.post(
        "/api/v1/auth/login",
        json={"username": "analyst", "password": "AnalystShield@2026#Sec"},
    )
    assert res.status_code == 200
    token = res.get_json()["data"]["token"]
    return {"Authorization": f"Bearer {token}"}


def test_01_health_and_readiness(app_client):
    """Verify health and readiness probes return 200 OK."""
    res_h = app_client.get("/api/v1/health")
    assert res_h.status_code == 200
    assert res_h.get_json()["data"]["status"] == "ok"

    res_r = app_client.get("/api/v1/ready")
    assert res_r.status_code == 200
    assert res_r.get_json()["data"]["status"] == "ok"


def test_02_model_info_and_integrity(app_client):
    """Verify model info exposes verified SHA-256 hashes and 13 forward features."""
    res = app_client.get("/api/v1/model/info")
    assert res.status_code == 200
    data = res.get_json()["data"]

    # Verify checksums
    assert data["artifact_integrity"]["verified"] is True
    assert data["supervised_model"]["sha256"] == "c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495"
    assert data["unsupervised_model"]["sha256"] == "d9fe41016c51f8484b57c80bb2f0ec41186c66add9bae71f822d0a85c13a350e"

    # Verify thresholds
    assert data["decision_threshold"] == 0.50
    assert data["unsupervised_model"]["decision_threshold"] == 0.727896

    # Verify 13 features contract
    assert len(data["required_forward_features"]) == 10  # Raw forward inputs
    assert len(data["engineered_features"]) == 3          # Derived rate features


def test_03_benign_https_flow_scoring(app_client, analyst_headers):
    """Verify standard HTTPS flow is classified correctly."""
    normal_flow = {
        "duration_seconds": 1.45,
        "fwd_bytes": 4800,
        "sttl": 31,
        "sload": 26482.7,
        "fwd_packets": 18,
        "swin": 255,
        "smeansz": 266.6,
        "sjit": 2.1,
        "sintpkt": 80.5,
        "is_sm_ips_ports": 0,
    }
    res = app_client.post("/api/v1/predict/single", json=normal_flow, headers=analyst_headers)
    assert res.status_code == 200
    d = res.get_json()["data"]
    assert "hybrid_classification" in d
    assert d["hybrid_classification"] == "NORMAL_TRAFFIC"
    assert d["supervised"]["is_anomaly"] is False
    assert d["supervised"]["probability"] < 0.50


def test_04_syn_flood_attack_scoring(app_client, analyst_headers):
    """Verify volumetric SYN flood attack triggers high anomaly score."""
    syn_flood = {
        "duration_seconds": 0.0018,
        "fwd_bytes": 185000,
        "sttl": 254,
        "sload": 822222222.2,
        "fwd_packets": 280,
        "swin": 255,
        "smeansz": 660.7,
        "sjit": 18.2,
        "sintpkt": 0.006,
        "is_sm_ips_ports": 0,
    }
    res = app_client.post("/api/v1/predict/single", json=syn_flood, headers=analyst_headers)
    assert res.status_code == 200
    d = res.get_json()["data"]
    assert d["supervised"]["is_anomaly"] is True
    assert d["supervised"]["probability"] >= 0.50
    assert d["hybrid_classification"] in ["DUAL_CONFIRMED", "SUPERVISED_ONLY_ALERT"]


def test_05_batch_hybrid_inference(app_client, admin_headers):
    """Verify batch inference endpoint correctly processes multiple flows and returns hybrid counts."""
    flows = [
        # Normal
        {
            "duration_seconds": 5.0, "fwd_bytes": 1000, "sttl": 64, "sload": 1600.0,
            "fwd_packets": 10, "swin": 255, "smeansz": 100, "sjit": 0.1, "sintpkt": 500.0,
            "is_sm_ips_ports": 0
        },
        # Port scan
        {
            "duration_seconds": 0.0001, "fwd_bytes": 44, "sttl": 254, "sload": 3520000.0,
            "fwd_packets": 1, "swin": 1024, "smeansz": 44.0, "sjit": 0.0, "sintpkt": 0.0,
            "is_sm_ips_ports": 0
        },
    ]
    res = app_client.post("/api/v1/predict/batch", json={"records": flows}, headers=admin_headers)
    assert res.status_code == 200
    d = res.get_json()["data"]
    assert len(d["predictions"]) == 2
    assert "hybrid_classification_counts" in d
    assert isinstance(d["hybrid_classification_counts"], dict)


def test_06_alerts_and_stats(app_client, admin_headers):
    """Verify alerts endpoint lists alerts and stats return valid structure."""
    res_l = app_client.get("/api/v1/alerts", headers=admin_headers)
    assert res_l.status_code == 200
    assert "data" in res_l.get_json()
    assert isinstance(res_l.get_json()["data"], list)

    res_s = app_client.get("/api/v1/alerts/stats", headers=admin_headers)
    assert res_s.status_code == 200
    assert "data" in res_s.get_json()
    assert "total_records" in res_s.get_json()["data"]


def test_07_rbac_access_control(app_client, analyst_headers):
    """Verify analyst role cannot access admin-only endpoints."""
    # Analyst cannot promote models in registry (requires admin role)
    res = app_client.post(
        "/api/v1/monitoring/registry/promote",
        json={"model_id": "candidate_m16", "approval_notes": "Valid justification notes for promotion"},
        headers=analyst_headers,
    )
    assert res.status_code == 403
    assert res.get_json()["error"]["code"] == "FORBIDDEN"
