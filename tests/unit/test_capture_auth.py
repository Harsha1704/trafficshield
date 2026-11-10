"""
Unit tests for Milestone 3.2a — Capture Endpoint Protection and RBAC Scrutiny.
"""
from __future__ import annotations

import collections

import pytest

from app import create_app
from app.database.models import User
from app.extensions import db
from app.utils.auth import generate_token
from config.settings import TestingSettings as AppTestingSettings
from streaming.manager import RealTimeDetectionManager


@pytest.fixture
def auth_app(tmp_path):
    """Create test Flask app with active authentication enabled."""
    db_file = tmp_path / "auth_test.db"
    settings = AppTestingSettings(
        database_url=f"sqlite:///{db_file.resolve().as_posix()}",
        auth_enabled=True,
    )
    app = create_app(settings)

    with app.app_context():
        db.create_all()
        # Create analyst user
        analyst = User(username="sec_analyst", role="analyst", is_active=True)
        analyst.set_password("AnalystPass123!")
        db.session.add(analyst)

        # Create admin user
        admin = User(username="sec_admin", role="admin", is_active=True)
        admin.set_password("AdminPass123!")
        db.session.add(admin)

        # Create low-privilege auditor user
        auditor = User(username="sec_auditor", role="auditor", is_active=True)
        auditor.set_password("AuditorPass123!")
        db.session.add(auditor)

        db.session.commit()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def auth_client(auth_app):
    with auth_app.test_client() as client:
        yield client


@pytest.fixture
def analyst_token(auth_app):
    with auth_app.app_context():
        user = User.query.filter_by(username="sec_analyst").first()
        return generate_token(user)


@pytest.fixture
def admin_token(auth_app):
    with auth_app.app_context():
        user = User.query.filter_by(username="sec_admin").first()
        return generate_token(user)


@pytest.fixture
def auditor_token(auth_app):
    with auth_app.app_context():
        user = User.query.filter_by(username="sec_auditor").first()
        return generate_token(user)


@pytest.fixture(autouse=True)
def mock_recent_events():
    """Inject mock recent event with IP coordinates into RealTimeDetectionManager."""
    manager = RealTimeDetectionManager.get_instance()
    mock_events = collections.deque(
        [
            {
                "event_id": "test-ev-1",
                "flow_id": "10.0.0.5:12345->10.0.0.99:80/TCP",
                "src_ip": "10.0.0.5",
                "dst_ip": "10.0.0.99",
                "protocol": "TCP",
                "anomaly_score": 0.85,
            }
        ],
        maxlen=50,
    )
    if manager.inference_worker:
        original = manager.inference_worker.recent_events
        manager.inference_worker.recent_events = mock_events
        yield
        manager.inference_worker.recent_events = original
    else:
        # Create mock worker placeholder
        from unittest.mock import MagicMock
        worker = MagicMock()
        worker.recent_events = mock_events
        worker.get_metrics.return_value = {}
        manager.inference_worker = worker
        yield
        manager.inference_worker = None


class TestCaptureEndpointProtection:
    """Validate RBAC and data minimization on /capture routes."""

    def test_unauthenticated_status_redacts_recent_events_and_ips(self, auth_client):
        """Unauthenticated caller gets 200 OK for operational status, but recent_events is empty."""
        res = auth_client.get("/api/v1/capture/status")
        assert res.status_code == 200
        data = res.get_json()["data"]
        assert "worker_state" in data
        assert "driver_available" in data
        # Sensitive recent_events must be redacted to empty list
        assert data["recent_events"] == []

    def test_authenticated_analyst_receives_full_recent_events_with_ips(
        self, auth_client, analyst_token
    ):
        """Analyst token receives unredacted recent_events including flow IP coordinates."""
        headers = {"Authorization": f"Bearer {analyst_token}"}
        res = auth_client.get("/api/v1/capture/status", headers=headers)
        assert res.status_code == 200
        data = res.get_json()["data"]
        assert len(data["recent_events"]) == 1
        ev = data["recent_events"][0]
        assert ev["src_ip"] == "10.0.0.5"
        assert ev["dst_ip"] == "10.0.0.99"

    def test_authenticated_admin_receives_full_recent_events(
        self, auth_client, admin_token
    ):
        """Admin token receives unredacted status and recent events."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        res = auth_client.get("/api/v1/capture/status", headers=headers)
        assert res.status_code == 200
        data = res.get_json()["data"]
        assert len(data["recent_events"]) == 1
        assert data["recent_events"][0]["src_ip"] == "10.0.0.5"

    def test_unauthenticated_interfaces_redacts_ip_and_mac(self, auth_client):
        """Unauthenticated caller gets 200 with driver availability, but interface IPs/MACs are redacted."""
        res = auth_client.get("/api/v1/capture/interfaces")
        assert res.status_code == 200
        data = res.get_json()["data"]
        assert "driver_available" in data
        assert "interfaces" in data
        for iface in data["interfaces"]:
            assert iface["ipv4_addresses"] == ["[REDACTED]"]
            assert iface["mac_address"] == "[REDACTED]"

    def test_authenticated_analyst_receives_full_interfaces(
        self, auth_client, analyst_token
    ):
        """Analyst receives actual unredacted interface properties."""
        headers = {"Authorization": f"Bearer {analyst_token}"}
        res = auth_client.get("/api/v1/capture/interfaces", headers=headers)
        assert res.status_code == 200
        data = res.get_json()["data"]
        assert "interfaces" in data
        for iface in data["interfaces"]:
            # If interfaces exist on host, they should not be redacted
            if iface.get("ipv4_addresses"):
                assert iface["ipv4_addresses"] != ["[REDACTED]"]

    def test_sample_pcaps_requires_analyst_or_admin(
        self, auth_client, analyst_token, auditor_token
    ):
        """Sample PCAP enumeration strictly requires analyst or admin role."""
        # Unauthenticated -> 401
        res_unauth = auth_client.get("/api/v1/capture/sample-pcaps")
        assert res_unauth.status_code == 401

        # Auditor (insufficient role) -> 403
        headers_auditor = {"Authorization": f"Bearer {auditor_token}"}
        res_auditor = auth_client.get("/api/v1/capture/sample-pcaps", headers=headers_auditor)
        assert res_auditor.status_code == 403

        # Analyst -> 200
        headers_analyst = {"Authorization": f"Bearer {analyst_token}"}
        res_analyst = auth_client.get("/api/v1/capture/sample-pcaps", headers=headers_analyst)
        assert res_analyst.status_code == 200
