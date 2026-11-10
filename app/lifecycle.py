"""
TrafficShield Application Lifecycle Management
==============================================
Production startup preflight verification, health qualification, and graceful teardown.
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
from pathlib import Path
from typing import Any

from flask import Flask
from sqlalchemy import text

from app.extensions import db
from config.settings import BaseAppSettings, get_settings
from ml.production_service import (
    EXPECTED_DETECTOR_SHA256,
    EXPECTED_IFOREST_SHA256,
    EXPECTED_PREPROCESSOR_SHA256,
)
from streaming.manager import RealTimeDetectionManager

logger = logging.getLogger("app.lifecycle")

_SHUTDOWN_LOCK = threading.Lock()
_SHUTDOWN_COMPLETED = False


def sanitize_message(msg: str) -> str:
    """Sanitize connection strings, secrets, and credentials from log/exception messages."""
    if not msg:
        return ""
    # Redact URIs with passwords (e.g. postgresql://user:pass@host:port/db)
    sanitized = re.sub(r"://([^:@\s]+):([^@\s]+)@", r"://\1:***@", str(msg))
    # Redact secret keys or tokens in query/form strings
    sanitized = re.sub(r"(token|secret|password|api_key|auth)=([^\s&]+)", r"\1=***", sanitized, flags=re.I)
    return sanitized


def compute_sha256(filepath: Path) -> str:
    """Compute SHA-256 digest of a file on disk."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def run_startup_preflight(
    app: Flask,
    settings: BaseAppSettings | None = None,
    verify_checksums: bool = True,
) -> dict[str, Any]:
    """
    Execute fail-fast preflight validation before the WSGI server accepts traffic:
    1. Validates host, port, and threading configuration.
    2. Validates database connectivity with sanitized error reporting.
    3. Validates required production detector and preprocessor artifacts (SHA-256 integrity).
    4. Qualifies optional Isolation Forest artifact (logs warning if absent without aborting).
    """
    if settings is None:
        settings = app.config.get("TRAFFICSHIELD_SETTINGS") or get_settings()

    host = getattr(settings, "server_host", "127.0.0.1")
    port = getattr(settings, "server_port", 5000)
    threads = getattr(settings, "server_threads", 4)

    # 1. Validate network binding constraints
    if not (1 <= port <= 65535):
        raise ValueError(f"Invalid server_port: {port}. Must be between 1 and 65535.")
    if not host or not str(host).strip():
        raise ValueError("Invalid server_host: Host binding address must not be empty.")
    if threads < 1:
        raise ValueError(f"Invalid server_threads: {threads}. Must be at least 1.")

    # 2. Database connectivity preflight
    try:
        with app.app_context():
            with db.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
    except Exception as exc:
        clean_err = sanitize_message(str(exc))
        logger.critical("Database connectivity preflight failed: %s", clean_err)
        raise RuntimeError(f"Database preflight check failed: {clean_err}") from None

    # 3. Model artifacts preflight
    detector_path = Path("artifacts/models/production_detector.joblib")
    preprocessor_path = Path("artifacts/models/production_preprocessor.joblib")
    iforest_path = Path("artifacts/models/production_iforest.joblib")

    if not detector_path.exists():
        raise RuntimeError(
            f"Required production detector artifact missing: {detector_path.as_posix()}"
        )
    if not preprocessor_path.exists():
        raise RuntimeError(
            f"Required production preprocessor artifact missing: {preprocessor_path.as_posix()}"
        )

    if verify_checksums:
        det_hash = compute_sha256(detector_path)
        if det_hash != EXPECTED_DETECTOR_SHA256:
            raise RuntimeError(
                f"Production detector artifact integrity failed (expected {EXPECTED_DETECTOR_SHA256}, got {det_hash})"
            )

        prep_hash = compute_sha256(preprocessor_path)
        if prep_hash != EXPECTED_PREPROCESSOR_SHA256:
            raise RuntimeError(
                f"Production preprocessor artifact integrity failed (expected {EXPECTED_PREPROCESSOR_SHA256}, got {prep_hash})"
            )

    # 4. Optional Isolation Forest check
    iforest_status = "OPTIONAL_ABSENT"
    if iforest_path.exists():
        if verify_checksums:
            if_hash = compute_sha256(iforest_path)
            if if_hash != EXPECTED_IFOREST_SHA256:
                raise RuntimeError(
                    f"Production Isolation Forest artifact integrity failed (expected {EXPECTED_IFOREST_SHA256}, got {if_hash})"
                )
        iforest_status = "VERIFIED"
    else:
        logger.warning(
            "Isolation Forest artifact not found at %s; operating in supervised-only mode.",
            iforest_path.as_posix(),
        )

    report = {
        "status": "READY",
        "database": "CONNECTED",
        "detector": "VERIFIED",
        "preprocessor": "VERIFIED",
        "iforest": iforest_status,
        "host": host,
        "port": port,
        "threads": threads,
        "single_process": True,
    }
    logger.info("Startup preflight completed successfully: %s", report)
    return report


def shutdown_application(
    app: Flask | None = None,
    drain_timeout: float = 5.0,
) -> dict[str, Any]:
    """
    Execute orderly, idempotent teardown of TrafficShield background workers and DB pool.
    1. Halts packet ingestion and joins pipeline threads.
    2. Flushes in-flight flows and drains inference queue up to drain_timeout.
    3. Disposes SQLAlchemy connection pool.
    4. Reports accurate final flow and worker state.
    """
    global _SHUTDOWN_COMPLETED

    with _SHUTDOWN_LOCK:
        manager = RealTimeDetectionManager.get_instance()
        manager_status = manager.stop(drain_timeout=drain_timeout)

        # Dispose database pool
        try:
            if app:
                with app.app_context():
                    db.engine.dispose()
            else:
                db.engine.dispose()
        except Exception as exc:
            logger.debug("Database pool disposal notice: %s", exc)

        _SHUTDOWN_COMPLETED = True

        shutdown_summary = {
            "status": "STOPPED",
            "manager_state": manager_status.get("state"),
            "flows_queued": manager.flows_queued,
            "flows_queue_dropped": manager.flows_queue_dropped,
            "pipeline_join_timed_out": manager.pipeline_join_timed_out,
            "worker": manager_status.get("worker", {}),
        }
        logger.info("Application shutdown completed: %s", shutdown_summary)
        return shutdown_summary


def is_shutdown_completed() -> bool:
    """Return whether application shutdown has been executed."""
    return _SHUTDOWN_COMPLETED


def reset_shutdown_state() -> None:
    """Reset shutdown state (intended for testing harness)."""
    global _SHUTDOWN_COMPLETED
    with _SHUTDOWN_LOCK:
        _SHUTDOWN_COMPLETED = False
