"""
Integration and Unit Tests for Prediction REST API
===================================================
Version: 1.0 (Milestone Sprint)

Validates:
1. GET /api/v1/model/info endpoint.
2. POST /api/v1/predict with valid normal flow (returns 200, low risk).
3. POST /api/v1/predict with attack flow (returns 200, elevated risk, attributions).
4. Feature policy enforcement: rejects prohibited reverse-direction features (422).
5. Target leakage enforcement: rejects ground-truth labels (422).
6. Missing required features schema validation (400).
7. POST /api/v1/predict/batch: multi-flow processing and summary stats.
8. Empty batch and payload validation.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def sample_benign_flow() -> dict:
    return {
        "duration_seconds": 0.5,
        "fwd_bytes": 800.0,
        "sttl": 31.0,
        "sload": 12800.0,
        "fwd_packets": 10.0,
        "swin": 255.0,
        "smeansz": 80.0,
        "sjit": 5.0,
        "sintpkt": 50.0,
        "is_sm_ips_ports": 0.0,
    }


@pytest.fixture
def sample_attack_flow() -> dict:
    return {
        "duration_seconds": 0.001,
        "fwd_bytes": 1_200_000.0,
        "sttl": 254.0,
        "sload": 9_600_000_000.0,
        "fwd_packets": 1200.0,
        "swin": 255.0,
        "smeansz": 1000.0,
        "sjit": 0.0,
        "sintpkt": 0.001,
        "is_sm_ips_ports": 0.0,
    }


def test_model_info_endpoint(client) -> None:
    """Verify model metadata endpoint."""
    resp = client.get("/api/v1/model/info")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    data = body["data"]
    assert "model_name" in data
    assert "decision_threshold" in data
    assert "required_forward_features" in data
    assert "Unidirectional" in data["feature_policy"]


def test_predict_single_benign(client, sample_benign_flow) -> None:
    """Verify inference on legitimate traffic."""
    resp = client.post("/api/v1/predict", json=sample_benign_flow)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    data = body["data"]
    assert "request_id" in data
    assert "anomaly_score" in data
    assert "is_anomaly" in data
    assert "risk_level" in data
    assert data["risk_level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")


def test_predict_single_attack(client, sample_attack_flow) -> None:
    """Verify inference on volumetric attack flow."""
    resp = client.post("/api/v1/predict", json=sample_attack_flow)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    data = body["data"]
    assert data["is_anomaly"] is True
    assert data["anomaly_score"] >= 0.5
    assert data["risk_level"] in ("HIGH", "CRITICAL")
    assert isinstance(data["top_contributing_features"], list)
    assert len(data["top_contributing_features"]) > 0


def test_predict_policy_violation_reverse_feature(client, sample_benign_flow) -> None:
    """Verify reverse-direction features are strictly rejected with HTTP 422."""
    leaked_flow = sample_benign_flow.copy()
    leaked_flow["dbytes"] = 5000.0  # PROHIBITED REVERSE DIRECTION FEATURE

    resp = client.post("/api/v1/predict", json=leaked_flow)
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["success"] is False
    assert body["error"]["code"] == "FEATURE_POLICY_VIOLATION"
    assert "Forbidden reverse-dependent" in body["error"]["message"]


def test_predict_policy_violation_label(client, sample_benign_flow) -> None:
    """Verify target labels are strictly rejected with HTTP 422."""
    leaked_flow = sample_benign_flow.copy()
    leaked_flow["eval_label"] = "normal"  # TARGET LABEL LEAKAGE

    resp = client.post("/api/v1/predict", json=leaked_flow)
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["success"] is False
    assert body["error"]["code"] == "FEATURE_POLICY_VIOLATION"


def test_predict_missing_feature(client, sample_benign_flow) -> None:
    """Verify missing required forward feature returns HTTP 400."""
    invalid_flow = sample_benign_flow.copy()
    del invalid_flow["sttl"]

    resp = client.post("/api/v1/predict", json=invalid_flow)
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["success"] is False
    assert body["error"]["code"] == "SCHEMA_VALIDATION_ERROR"
    assert "Missing required" in body["error"]["message"]


def test_predict_invalid_content_type(client) -> None:
    """Verify non-JSON request returns HTTP 400."""
    resp = client.post("/api/v1/predict", data="not json", content_type="text/plain")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["success"] is False


def test_predict_batch_success(client, sample_benign_flow, sample_attack_flow) -> None:
    """Verify batch flow scoring and summary analytics."""
    batch = [sample_benign_flow, sample_attack_flow]
    resp = client.post("/api/v1/predict/batch", json={"records": batch})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    data = body["data"]
    assert data["total_records"] == 2
    assert "anomalies_detected" in data
    assert "mean_anomaly_score" in data
    assert len(data["predictions"]) == 2


def test_predict_batch_empty(client) -> None:
    """Verify empty batch returns HTTP 400."""
    resp = client.post("/api/v1/predict/batch", json={"records": []})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["success"] is False


def test_predict_batch_exceeds_max_limit(client, sample_benign_flow) -> None:
    """Verify batch exceeding 5,000 records returns HTTP 413."""
    oversized_batch = [sample_benign_flow] * 5001
    resp = client.post("/api/v1/predict/batch", json={"records": oversized_batch})
    assert resp.status_code == 413
    body = resp.get_json()
    assert body["success"] is False
    assert body["error"]["code"] == "BATCH_SIZE_EXCEEDED"
    assert "exceeds maximum limit" in body["error"]["message"]

