"""
Unit tests for TrafficShield SOC Alerts Persistence and API endpoints.
"""
from __future__ import annotations

import pytest


@pytest.mark.unit
def test_alerts_crud_lifecycle(client):
    """Test full alert creation, retrieval, filtering, and status updates."""
    # 1. Create alert
    payload = {
        "request_id": "test-req-001",
        "anomaly_score": 0.895,
        "is_anomaly": True,
        "risk_level": "CRITICAL",
        "status": "NEW",
        "protocol": "TCP",
        "src_port": 50000,
        "dst_port": 80,
        "input_features": {
            "duration_seconds": 0.05,
            "fwd_bytes": 100000,
            "sttl": 254,
            "sload": 2000000.0,
            "fwd_packets": 150,
            "swin": 255,
            "smeansz": 666.6,
            "sjit": 10.0,
            "sintpkt": 0.33,
            "is_sm_ips_ports": 0,
        },
        "top_contributing_features": [
            {"feature": "sttl", "value": 254, "contribution": "high", "reason": "TTL spike"},
        ],
    }

    res = client.post("/api/v1/alerts", json=payload)
    assert res.status_code == 201
    created_data = res.get_json()["data"]
    assert len(created_data) == 1
    alert_id = created_data[0]["id"]
    assert created_data[0]["risk_level"] == "CRITICAL"
    assert created_data[0]["anomaly_score"] == 0.895

    # 2. Get single alert
    res_get = client.get(f"/api/v1/alerts/{alert_id}")
    assert res_get.status_code == 200
    alert_detail = res_get.get_json()["data"]
    assert alert_detail["id"] == alert_id
    assert alert_detail["status"] == "NEW"

    # 3. List alerts with filters
    res_list = client.get("/api/v1/alerts?risk_level=CRITICAL&status=NEW")
    assert res_list.status_code == 200
    list_data = res_list.get_json()
    assert list_data["meta"]["pagination"]["total"] >= 1
    assert any(a["id"] == alert_id for a in list_data["data"])

    # 4. Update status and notes
    res_patch = client.patch(
        f"/api/v1/alerts/{alert_id}",
        json={"status": "INVESTIGATING", "analyst_notes": "Triaging suspicious packet burst."},
    )
    assert res_patch.status_code == 200
    updated = res_patch.get_json()["data"]
    assert updated["status"] == "INVESTIGATING"
    assert updated["analyst_notes"] == "Triaging suspicious packet burst."
    assert updated["acknowledged_at"] is not None

    # 5. Invalid status rejection
    res_bad = client.patch(f"/api/v1/alerts/{alert_id}", json={"status": "INVALID_STATE"})
    assert res_bad.status_code == 400
    assert res_bad.get_json()["error"]["code"] == "INVALID_STATUS"

    # 6. Nonexistent alert returns 404
    res_404 = client.get("/api/v1/alerts/nonexistent-id-000")
    assert res_404.status_code == 404


@pytest.mark.unit
def test_alert_network_coordinates_serialization(client):
    """Test serialization of alerts with and without network coordinates."""
    # Alert with _network_coordinates
    payload_with_coords = {
        "request_id": "test-req-coords",
        "anomaly_score": 0.92,
        "is_anomaly": True,
        "risk_level": "CRITICAL",
        "status": "NEW",
        "protocol": "UDP",
        "src_port": 5353,
        "dst_port": 5353,
        "input_features": {
            "duration_seconds": 0.0001,
            "fwd_bytes": 140,
            "sttl": 255,
            "sload": 11200000.0,
            "fwd_packets": 1,
            "swin": 0,
            "smeansz": 140.0,
            "sjit": 0.0,
            "sintpkt": 0.0,
            "is_sm_ips_ports": 0,
            "packet_rate": 10000.0,
            "byte_rate": 1400000.0,
            "bytes_per_packet": 140.0,
            "_network_coordinates": {
                "src_ip": "192.168.1.105",
                "dst_ip": "224.0.0.251",
                "flow_id": "192.168.1.105:5353-224.0.0.251:5353-UDP",
            },
            "_hybrid_evidence": {
                "hybrid_classification": "SUPERVISED_ONLY_ALERT",
                "supervised": {"score": 0.92, "threshold": 0.5, "is_anomaly": True},
                "unsupervised": {"score": 0.61, "threshold": 0.7279, "is_anomaly": False},
            },
        },
    }
    res = client.post("/api/v1/alerts", json=payload_with_coords)
    assert res.status_code == 201
    created = res.get_json()["data"][0]
    alert_id = created["id"]
    assert created["src_ip"] == "192.168.1.105"
    assert created["dst_ip"] == "224.0.0.251"
    assert created["hybrid_classification"] == "SUPERVISED_ONLY_ALERT"

    # Fetch via GET
    res_get = client.get(f"/api/v1/alerts/{alert_id}")
    assert res_get.status_code == 200
    alert_data = res_get.get_json()["data"]
    assert alert_data["src_ip"] == "192.168.1.105"
    assert alert_data["dst_ip"] == "224.0.0.251"

    # Legacy alert without _network_coordinates
    payload_legacy = {
        "request_id": "test-req-legacy",
        "anomaly_score": 0.45,
        "is_anomaly": False,
        "risk_level": "LOW",
        "status": "NEW",
        "protocol": "TCP",
        "src_port": 12345,
        "dst_port": 443,
        "input_features": {
            "duration_seconds": 1.0,
            "fwd_bytes": 500,
            "sttl": 64,
            "sload": 4000.0,
            "fwd_packets": 5,
            "swin": 255,
            "smeansz": 100.0,
            "sjit": 1.0,
            "sintpkt": 0.2,
            "is_sm_ips_ports": 0,
        },
    }
    res_legacy = client.post("/api/v1/alerts", json=payload_legacy)
    assert res_legacy.status_code == 201
    legacy_created = res_legacy.get_json()["data"][0]
    assert legacy_created["src_ip"] is None
    assert legacy_created["dst_ip"] is None
    assert legacy_created["hybrid_classification"] is None


@pytest.mark.unit
def test_alerts_stats_endpoint(client):
    """Test retrieval of aggregate statistics for SOC overview."""
    # Seed sample alerts
    client.post("/api/v1/alerts/seed-demo?force=true")

    res = client.get("/api/v1/alerts/stats")
    assert res.status_code == 200
    stats = res.get_json()["data"]
    assert "total_records" in stats
    assert "total_anomalies" in stats
    assert "severity_distribution" in stats
    assert "status_distribution" in stats
    assert "CRITICAL" in stats["severity_distribution"]
    assert stats["total_records"] >= 5
