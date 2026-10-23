"""
Health and Readiness endpoints.

GET /api/v1/health  — Liveness probe. Returns 200 if the process is alive.
GET /api/v1/ready   — Readiness probe. Checks DB connectivity and returns
                       degraded status if dependencies are unavailable.
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from flask import Blueprint, current_app

from app.utils.response import error_response, success_response

logger = logging.getLogger(__name__)

health_bp = Blueprint("health", __name__)

# Record process start time for uptime calculation
_START_TIME = time.monotonic()


@health_bp.get("/health")
def health():
    """
    Liveness probe.

    Returns 200 OK while the process is running.
    Intentionally does not check dependencies — use /ready for that.
    """
    settings = current_app.config.get("TRAFFICSHIELD_SETTINGS")
    return success_response(
        data={
            "status": "ok",
            "service": "TrafficShield",
            "version": settings.app_version if settings else "unknown",
            "timestamp": datetime.now(UTC).isoformat(),
            "uptime_seconds": round(time.monotonic() - _START_TIME, 2),
        }
    )


@health_bp.get("/ready")
def ready():
    """
    Readiness probe.

    Checks that the database is reachable. Returns 200 if all checks pass,
    503 if any critical dependency is unavailable.
    """
    checks: dict[str, dict] = {}
    all_ok = True

    # ─── Database check ───────────────────────────────────────────────────────
    db_status = _check_database()
    checks["database"] = db_status
    if db_status["status"] != "ok":
        all_ok = False

    # ─── Monitoring Telemetry Freshness check ──────────────────────────────────
    mon_status = _check_monitoring_freshness()
    checks["monitoring"] = mon_status

    overall_status = "ok" if all_ok else "degraded"
    http_code = 200 if all_ok else 503

    payload = {
        "status": overall_status,
        "checks": checks,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    if all_ok:
        return success_response(data=payload)
    return error_response(
        message="One or more readiness checks failed",
        status_code=http_code,
        error_code="DEPENDENCY_UNAVAILABLE",
        details=payload,
    )


def _check_database() -> dict:
    """Attempt a minimal DB query to verify connectivity without leaking credentials."""
    try:
        from sqlalchemy import text

        from app.extensions import db
        with db.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:
        logger.warning("Database readiness check failed", exc_info=exc)
        # Never leak raw database connection strings, credentials, or traces
        return {"status": "error", "message": "Database connection unreachable"}


def _check_monitoring_freshness() -> dict:
    """Check telemetry freshness to detect silent pipeline halts."""
    try:
        from datetime import timedelta

        from app.database.models import MonitoringBatchMetric

        latest = MonitoringBatchMetric.query.order_by(MonitoringBatchMetric.timestamp.desc()).first()
        if not latest:
            return {"status": "ok", "telemetry": "no_batches_yet", "fresh": True}

        # Stale threshold: 24 hours
        stale_threshold = timedelta(hours=24)
        age = datetime.now(UTC) - latest.timestamp
        is_stale = age > stale_threshold

        return {
            "status": "warning" if is_stale else "ok",
            "last_batch_at": latest.timestamp.isoformat(),
            "age_seconds": round(age.total_seconds(), 1),
            "fresh": not is_stale,
            "message": "Telemetry is stale (>24h)" if is_stale else "Telemetry is fresh",
        }
    except Exception:
        return {"status": "warning", "fresh": False, "message": "Telemetry status unavailable"}
