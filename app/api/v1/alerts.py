"""
TrafficShield SOC Alert Persistence & Investigation API
=========================================================
Milestone 11 — SOC Security Operations

Endpoints for durable alert storage, status workflows, analyst investigation notes,
and command center analytics.
"""
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

from flask import Blueprint, current_app, request
from sqlalchemy import desc

from app.database.models import SecurityAlert
from app.extensions import db
from app.utils.auth import require_role
from app.utils.response import error_response, paginated_response, success_response

logger = logging.getLogger("alerts_api")

alerts_bp = Blueprint("alerts", __name__, url_prefix="/alerts")

VALID_STATUSES = {"NEW", "INVESTIGATING", "RESOLVED", "FALSE_POSITIVE"}
VALID_RISK_LEVELS = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


@alerts_bp.route("", methods=["GET"])
@require_role("analyst", "admin")
def list_alerts() -> Any:
    """List security alerts with filtering, sorting, and pagination."""
    status_filter = request.args.get("status")
    risk_filter = request.args.get("risk_level")
    is_anomaly_filter = request.args.get("is_anomaly")
    min_score_filter = request.args.get("min_score")
    max_score_filter = request.args.get("max_score")
    search_query = request.args.get("search")
    include_demo = request.args.get("include_demo", "true").lower() in ("true", "1")

    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(100, max(1, int(request.args.get("per_page", 20))))
    except ValueError:
        return error_response("page and per_page must be valid integers", 400, "INVALID_PAGINATION")

    query = SecurityAlert.query

    if not include_demo:
        query = query.filter(SecurityAlert.is_demo.is_(False))

    if status_filter and status_filter.upper() in VALID_STATUSES:
        query = query.filter(SecurityAlert.status == status_filter.upper())

    if risk_filter and risk_filter.upper() in VALID_RISK_LEVELS:
        query = query.filter(SecurityAlert.risk_level == risk_filter.upper())

    if is_anomaly_filter is not None:
        if is_anomaly_filter.lower() in ("true", "1"):
            query = query.filter(SecurityAlert.is_anomaly.is_(True))
        elif is_anomaly_filter.lower() in ("false", "0"):
            query = query.filter(SecurityAlert.is_anomaly.is_(False))

    if min_score_filter:
        try:
            min_score = float(min_score_filter)
            query = query.filter(SecurityAlert.anomaly_score >= min_score)
        except ValueError:
            pass

    if max_score_filter:
        try:
            max_score = float(max_score_filter)
            query = query.filter(SecurityAlert.anomaly_score <= max_score)
        except ValueError:
            pass

    if search_query:
        search_pattern = f"%{search_query.strip()}%"
        query = query.filter(
            SecurityAlert.id.like(search_pattern)
            | SecurityAlert.request_id.like(search_pattern)
            | SecurityAlert.analyst_notes.like(search_pattern)
        )

    total = query.count()
    items = (
        query.order_by(desc(SecurityAlert.timestamp))
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    alert_dicts = [item.to_dict() for item in items]
    return paginated_response(items=alert_dicts, total=total, page=page, per_page=per_page)


@alerts_bp.route("/stats", methods=["GET"])
@require_role("analyst", "admin")
def alert_stats() -> Any:
    """Return overview analytics with explicit KPI data provenance for SOC command center."""
    total_alerts = SecurityAlert.query.count()
    total_anomalies = SecurityAlert.query.filter(SecurityAlert.is_anomaly.is_(True)).count()
    demo_count = SecurityAlert.query.filter(SecurityAlert.is_demo.is_(True)).count()
    production_count = total_alerts - demo_count

    data_mode = (
        "EMPTY"
        if total_alerts == 0
        else "DEMO_FIXTURE"
        if demo_count == total_alerts
        else "PRODUCTION_ONLY"
        if demo_count == 0
        else "MIXED"
    )

    # Severity counts
    critical = SecurityAlert.query.filter(SecurityAlert.risk_level == "CRITICAL").count()
    high = SecurityAlert.query.filter(SecurityAlert.risk_level == "HIGH").count()
    medium = SecurityAlert.query.filter(SecurityAlert.risk_level == "MEDIUM").count()
    low = SecurityAlert.query.filter(SecurityAlert.risk_level == "LOW").count()

    # Status counts
    new_alerts = SecurityAlert.query.filter(SecurityAlert.status == "NEW").count()
    investigating = SecurityAlert.query.filter(SecurityAlert.status == "INVESTIGATING").count()
    resolved = SecurityAlert.query.filter(SecurityAlert.status == "RESOLVED").count()
    false_positives = SecurityAlert.query.filter(SecurityAlert.status == "FALSE_POSITIVE").count()

    all_scores = [
        row[0]
        for row in db.session.query(SecurityAlert.anomaly_score).all()
    ]
    mean_score = round(float(sum(all_scores) / len(all_scores)), 4) if all_scores else 0.0
    max_score = round(float(max(all_scores)), 4) if all_scores else 0.0

    db_uri = str(current_app.config.get("SQLALCHEMY_DATABASE_URI", ""))
    if "postgres" in db_uri:
        storage_backend = "PostgreSQL Managed Cluster (trafficshield_db)"
    elif ":memory:" in db_uri:
        storage_backend = "SQLite In-Memory (Test)"
    else:
        storage_backend = "SQLite persistent (trafficshield_dev.db)"

    return success_response(
        data={
            "total_records": total_alerts,
            "production_records": production_count,
            "demo_records": demo_count,
            "data_mode": data_mode,
            "storage_backend": storage_backend,
            "total_anomalies": total_anomalies,
            "anomaly_rate": round((total_anomalies / total_alerts * 100), 2) if total_alerts else 0.0,
            "mean_anomaly_score": mean_score,
            "max_anomaly_score": max_score,
            "severity_distribution": {
                "CRITICAL": critical,
                "HIGH": high,
                "MEDIUM": medium,
                "LOW": low,
            },
            "status_distribution": {
                "NEW": new_alerts,
                "INVESTIGATING": investigating,
                "RESOLVED": resolved,
                "FALSE_POSITIVE": false_positives,
            },
        }
    )


@alerts_bp.route("/<alert_id>", methods=["GET"])
@require_role("analyst", "admin")
def get_alert(alert_id: str) -> Any:
    """Retrieve full details of a single security alert."""
    alert = SecurityAlert.query.filter_by(id=alert_id).first()
    if not alert:
        return error_response(f"Alert with ID {alert_id} not found", 404, "ALERT_NOT_FOUND")

    return success_response(data=alert.to_dict())


@alerts_bp.route("/<alert_id>", methods=["PATCH"])
@require_role("analyst", "admin")
def update_alert(alert_id: str) -> Any:
    """Update investigation status and analyst notes for an alert."""
    if not request.is_json:
        return error_response("Payload must be application/json", 400, "INVALID_CONTENT_TYPE")

    data = request.get_json(silent=True) or {}
    alert = SecurityAlert.query.filter_by(id=alert_id).first()
    if not alert:
        return error_response(f"Alert with ID {alert_id} not found", 404, "ALERT_NOT_FOUND")

    if "status" in data:
        new_status = str(data["status"]).upper()
        if new_status not in VALID_STATUSES:
            return error_response(
                f"Invalid status '{new_status}'. Allowed: {sorted(VALID_STATUSES)}",
                400,
                "INVALID_STATUS",
            )
        if alert.status == "NEW" and new_status != "NEW":
            alert.acknowledged_at = datetime.now(UTC)
        alert.status = new_status

    if "analyst_notes" in data:
        notes = str(data["analyst_notes"]).strip()
        if len(notes) > 2000:
            return error_response(
                "analyst_notes exceeds maximum length of 2,000 characters",
                400,
                "NOTES_TOO_LONG",
            )
        alert.analyst_notes = notes

    alert.updated_at = datetime.now(UTC)
    db.session.commit()

    return success_response(data=alert.to_dict(), message="Alert updated successfully")


@alerts_bp.route("", methods=["POST"])
@require_role("analyst", "admin")
def create_alerts() -> Any:
    """
    Persist one or multiple flow prediction results into durable alert storage.
    Accepts single alert dict or list of alert dicts (max 1,000).
    """
    if not request.is_json:
        return error_response("Payload must be application/json", 400, "INVALID_CONTENT_TYPE")

    payload = request.get_json(silent=True)
    if not payload:
        return error_response("Empty alert payload", 400, "EMPTY_PAYLOAD")

    records = payload if isinstance(payload, list) else [payload]
    if len(records) > 1000:
        return error_response(
            f"Alert creation batch exceeds maximum limit of 1,000 records (received {len(records)})",
            413,
            "PAYLOAD_TOO_LARGE",
        )

    created = []

    for r in records:
        if not isinstance(r, dict):
            continue
        try:
            score = float(r.get("anomaly_score", 0.0))
        except (ValueError, TypeError):
            return error_response("anomaly_score must be numeric", 400, "INVALID_SCORE")

        if not (0.0 <= score <= 1.0):
            return error_response(f"anomaly_score {score} must be in range [0.0, 1.0]", 400, "SCORE_OUT_OF_RANGE")

        is_anom = bool(r.get("is_anomaly", score >= 0.5))
        risk = str(r.get("risk_level", "CRITICAL" if score >= 0.85 else "HIGH" if score >= 0.65 else "MEDIUM" if score >= 0.5 else "LOW")).upper()
        if risk not in VALID_RISK_LEVELS:
            risk = "CRITICAL" if score >= 0.85 else "HIGH" if score >= 0.65 else "MEDIUM" if score >= 0.5 else "LOW"

        notes = str(r.get("analyst_notes", "")).strip() if r.get("analyst_notes") else None
        if notes and len(notes) > 2000:
            return error_response("analyst_notes exceeds maximum length of 2,000 characters", 400, "NOTES_TOO_LONG")

        input_feats = dict(r.get("input_features", {})) if isinstance(r.get("input_features"), dict) else {}
        if "hybrid_classification" in r or "supervised" in r or "unsupervised" in r:
            input_feats["_hybrid_evidence"] = {
                "hybrid_classification": r.get("hybrid_classification"),
                "supervised": r.get("supervised"),
                "unsupervised": r.get("unsupervised"),
            }

        alert = SecurityAlert(
            request_id=r.get("request_id"),
            timestamp=datetime.now(UTC),
            is_anomaly=is_anom,
            anomaly_score=score,
            decision_threshold=float(r.get("decision_threshold", 0.5)),
            risk_level=risk,
            model_name=str(r.get("model_name", "OptunaTuned_XGBoost"))[:64],
            model_version=str(r.get("model_version", "1.0.0"))[:32],
            status=r.get("status", "NEW") if r.get("status") in VALID_STATUSES else "NEW",
            analyst_notes=notes,
            input_features=input_feats,
            top_contributing_features=r.get("top_contributing_features", []),
            protocol=str(r.get("protocol", "TCP"))[:16] if r.get("protocol") else None,
            src_port=r.get("src_port"),
            dst_port=r.get("dst_port"),
            is_demo=bool(r.get("is_demo", False)),
            source=str(r.get("source", "batch_upload"))[:32],
        )
        db.session.add(alert)
        created.append(alert)

    db.session.commit()
    return success_response(
        data=[a.to_dict() for a in created],
        status_code=201,
        message=f"Persisted {len(created)} alerts to storage",
    )


@alerts_bp.route("/seed-demo", methods=["POST"])
@require_role("admin")
def seed_demo_alerts() -> Any:
    """
    Seed initial realistic demonstration alerts for SOC dashboard evaluation.
    Clearly marks demonstration fixtures. Strictly rejected in production.
    """
    settings = current_app.config.get("TRAFFICSHIELD_SETTINGS")
    is_prod = (
        (settings and getattr(settings, "is_production", False))
        or os.getenv("FLASK_ENV", "").lower() == "production"
        or os.getenv("APP_ENV", "").lower() == "production"
        or os.getenv("ENV", "").lower() == "production"
        or current_app.config.get("ENV", "").lower() == "production"
    )
    allow_seed = os.getenv("ALLOW_DEMO_SEEDING", "false").lower() in ("true", "1", "yes")
    if is_prod and not allow_seed:
        return error_response(
            message="Demo alert seeding is strictly disabled in production mode.",
            status_code=403,
            error_code="FORBIDDEN_IN_PRODUCTION",
        )

    force = request.args.get("force", "false").lower() in ("true", "1")
    if SecurityAlert.query.count() > 0 and not force:
        return success_response(
            message="Database already contains alerts. Use ?force=true to seed additional demo alerts.",
            data={"existing_count": SecurityAlert.query.count()},
        )

    from app.utils.seeding import seed_demo_alerts_data

    created = seed_demo_alerts_data()
    return success_response(
        data=[a.to_dict() for a in created],
        status_code=201,
        message=f"Seeded {len(created)} demonstration SOC alerts",
    )
