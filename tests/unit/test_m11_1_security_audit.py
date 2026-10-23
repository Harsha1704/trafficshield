"""
Unit tests for TrafficShield Milestone 11.1 Dashboard Evidence Integrity and Security Audit.

Verifies:
1. Reconciled M9 benchmark metrics served by the model intelligence API.
2. Production mode protection disabling demo alert seeding.
3. Provenance tracking (is_demo, source, data_mode, production_records, demo_records).
4. Strict input limits on alert creation and mutation (batch size, note length, score bounds).
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from app.database.models import SecurityAlert
from app.extensions import db


@pytest.mark.unit
def test_model_info_returns_authoritative_m9_benchmarks(client):
    """Verify GET /api/v1/model/info returns audited M9 benchmarks with both Day 1 and Day 2 splits."""
    res = client.get("/api/v1/model/info")
    assert res.status_code == 200
    data = res.get_json()["data"]

    assert "verified_benchmark" in data
    bench = data["verified_benchmark"]

    # Verify Day 1 Held-out Test
    test_split = bench["heldout_test"]
    assert test_split["flows"] == 19942
    assert test_split["accuracy"] == pytest.approx(0.981045, abs=1e-5)
    assert test_split["recall"] == pytest.approx(0.977808, abs=1e-5)
    assert test_split["precision"] == pytest.approx(0.958501, abs=1e-5)
    assert test_split["specificity"] == pytest.approx(0.982391, abs=1e-5)
    assert test_split["f1_score"] == pytest.approx(0.968058, abs=1e-5)
    assert test_split["roc_auc"] == pytest.approx(0.998711, abs=1e-5)
    assert test_split["confusion_matrix"] == [13836, 248, 130, 5728]

    # Verify Day 2 Temporal Holdout
    day2_split = bench["day2_temporal_holdout"]
    assert day2_split["flows"] == 20000
    assert day2_split["accuracy"] == pytest.approx(0.9697, abs=1e-4)
    assert day2_split["recall"] == pytest.approx(0.9837, abs=1e-4)
    assert day2_split["precision"] == pytest.approx(0.9057, abs=1e-4)
    assert day2_split["specificity"] == pytest.approx(0.9650, abs=1e-4)
    assert day2_split["f1_score"] == pytest.approx(0.9431, abs=1e-4)
    assert day2_split["confusion_matrix"] == [14384, 522, 83, 5011]

    # Verify Cross-dataset limits
    assert bench["cross_dataset_limits"]["cicids2017_status"] == "DIRECT_TRANSFER_UNSUPPORTED"
    assert "ABSENT_LOCALLY" in bench["cross_dataset_limits"]["cicids2017_local_raw_data"]


@pytest.mark.unit
def test_seed_demo_alerts_forbidden_in_production(client, app):
    """Verify demo seeding endpoint returns 403 Forbidden when running in production mode."""
    # Test via settings.is_production
    current_settings = app.config.get("TRAFFICSHIELD_SETTINGS")
    with patch.object(type(current_settings), "is_production", property(lambda self: True)):
        res = client.post("/api/v1/alerts/seed-demo")
        assert res.status_code == 403
        body = res.get_json()
        assert body["error"]["code"] == "FORBIDDEN_IN_PRODUCTION"

    # Test via FLASK_ENV environment variable
    with patch.dict(os.environ, {"FLASK_ENV": "production"}):
        res = client.post("/api/v1/alerts/seed-demo")
        assert res.status_code == 403
        body = res.get_json()
        assert body["error"]["code"] == "FORBIDDEN_IN_PRODUCTION"


@pytest.mark.unit
def test_alert_provenance_and_stats_data_mode(client, app):
    """Verify alerts distinguish demo fixtures from production telemetry and reflect accurate data_mode."""
    with app.app_context():
        # Clear existing alerts
        SecurityAlert.query.delete()
        db.session.commit()

    # 1. Stats on empty DB
    res_empty = client.get("/api/v1/alerts/stats")
    assert res_empty.status_code == 200
    data_empty = res_empty.get_json()["data"]
    assert data_empty["data_mode"] == "EMPTY"
    assert data_empty["total_records"] == 0

    # 2. Seed demo alerts
    res_seed = client.post("/api/v1/alerts/seed-demo?force=true")
    assert res_seed.status_code == 201

    res_stats_demo = client.get("/api/v1/alerts/stats")
    stats_demo = res_stats_demo.get_json()["data"]
    assert stats_demo["data_mode"] == "DEMO_FIXTURE"
    assert stats_demo["demo_records"] > 0
    assert stats_demo["production_records"] == 0

    # 3. Create a production alert
    prod_payload = {
        "request_id": "audit-prod-001",
        "anomaly_score": 0.92,
        "is_anomaly": True,
        "risk_level": "CRITICAL",
        "is_demo": False,
        "source": "api_ingestion",
        "input_features": {"sttl": 254},
    }
    res_prod = client.post("/api/v1/alerts", json=prod_payload)
    assert res_prod.status_code == 201

    # Now stats should be MIXED
    res_stats_mixed = client.get("/api/v1/alerts/stats")
    stats_mixed = res_stats_mixed.get_json()["data"]
    assert stats_mixed["data_mode"] == "MIXED"
    assert stats_mixed["production_records"] == 1
    assert stats_mixed["demo_records"] > 0

    # 4. List alerts with include_demo=false
    res_list_prod = client.get("/api/v1/alerts?include_demo=false")
    assert res_list_prod.status_code == 200
    items = res_list_prod.get_json()["data"]
    assert len(items) == 1
    assert items[0]["is_demo"] is False


@pytest.mark.unit
def test_alert_validation_boundaries(client):
    """Verify input validation limits: batch size, score range, note length."""
    # 1. Payload batch size > 1000
    oversized = [{"anomaly_score": 0.5, "input_features": {}} for _ in range(1001)]
    res_large = client.post("/api/v1/alerts", json=oversized)
    assert res_large.status_code == 413
    assert res_large.get_json()["error"]["code"] == "PAYLOAD_TOO_LARGE"

    # 2. Score out of [0.0, 1.0]
    res_neg = client.post("/api/v1/alerts", json={"anomaly_score": -0.1, "input_features": {}})
    assert res_neg.status_code == 400
    assert res_neg.get_json()["error"]["code"] == "SCORE_OUT_OF_RANGE"

    res_huge = client.post("/api/v1/alerts", json={"anomaly_score": 1.5, "input_features": {}})
    assert res_huge.status_code == 400
    assert res_huge.get_json()["error"]["code"] == "SCORE_OUT_OF_RANGE"

    # 3. Note length > 2000 on create
    long_note = "A" * 2001
    res_long_create = client.post("/api/v1/alerts", json={"anomaly_score": 0.5, "analyst_notes": long_note, "input_features": {}})
    assert res_long_create.status_code == 400
    assert res_long_create.get_json()["error"]["code"] == "NOTES_TOO_LONG"

    # 4. Note length > 2000 on patch
    res_ok = client.post("/api/v1/alerts", json={"anomaly_score": 0.5, "input_features": {}})
    alert_id = res_ok.get_json()["data"][0]["id"]

    res_long_patch = client.patch(f"/api/v1/alerts/{alert_id}", json={"analyst_notes": long_note})
    assert res_long_patch.status_code == 400
    assert res_long_patch.get_json()["error"]["code"] == "NOTES_TOO_LONG"
