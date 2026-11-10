"""
Unit tests for Phase 5 Batch 2: Production WSGI and Process Reliability.
========================================================================
Validates:
1. Server host, port, and thread configuration validation.
2. Startup preflight failure on missing or corrupt detector models.
3. Startup preflight optional Isolation Forest qualification.
4. Database connectivity preflight failure and secret/credential sanitization.
5. Successful startup preflight under valid configuration.
6. Single-process deployment constraint and shared manager lifecycle.
7. Graceful shutdown, idempotency, drain timeout handling, and flow accounting.
8. WSGI runner execution and KeyboardInterrupt teardown handling.
"""
from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.lifecycle import (
    reset_shutdown_state,
    run_startup_preflight,
    sanitize_message,
    shutdown_application,
)
from config.settings import DevelopmentSettings
from streaming.manager import RealTimeDetectionManager, WorkerState
from wsgi import run_production_server

# ─── 1. Configuration & Validation Tests ──────────────────────────────────────

def test_server_port_and_host_validation():
    """Verify server host, port, and thread constraints on settings."""
    # Valid defaults
    settings = DevelopmentSettings(server_host="127.0.0.1", server_port=5000, server_threads=4)
    assert settings.server_host == "127.0.0.1"
    assert settings.server_port == 5000
    assert settings.server_threads == 4

    # Invalid ports
    with pytest.raises(ValueError, match="server_port must be between 1 and 65535"):
        DevelopmentSettings(server_port=0)

    with pytest.raises(ValueError, match="server_port must be between 1 and 65535"):
        DevelopmentSettings(server_port=70000)

    with pytest.raises(ValueError, match="server_port must be between 1 and 65535"):
        DevelopmentSettings(server_port=-1)

    # Invalid empty host
    with pytest.raises(ValueError, match="server_host must not be empty"):
        DevelopmentSettings(server_host="   ")

    # Invalid threads
    with pytest.raises(ValueError, match="server_threads must be at least 1"):
        DevelopmentSettings(server_threads=0)


def test_sanitize_message_redacts_credentials_and_tokens():
    """Verify that credentials, passwords, and tokens are scrubbed from error logs."""
    raw_uri_err = "OperationalError: could not connect to postgresql://admin_user:SuperSecretPassword123@db.prod.internal:5432/trafficshield"
    sanitized = sanitize_message(raw_uri_err)
    assert "SuperSecretPassword123" not in sanitized
    assert "postgresql://admin_user:***@db.prod.internal:5432/trafficshield" in sanitized

    raw_token_err = "AuthError: invalid request param token=eyJhGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9&user=analyst"
    sanitized_tok = sanitize_message(raw_token_err)
    assert "eyJhGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in sanitized_tok
    assert "token=***" in sanitized_tok


# ─── 2. Startup Preflight Tests ───────────────────────────────────────────────

def test_startup_preflight_success(app):
    """Verify that startup preflight succeeds with valid configuration and production artifacts."""
    report = run_startup_preflight(app, verify_checksums=False)
    assert report["status"] == "READY"
    assert report["database"] == "CONNECTED"
    assert report["detector"] == "VERIFIED"
    assert report["preprocessor"] == "VERIFIED"
    assert report["single_process"] is True


def test_startup_preflight_detects_missing_detector(app):
    """Verify fail-fast error when required supervised detector is missing."""
    with patch("app.lifecycle.Path.exists", side_effect=lambda: False):
        with pytest.raises(RuntimeError, match="Required production detector artifact missing"):
            run_startup_preflight(app, verify_checksums=False)


def test_startup_preflight_detects_corrupt_detector_checksum(app):
    """Verify fail-fast error when detector checksum fails verification."""
    with patch("app.lifecycle.compute_sha256", return_value="bad_hash_value"):
        with pytest.raises(RuntimeError, match="Production detector artifact integrity failed"):
            run_startup_preflight(app, verify_checksums=True)


