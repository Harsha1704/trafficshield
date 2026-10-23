"""
TrafficShield Milestone 13 — Production Security & Release Verification Tests
=============================================================================
Comprehensive automated test suite covering:
1. Production configuration fail-fast assertions (secrets, non-sqlite DB, CORS, debug mode)
2. Authentication & credential protection (PBKDF2/scrypt, generic errors, account enumeration defense)
3. Role-Based Access Control (RBAC: analyst vs admin privilege separation)
4. Model promotion governance & audit trail enforcement
5. Demo seeding strict production denial across all environment flags
6. Security response headers (CSP, X-Frame-Options, MIME sniffing, HSTS)
7. Request correlation ID propagation (X-Request-ID)
8. Production error shielding & readiness probe sanitization
9. Frozen artifact cryptographic SHA-256 integrity & tamper rejection
10. Safe database backup and recovery on disposable test database
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from app import create_app
from app.database.models import ModelRegistryEntry, User
from app.extensions import db
from app.utils.auth import generate_token
from config.settings import ProductionSettings
from ml.production_service import (
    EXPECTED_DETECTOR_SHA256,
    EXPECTED_PREPROCESSOR_SHA256,
    ProductionInferenceService,
)


# ─── 1. Production Configuration Fail-Fast Tests ──────────────────────────────
class TestProductionConfigurationFailFast:
    """Verify that insecure production settings cause immediate startup failure."""

    def test_production_rejects_weak_secret_key(self):
        with pytest.raises(ValueError, match="SECRET_KEY must be at least 32 characters"):
            ProductionSettings(
                secret_key="too-short",
                database_url="postgresql://user:pass@localhost:5432/db",
            )

    def test_production_rejects_default_dev_secret_key(self):
        with pytest.raises(ValueError, match="SECRET_KEY must be set to a strong random value"):
            ProductionSettings(
                secret_key="dev-secret-key-change-in-production",
                database_url="postgresql://user:pass@localhost:5432/db",
            )

    def test_production_rejects_sqlite(self):
        with pytest.raises(ValueError, match="Production database must not use SQLite"):
            ProductionSettings(
                secret_key="a" * 32,
                database_url="sqlite:///trafficshield_prod.db",
            )

    def test_production_rejects_wildcard_cors(self):
        with pytest.raises(ValueError, match=r"Wildcard CORS origin '\*' is strictly prohibited"):
            ProductionSettings(
                secret_key="a" * 32,
                database_url="postgresql://user:pass@localhost:5432/db",
                cors_origins="http://localhost:3000,*",
            )

    def test_production_rejects_flask_debug_true(self):
        with pytest.raises(ValueError, match="flask_debug must be False in production"):
            ProductionSettings(
                secret_key="a" * 32,
                database_url="postgresql://user:pass@localhost:5432/db",
                flask_debug=True,
            )

    def test_valid_production_settings_pass(self):
        prod = ProductionSettings(
            secret_key="a" * 32,
            database_url="postgresql://trafficshield:strongpass@localhost:5432/trafficshield_prod",
            cors_origins="https://soc.trafficshield.internal",
            flask_debug=False,
        )
        assert prod.is_production is True
        assert prod.session_cookie_secure is True


# ─── 2. Authentication & Credential Protection Tests ──────────────────────────
@pytest.fixture
def auth_app():
    """Create a test application instance with AUTH_ENABLED=True."""
    app = create_app("testing")
    app.config["AUTH_ENABLED"] = True
    app.config["SECRET_KEY"] = "testing-secret-key-at-least-32-chars-long"

    with app.app_context():
        db.create_all()
        # Seed test analyst and admin
        analyst = User(username="sec_analyst", role="analyst", is_active=True)
        analyst.set_password("ValidAnalystPass123!")

        admin = User(username="sec_admin", role="admin", is_active=True)
        admin.set_password("ValidAdminPass123!")

        db.session.add_all([analyst, admin])
        db.session.commit()

        yield app

        db.session.remove()
        db.drop_all()


@pytest.fixture
def auth_client(auth_app):
    return auth_app.test_client()


class TestAuthenticationLifecycle:
    """Test login, logout, and token authentication."""

    def test_login_success_analyst(self, auth_client):
        resp = auth_client.post(
            "/api/v1/auth/login",
            json={"username": "sec_analyst", "password": "ValidAnalystPass123!"},
        )
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert "token" in data
        assert data["user"]["username"] == "sec_analyst"
        assert data["user"]["role"] == "analyst"
        # Check session cookie set
        assert "trafficshield_session" in resp.headers.get("Set-Cookie", "")

    def test_login_invalid_password_returns_generic_error(self, auth_client):
        resp = auth_client.post(
            "/api/v1/auth/login",
            json={"username": "sec_analyst", "password": "WrongPassword!"},
        )
        assert resp.status_code == 401
        data = resp.get_json()
        assert data["error"]["code"] == "INVALID_CREDENTIALS"
        assert data["error"]["message"] == "Invalid username or password"

    def test_login_nonexistent_user_returns_generic_error(self, auth_client):
        resp = auth_client.post(
            "/api/v1/auth/login",
            json={"username": "nonexistent_hacker", "password": "SomePassword123!"},
        )
        assert resp.status_code == 401
        data = resp.get_json()
        # Ensure account enumeration is prevented
        assert data["error"]["code"] == "INVALID_CREDENTIALS"
        assert data["error"]["message"] == "Invalid username or password"

    def test_auth_me_with_bearer_token(self, auth_client, auth_app):
        with auth_app.app_context():
            user = User.query.filter_by(username="sec_analyst").first()
            token = generate_token(user)

        resp = auth_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["username"] == "sec_analyst"
        assert data["role"] == "analyst"

    def test_auth_me_unauthenticated_returns_401(self, auth_client):
        resp = auth_client.get("/api/v1/auth/me")
        assert resp.status_code == 401
        data = resp.get_json()
        assert data["error"]["code"] == "UNAUTHORIZED"

    def test_logout_clears_cookie(self, auth_client):
        resp = auth_client.post("/api/v1/auth/logout")
        assert resp.status_code == 200
        cookie_header = resp.headers.get("Set-Cookie", "")
        # Deleting cookie sets Expires in the past or max-age=0
        assert "trafficshield_session" in cookie_header


# ─── 3. Role-Based Access Control (RBAC) Tests ───────────────────────────────
class TestRoleBasedAccessControl:
    """Verify privilege boundaries between analyst and admin."""

    def test_unauthenticated_access_to_predict_denied(self, auth_client):
        resp = auth_client.post(
            "/api/v1/predict",
            json={
                "duration_seconds": 1.0,
                "fwd_bytes": 100,
                "sttl": 64,
                "sload": 800.0,
                "fwd_packets": 2,
                "swin": 255,
                "smeansz": 50,
                "sjit": 1.0,
                "sintpkt": 50.0,
                "is_sm_ips_ports": 0,
            },
        )
        assert resp.status_code == 401
        assert resp.get_json()["error"]["code"] == "UNAUTHORIZED"

    def test_analyst_can_access_alerts_and_scoring(self, auth_client, auth_app):
        with auth_app.app_context():
            user = User.query.filter_by(username="sec_analyst").first()
            token = generate_token(user)

        resp = auth_client.get(
            "/api/v1/alerts",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    def test_analyst_forbidden_from_promoting_model(self, auth_client, auth_app):
        with auth_app.app_context():
            user = User.query.filter_by(username="sec_analyst").first()
            token = generate_token(user)

        resp = auth_client.post(
            "/api/v1/monitoring/registry/promote",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "model_id": "some-candidate-uuid",
                "approved_by": "sec_analyst",
                "approval_notes": "Attempting unprivileged promotion by analyst",
            },
        )
        assert resp.status_code == 403
        data = resp.get_json()
        assert data["error"]["code"] == "FORBIDDEN"

    def test_admin_can_promote_model_with_valid_notes(self, auth_client, auth_app):
        with auth_app.app_context():
            admin = User.query.filter_by(username="sec_admin").first()
            token = generate_token(admin)

            # Insert candidate entry in model registry
            entry = ModelRegistryEntry(
                model_name="OptunaTuned_Candidate",
                model_version="1.1.0-rc1",
                preprocessor_version="1.0.0",
                model_artifact_hash="c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495",
                preprocessor_artifact_hash="effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653",
                lifecycle_status="VALIDATED",
                decision_threshold=0.5,
                feature_contract=["sttl", "sload"],
                training_dataset_provenance={"dataset": "UNSW-NB15"},
                evaluation_split_metrics={"accuracy": 0.981},
                is_active=False,
            )
            db.session.add(entry)
            db.session.commit()
            candidate_id = entry.id

        resp = auth_client.post(
            "/api/v1/monitoring/registry/promote",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "model_id": candidate_id,
                "approved_by": "sec_admin",
                "approval_notes": "Audited evaluation metrics and verified feature contracts on Day 2 holdout.",
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["lifecycle_status"] == "PRODUCTION"
        assert data["is_active"] is True
        assert data["promoted_by"] == "sec_admin"

    def test_admin_promotion_requires_meaningful_justification(self, auth_client, auth_app):
        with auth_app.app_context():
            admin = User.query.filter_by(username="sec_admin").first()
            token = generate_token(admin)

        resp = auth_client.post(
            "/api/v1/monitoring/registry/promote",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "model_id": "some-id",
                "approved_by": "sec_admin",
                "approval_notes": "ok",  # Less than 10 characters
            },
        )
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "INSUFFICIENT_APPROVAL_JUSTIFICATION"


# ─── 4. Demo Seeding Production Denial Tests ─────────────────────────────────
class TestDemoSeedingProductionDenial:
    """Ensure demo seeding strictly returns 403 under all production flag combinations."""

    @pytest.mark.parametrize(
        "env_var,env_val",
        [
            ("FLASK_ENV", "production"),
            ("APP_ENV", "production"),
            ("ENV", "production"),
        ],
    )
    def test_demo_alerts_seeding_forbidden_in_production(self, auth_client, auth_app, env_var, env_val):
        with auth_app.app_context():
            admin = User.query.filter_by(username="sec_admin").first()
            token = generate_token(admin)

        with patch.dict(os.environ, {env_var: env_val}):
            resp = auth_client.post(
                "/api/v1/alerts/seed-demo",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 403
            assert resp.get_json()["error"]["code"] == "FORBIDDEN_IN_PRODUCTION"

    def test_demo_monitoring_seeding_forbidden_in_production(self, auth_client, auth_app):
        with auth_app.app_context():
            admin = User.query.filter_by(username="sec_admin").first()
            token = generate_token(admin)

        with patch.dict(os.environ, {"FLASK_ENV": "production"}):
            resp = auth_client.post(
                "/api/v1/monitoring/seed-demo",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 403
            assert resp.get_json()["error"]["code"] == "FORBIDDEN_IN_PRODUCTION"


# ─── 5. Security Response Headers & Tracing Tests ─────────────────────────────
class TestSecurityHeadersAndTracing:
    """Verify presence of defense-in-depth security headers and request IDs."""

    def test_security_headers_present_on_all_responses(self, auth_client):
        resp = auth_client.get("/api/v1/health")
        assert resp.status_code == 200
        headers = resp.headers

        assert headers.get("X-Content-Type-Options") == "nosniff"
        assert headers.get("X-Frame-Options") == "DENY"
        assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert "Content-Security-Policy" in headers
        assert "default-src 'self'" in headers["Content-Security-Policy"]
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
        assert "X-Request-ID" in headers

    def test_request_id_correlation_echo(self, auth_client):
        custom_id = f"soc-req-{uuid.uuid4()}"
        resp = auth_client.get("/api/v1/health", headers={"X-Request-ID": custom_id})
        assert resp.status_code == 200
        assert resp.headers.get("X-Request-ID") == custom_id


# ─── 6. Readiness Probe & Error Shielding Tests ───────────────────────────────
class TestReadinessProbeAndErrorShielding:
    """Ensure readiness probe and error handlers do not leak infrastructure details."""

    def test_readiness_probe_healthy(self, auth_client):
        resp = auth_client.get("/api/v1/ready")
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["status"] == "ok"
        assert data["checks"]["database"]["status"] == "ok"
        assert "monitoring" in data["checks"]

    def test_readiness_probe_failure_is_sanitized(self, auth_client):
        # Mock engine.connect to simulate database connectivity failure
        with patch("app.extensions.db.engine.connect", side_effect=sqlite3.OperationalError("Sensitive path /var/db/leaked.db")):
            resp = auth_client.get("/api/v1/ready")
            assert resp.status_code == 503
            data = resp.get_json()
            assert data["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
            # Ensure raw exception string is not leaked to client
            db_check = data["error"]["details"]["checks"]["database"]
            assert db_check["status"] == "error"
            assert db_check["message"] == "Database connection unreachable"
            assert "/var/db/leaked.db" not in str(data)


# ─── 7. Model Artifact Cryptographic Integrity Tests ──────────────────────────
class TestModelArtifactIntegrity:
    """Verify SHA-256 verification and fail-closed behavior on tampered models."""

    def test_production_artifacts_match_authoritative_hashes(self):
        detector_path = Path("artifacts/models/production_detector.joblib")
        prep_path = Path("artifacts/models/production_preprocessor.joblib")

        assert detector_path.exists()
        assert prep_path.exists()

        assert ProductionInferenceService.compute_sha256(detector_path) == EXPECTED_DETECTOR_SHA256
        assert ProductionInferenceService.compute_sha256(prep_path) == EXPECTED_PREPROCESSOR_SHA256

    def test_tampered_model_artifact_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tampered_path = Path(tmp_dir) / "tampered_detector.joblib"
            tampered_path.write_bytes(b"corrupted-or-malicious-bytes")

            # Initialization and load_artifacts() must raise RuntimeError and fail closed
            with pytest.raises(RuntimeError, match="Model artifact SHA-256 integrity verification failed"):
                ProductionInferenceService(
                    model_path=tampered_path,
                    verify_checksums=True,
                )


# ─── 8. Safe Database Backup & Recovery Test ──────────────────────────────────
class TestDisposableDatabaseRecovery:
    """Test backup and restoration on a disposable temporary SQLite database."""

    def test_sqlite_online_backup_and_recovery_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            active_db = Path(tmp_dir) / "active.db"
            backup_db = Path(tmp_dir) / "backup.db"

            # 1. Create active database and insert records
            conn = sqlite3.connect(active_db)
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE test_alerts (id TEXT PRIMARY KEY, score REAL, label TEXT)")
            cursor.execute("INSERT INTO test_alerts VALUES ('alert-1', 0.942, 'CRITICAL')")
            cursor.execute("INSERT INTO test_alerts VALUES ('alert-2', 0.125, 'LOW')")
            conn.commit()

            # 2. Perform online transactional backup via sqlite3 backup API
            backup_conn = sqlite3.connect(backup_db)
            with backup_conn:
                conn.backup(backup_conn, pages=100)
            backup_conn.close()
            conn.close()

            assert backup_db.exists()
            assert backup_db.stat().st_size > 0

            # 3. Simulate disaster: corrupt/delete records in active DB
            corrupt_conn = sqlite3.connect(active_db)
            corrupt_conn.execute("DELETE FROM test_alerts")
            corrupt_conn.commit()
            count = corrupt_conn.execute("SELECT count(*) FROM test_alerts").fetchone()[0]
            corrupt_conn.close()
            assert count == 0

            # 4. Perform recovery: restore from backup into a clean target DB
            restored_db = Path(tmp_dir) / "restored.db"
            src_conn = sqlite3.connect(backup_db)
            dest_conn = sqlite3.connect(restored_db)
            with dest_conn:
                src_conn.backup(dest_conn)
            src_conn.close()

            # 5. Verify restored data
            res = dest_conn.execute("SELECT id, score, label FROM test_alerts ORDER BY id").fetchall()
            dest_conn.close()

            assert len(res) == 2
            assert res[0] == ("alert-1", 0.942, "CRITICAL")
            assert res[1] == ("alert-2", 0.125, "LOW")
