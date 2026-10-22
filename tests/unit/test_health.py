"""
Unit tests for health and readiness endpoints.

Tests verify:
- Correct HTTP status codes
- Response envelope structure
- Required fields in response body
- Readiness check includes DB status
"""
from __future__ import annotations

import pytest


@pytest.mark.unit
class TestHealthEndpoint:
    """Tests for GET /api/v1/health (liveness probe)."""

    def test_health_returns_200(self, client):
        response = client.get("/api/v1/health")
        assert response.status_code == 200

    def test_health_returns_json(self, client):
        response = client.get("/api/v1/health")
        assert response.content_type == "application/json"

    def test_health_success_envelope(self, client):
        data = client.get("/api/v1/health").get_json()
        assert data["success"] is True
        assert "data" in data

    def test_health_data_fields(self, client):
        data = client.get("/api/v1/health").get_json()
        payload = data["data"]
        assert payload["status"] == "ok"
        assert payload["service"] == "TrafficShield"
        assert "version" in payload
        assert "timestamp" in payload
        assert "uptime_seconds" in payload

    def test_health_uptime_is_non_negative(self, client):
        data = client.get("/api/v1/health").get_json()
        assert data["data"]["uptime_seconds"] >= 0

    def test_health_version_is_string(self, client):
        data = client.get("/api/v1/health").get_json()
        assert isinstance(data["data"]["version"], str)

    def test_health_timestamp_is_iso8601(self, client):
        from datetime import datetime
        data = client.get("/api/v1/health").get_json()
        ts = data["data"]["timestamp"]
        # Should parse without error
        datetime.fromisoformat(ts.replace("Z", "+00:00"))

    def test_health_method_not_allowed_post(self, client):
        """POST to health endpoint should return 405."""
        response = client.post("/api/v1/health")
        assert response.status_code == 405

    def test_health_method_not_allowed_delete(self, client):
        response = client.delete("/api/v1/health")
        assert response.status_code == 405


@pytest.mark.unit
class TestReadyEndpoint:
    """Tests for GET /api/v1/ready (readiness probe)."""

    def test_ready_returns_2xx_or_503(self, client):
        """Ready endpoint returns 200 or 503 — never 4xx."""
        response = client.get("/api/v1/ready")
        assert response.status_code in (200, 503)

    def test_ready_returns_json(self, client):
        response = client.get("/api/v1/ready")
        assert response.content_type == "application/json"

    def test_ready_contains_checks(self, client):
        """Response must include a 'checks' dict."""
        response = client.get("/api/v1/ready")
        data = response.get_json()
        # On success, payload is in data.data; on error, in error.details
        if data.get("success"):
            payload = data["data"]
        else:
            payload = data["error"]["details"]
        assert "checks" in payload
        assert "database" in payload["checks"]

    def test_ready_database_check_structure(self, client):
        response = client.get("/api/v1/ready")
        data = response.get_json()
        if data.get("success"):
            checks = data["data"]["checks"]
        else:
            checks = data["error"]["details"]["checks"]
        db_check = checks["database"]
        assert "status" in db_check
        assert db_check["status"] in ("ok", "error")

    def test_ready_with_in_memory_sqlite_is_ok(self, client):
        """In-memory SQLite used in tests should always be reachable."""
        response = client.get("/api/v1/ready")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["data"]["checks"]["database"]["status"] == "ok"


@pytest.mark.unit
class TestErrorHandlers:
    """Tests for global JSON error handlers."""

    def test_404_returns_json(self, client):
        response = client.get("/api/v1/this-route-does-not-exist")
        assert response.status_code == 404
        data = response.get_json()
        assert data["success"] is False
        assert "error" in data

    def test_404_error_code(self, client):
        response = client.get("/nonexistent")
        assert response.status_code == 404
        data = response.get_json()
        assert data["error"]["code"] == "NOT_FOUND"

    def test_405_returns_json(self, client):
        response = client.post("/api/v1/health")
        assert response.status_code == 405
        data = response.get_json()
        assert data["success"] is False
