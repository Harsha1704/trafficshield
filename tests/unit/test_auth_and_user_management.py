"""
TrafficShield Unit Tests — Authentication Lifecycle, User Bootstrap, and Password Reset
=======================================================================================
Verifies:
- Login with valid credentials succeeds and returns JWT token
- Login with invalid credentials or nonexistent user returns generic 401
- Password reset using User.set_password() cleanly updates hash and allows login with new password
- CLI user management commands (list, reset-password) function securely
- Production bootstrap behavior with initial credentials
"""
from __future__ import annotations

import pytest

from app import create_app
from app.database.models import User
from app.extensions import db
from app.utils.auth import bootstrap_initial_users


@pytest.fixture
def auth_test_app():
    """Create an isolated test application instance."""
    app = create_app("testing")
    app.config["AUTH_ENABLED"] = True
    app.config["SECRET_KEY"] = "testing-secret-key-at-least-32-chars-long"

    with app.app_context():
        # Ensure standard dev analyst has known password for tests
        analyst = User.query.filter_by(username="analyst").first()
        if analyst is None:
            analyst = User(username="analyst", role="analyst", is_active=True)
            db.session.add(analyst)
        analyst.set_password("ValidAnalyst123!")
        db.session.commit()

        yield app

        db.session.remove()
        db.drop_all()


@pytest.fixture
def auth_client(auth_test_app):
    return auth_test_app.test_client()


class TestAuthLifecycleAndReset:
    """Verify login authentication and password reset lifecycle."""

    def test_login_success_with_valid_credentials(self, auth_client):
        resp = auth_client.post(
            "/api/v1/auth/login",
            json={"username": "analyst", "password": "ValidAnalyst123!"},
        )
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["success"] is True
        assert "token" in payload["data"]
        assert payload["data"]["user"]["username"] == "analyst"
        assert payload["data"]["user"]["role"] == "analyst"

    def test_login_failure_with_wrong_password(self, auth_client):
        resp = auth_client.post(
            "/api/v1/auth/login",
            json={"username": "analyst", "password": "WrongPassword123!"},
        )
        assert resp.status_code == 401
        payload = resp.get_json()
        assert payload["success"] is False
        assert payload["error"]["code"] == "INVALID_CREDENTIALS"
        assert payload["error"]["message"] == "Invalid username or password"

    def test_login_failure_with_nonexistent_user(self, auth_client):
        resp = auth_client.post(
            "/api/v1/auth/login",
            json={"username": "ghost_operator", "password": "SomePassword123!"},
        )
        assert resp.status_code == 401
        payload = resp.get_json()
        assert payload["success"] is False
        assert payload["error"]["code"] == "INVALID_CREDENTIALS"
        assert payload["error"]["message"] == "Invalid username or password"

    def test_password_reset_flow(self, auth_test_app, auth_client):
        """Verify resetting user password allows login with new credentials only."""
        with auth_test_app.app_context():
            user = User.query.filter_by(username="analyst").first()
            assert user is not None
            user.set_password("BrandNewPassword2026!")
            db.session.commit()

        # Old password must now fail
        old_resp = auth_client.post(
            "/api/v1/auth/login",
            json={"username": "analyst", "password": "ValidAnalyst123!"},
        )
        assert old_resp.status_code == 401

        # New password must now succeed
        new_resp = auth_client.post(
            "/api/v1/auth/login",
            json={"username": "analyst", "password": "BrandNewPassword2026!"},
        )
        assert new_resp.status_code == 200
        assert new_resp.get_json()["data"]["user"]["username"] == "analyst"

    def test_flask_cli_user_management(self, auth_test_app, auth_client):
        """Verify the Flask CLI 'users reset-password' command resets password."""
        runner = auth_test_app.test_cli_runner()

        # Reset password via CLI
        result = runner.invoke(
            args=["users", "reset-password", "analyst", "--password", "CliResetPass2026!"]
        )
        assert result.exit_code == 0
        assert "Successfully reset password" in result.output

        # Verify login with the CLI-reset password
        login_resp = auth_client.post(
            "/api/v1/auth/login",
            json={"username": "analyst", "password": "CliResetPass2026!"},
        )
        assert login_resp.status_code == 200

    def test_production_initial_bootstrap_with_credentials(self):
        """Verify bootstrap_initial_users in production seeds accounts from config."""
        app = create_app("testing")
        app.config["ADMIN_INITIAL_USERNAME"] = "custom_admin"
        app.config["ADMIN_INITIAL_PASSWORD"] = "StrongAdminPass2026!"
        app.config["ANALYST_INITIAL_USERNAME"] = "custom_analyst"
        app.config["ANALYST_INITIAL_PASSWORD"] = "StrongAnalystPass2026!"

        # Mock settings to simulate production
        class MockSettings:
            is_production = True
            admin_initial_username = "custom_admin"
            admin_initial_password = "StrongAdminPass2026!"
            analyst_initial_username = "custom_analyst"
            analyst_initial_password = "StrongAnalystPass2026!"

        app.config["TRAFFICSHIELD_SETTINGS"] = MockSettings()

        with app.app_context():
            db.create_all()
            bootstrap_initial_users(app)

            admin = User.query.filter_by(username="custom_admin").first()
            assert admin is not None
            assert admin.role == "admin"
            assert admin.check_password("StrongAdminPass2026!")

            analyst = User.query.filter_by(username="custom_analyst").first()
            assert analyst is not None
            assert analyst.role == "analyst"
            assert analyst.check_password("StrongAnalystPass2026!")

            # Verify that re-running bootstrap with updated config synchronizes the password
            app.config["ANALYST_INITIAL_PASSWORD"] = "UpdatedViaEnvPass2026!"
            bootstrap_initial_users(app)
            db.session.expire_all()
            analyst_recheck = User.query.filter_by(username="custom_analyst").first()
            assert analyst_recheck.check_password("UpdatedViaEnvPass2026!")

            # Verify that re-running bootstrap with empty password leaves existing user untouched
            app.config["ANALYST_INITIAL_PASSWORD"] = ""
            bootstrap_initial_users(app)
            db.session.expire_all()
            analyst_recheck2 = User.query.filter_by(username="custom_analyst").first()
            assert analyst_recheck2.check_password("UpdatedViaEnvPass2026!")

            db.session.remove()
            db.drop_all()