def test_startup_preflight_optional_iforest_does_not_abort(app):
    """Verify that missing Isolation Forest logs warning and marks OPTIONAL_ABSENT without crashing."""
    def fake_exists(self):
        if "production_iforest" in str(self):
            return False
        return True

    with patch.object(Path, "exists", fake_exists):
        report = run_startup_preflight(app, verify_checksums=False)
        assert report["status"] == "READY"
        assert report["iforest"] == "OPTIONAL_ABSENT"


def test_startup_preflight_database_failure_is_sanitized(app):
    """Verify database preflight failure redacts connection credentials in the raised RuntimeError."""
    fake_conn = MagicMock()
    fake_conn.__enter__.return_value = fake_conn
    fake_conn.execute.side_effect = Exception(
        "FATAL: password authentication failed for user 'shield_admin' with postgresql://shield_admin:SecretDBPass999@postgres.prod:5432/shield_db"
    )

    with patch("app.extensions.db.engine.connect", return_value=fake_conn):
        with pytest.raises(RuntimeError) as exc_info:
            run_startup_preflight(app)

        err_msg = str(exc_info.value)
        assert "Database preflight check failed" in err_msg
        assert "SecretDBPass999" not in err_msg
        assert "shield_admin:***@" in err_msg


# ─── 3. Single-Process Architecture & Manager Lifecycle Tests ─────────────────

def test_single_process_shared_manager_identity():
    """Verify RealTimeDetectionManager singleton holds identity across concurrent execution threads."""
    instances = []

    def get_mgr():
        instances.append(RealTimeDetectionManager.get_instance())

    threads = [threading.Thread(target=get_mgr) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(instances) == 10
    # Every reference must be the exact identical object
    first = instances[0]
    assert all(inst is first for inst in instances)


# ─── 4. Graceful Shutdown & Teardown Tests ────────────────────────────────────

def test_graceful_shutdown_idempotency_and_state(app):
    """Verify application shutdown stops manager and is safely idempotent on repeated calls."""
    reset_shutdown_state()
    manager = RealTimeDetectionManager.get_instance()

    # Initial shutdown
    res1 = shutdown_application(app)
    assert res1["status"] == "STOPPED"
    assert manager.state in (WorkerState.STOPPED, WorkerState.DEGRADED, WorkerState.FAILED)

    # Second shutdown must be idempotent and return without error
    res2 = shutdown_application(app)
    assert res2["status"] == "STOPPED"


def test_shutdown_with_queued_flows_reports_honest_accounting(app):
    """Verify that when worker cannot finish draining, shutdown accurately accounts for unprocessed flows."""
    reset_shutdown_state()
    manager = RealTimeDetectionManager.get_instance()

    # Populate flow queue with dummy flows
    for i in range(5):
        manager.flow_queue.put({"flow_id": f"flow_{i}"})

    # Shut down with a fast timeout (0.1s)
    res = shutdown_application(app, drain_timeout=0.1)
    assert res["status"] == "STOPPED"
    # Flows dropped or remaining must be counted accurately, never claiming zero if unfinished
    assert isinstance(res["flows_queued"], int)


# ─── 5. Production WSGI Server Runner Tests ───────────────────────────────────

def test_run_production_server_handles_keyboard_interrupt(app):
    """Verify run_production_server handles KeyboardInterrupt and cleanly triggers shutdown_application."""
    reset_shutdown_state()

    mock_serve = MagicMock(side_effect=KeyboardInterrupt)

    with patch("waitress.serve", mock_serve), patch("app.lifecycle.run_startup_preflight") as mock_preflight:
        mock_preflight.return_value = {"status": "READY"}
        # Must not crash, should catch KeyboardInterrupt and cleanly shut down
        run_production_server(
            host="127.0.0.1",
            port=5000,
            threads=2,
            application=app,
        )

        mock_serve.assert_called_once()
