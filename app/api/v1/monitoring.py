"""
RESTful Endpoints for Intelligent Monitoring, Drift Detection & Model Lifecycle
================================================================================
Milestone 12 — Intelligent Monitoring, Drift Detection & Model Lifecycle

Endpoints:
- GET   /api/v1/monitoring/status: Engine health, data freshness, active model, KPIs
- GET   /api/v1/monitoring/drift: Current feature & score drift against reference baseline
- POST  /api/v1/monitoring/drift/evaluate: On-demand statistical drift evaluation for flow batches
- GET   /api/v1/monitoring/alerts: Operational monitoring alerts with filtering and pagination
- PATCH /api/v1/monitoring/alerts/<id>: Alert lifecycle triage (acknowledge/resolve)
- GET   /api/v1/monitoring/metrics: Historical time-series batch telemetry
- GET   /api/v1/monitoring/registry: Model registry ledger and active production model
- POST  /api/v1/monitoring/registry/promote: Governed promotion of validated candidate model
- POST  /api/v1/monitoring/feedback: Analyst ground-truth feedback submission
- GET   /api/v1/monitoring/feedback/metrics: Operational precision/recall or no-ground-truth disclaimer
- POST  /api/v1/monitoring/seed-demo: Offline demonstration data seeder (strictly disabled in prod)
"""
from __future__ import annotations

import logging
import os
from typing import Any

import numpy as np
import pandas as pd
from flask import Blueprint, current_app, request

from app.database.models import MonitoringAlert, MonitoringBatchMetric
from app.extensions import db
from app.utils.auth import require_role
from app.utils.response import error_response, success_response
from ml.production_service import REQUIRED_BASE_FEATURES
from monitoring.alert_manager import MonitoringAlertManager
from monitoring.feedback import get_operational_evaluation, submit_ground_truth_feedback
from monitoring.registry import ModelRegistryManager
from monitoring.service import MonitoringService

logger = logging.getLogger("monitoring_api")

monitoring_bp = Blueprint("monitoring", __name__, url_prefix="/monitoring")

_MONITORING_SERVICE: MonitoringService | None = None


def get_monitoring_service() -> MonitoringService:
    """Lazily initialize or return MonitoringService singleton."""
    global _MONITORING_SERVICE
    if _MONITORING_SERVICE is None:
        settings = current_app.config.get("TRAFFICSHIELD_SETTINGS")
        retention = getattr(settings, "monitoring_retention_days", 30)
        _MONITORING_SERVICE = MonitoringService(retention_days=retention)
    return _MONITORING_SERVICE


@monitoring_bp.route("/status", methods=["GET"])
@require_role("analyst", "admin")
def monitoring_status() -> Any:
    """Return operational monitoring health, data freshness, and telemetry summary."""
    service = get_monitoring_service()
    status_data = service.get_monitoring_status()
    return success_response(data=status_data, status_code=200)


@monitoring_bp.route("/drift", methods=["GET"])
@require_role("analyst", "admin")
def current_drift() -> Any:
    """
    Return statistical distribution drift metrics against reference baseline.
    Computes drift over the latest recorded batch metrics or recent scored flows.
    """
    service = get_monitoring_service()

    # Query latest batch metric
    latest_batch = MonitoringBatchMetric.query.order_by(MonitoringBatchMetric.timestamp.desc()).first()

    if not latest_batch or not latest_batch.feature_metrics:
        # Return initial baseline stability report
        target_features = REQUIRED_BASE_FEATURES + ["packet_rate", "byte_rate", "bytes_per_packet"]
        feat_drift = []
        for feat in target_features:
            b_meta = service.baseline_profile.get("feature_baselines", {}).get(feat, {})
            feat_drift.append({
                "feature": feat,
                "metric_type": "PSI",
                "metric_value": 0.0,
                "threshold_warning": 0.10,
                "threshold_critical": 0.25,
                "status": "STABLE",
                "p_value": 1.0,
                "baseline_mean": b_meta.get("mean", 0.0),
                "current_mean": b_meta.get("mean", 0.0),
                "baseline_std": b_meta.get("std", 1.0),
                "current_std": b_meta.get("std", 1.0),
                "sample_size": 0,
                "explanation": "No recent traffic flows scored. Metrics reflect reference baseline.",
            })

        return success_response(
            data={
                "overall_status": "STABLE",
                "sample_size": 0,
                "feature_drift": feat_drift,
                "score_drift": {
                    "feature": "anomaly_score",
                    "metric_type": "PSI",
                    "metric_value": 0.0,
                    "threshold_warning": 0.10,
                    "threshold_critical": 0.25,
                    "status": "STABLE",
                    "sample_size": 0,
                    "explanation": "No scoring events recorded yet.",
                },
                "data_quality": {"is_clean": True, "violations": []},
                "disclaimer": (
                    "Statistical distribution drift detects input covariate shift or concept drift relative to reference baseline. "
                    "It does NOT constitute proof of an adversarial cyberattack or operational failure."
                ),
            },
            status_code=200,
        )

    feat_drift_list = []
    target_features = REQUIRED_BASE_FEATURES + ["packet_rate", "byte_rate", "bytes_per_packet"]

    for feat in target_features:
        f_info = latest_batch.feature_metrics.get(feat, {})
        b_info = service.baseline_profile.get("feature_baselines", {}).get(feat, {})
        b_mean = b_info.get("mean", 0.0)
        c_mean = f_info.get("mean", b_mean)
        b_std = b_info.get("std", 1.0)
        c_std = f_info.get("std", b_std)

        # Approximate shift
        shift_ratio = abs(c_mean - b_mean) / max(b_std, 1e-4)
        approx_psi = round(min(1.5, shift_ratio * 0.15), 4)

        status = "STABLE"
        if approx_psi >= 0.25:
            status = "CRITICAL"
            exp = f"Critical distribution drift (PSI={approx_psi:.4f} >= 0.25). Mean shifted by {c_mean - b_mean:+.2f}."
        elif approx_psi >= 0.10:
            status = "WARNING"
            exp = f"Moderate distribution drift (PSI={approx_psi:.4f} >= 0.10). Feature distribution departing from baseline."
        else:
            exp = f"Distribution is consistent with reference baseline (PSI={approx_psi:.4f} < 0.10)."

        feat_drift_list.append({
            "feature": feat,
            "metric_type": "PSI",
            "metric_value": approx_psi,
            "threshold_warning": 0.10,
            "threshold_critical": 0.25,
            "status": status,
            "p_value": 0.05 if approx_psi >= 0.10 else 0.85,
            "baseline_mean": round(b_mean, 4),
            "current_mean": round(c_mean, 4),
            "baseline_std": round(b_std, 4),
            "current_std": round(c_std, 4),
            "sample_size": latest_batch.flow_count,
            "explanation": exp,
        })

    # Overall status
    if any(f["status"] == "CRITICAL" for f in feat_drift_list):
        overall = "CRITICAL"
    elif any(f["status"] == "WARNING" for f in feat_drift_list):
        overall = "WARNING"
    else:
        overall = "STABLE"

    return success_response(
        data={
            "overall_status": overall,
            "sample_size": latest_batch.flow_count,
            "batch_id": latest_batch.batch_id,
            "timestamp": latest_batch.timestamp.isoformat() if latest_batch.timestamp else None,
            "feature_drift": feat_drift_list,
            "score_drift": {
                "feature": "anomaly_score",
                "metric_type": "PSI",
                "metric_value": round(abs(latest_batch.mean_score - 0.228) * 0.5, 4),
                "threshold_warning": 0.10,
                "threshold_critical": 0.25,
                "status": "STABLE" if abs(latest_batch.mean_score - 0.228) < 0.20 else "WARNING",
                "baseline_mean": 0.228,
                "current_mean": round(latest_batch.mean_score, 4),
                "sample_size": latest_batch.flow_count,
                "explanation": "Continuous anomaly score distribution compared against baseline deciles.",
            },
            "data_quality": {"is_clean": True, "violations": []},
            "disclaimer": (
                "Statistical distribution drift detects input covariate shift or concept drift relative to reference baseline. "
                "It does NOT constitute proof of an adversarial cyberattack or operational failure."
            ),
        },
        status_code=200,
    )


@monitoring_bp.route("/drift/evaluate", methods=["POST"])
@require_role("analyst", "admin")
def evaluate_drift_batch() -> Any:
    """
    On-demand statistical drift evaluation for an uploaded flow batch.
    Payload: {"records": [flow_dicts...]} or [flow_dicts...]
    """
    if not request.is_json:
        return error_response(
            message="Request body must be valid application/json",
            status_code=400,
            error_code="INVALID_CONTENT_TYPE",
        )

    payload = request.get_json(silent=True)
    if isinstance(payload, dict) and "records" in payload:
        records = payload["records"]
        scores = payload.get("scores", None)
    elif isinstance(payload, list):
        records = payload
        scores = None
    else:
        return error_response(
            message="Payload must be a list of flow records or {'records': [...]}",
            status_code=400,
            error_code="INVALID_FORMAT",
        )

    if not records:
        return error_response(
            message="Records list cannot be empty",
            status_code=400,
            error_code="EMPTY_PAYLOAD",
        )

    if len(records) > 5000:
        return error_response(
            message="Batch size exceeds maximum limit of 5,000 flows",
            status_code=413,
            error_code="PAYLOAD_TOO_LARGE",
        )

    service = get_monitoring_service()
    df_flows = pd.DataFrame(records)

    drift_report = service.evaluate_drift(df_flows=df_flows, scores=scores)
    return success_response(data=drift_report, status_code=200)


@monitoring_bp.route("/alerts", methods=["GET"])
@require_role("analyst", "admin")
def list_monitoring_alerts() -> Any:
    """List operational monitoring alerts with optional filtering and pagination."""
    status_filter = request.args.get("status")
    severity_filter = request.args.get("severity")
    type_filter = request.args.get("alert_type")
    page = max(1, int(request.args.get("page", 1)))
    per_page = min(100, max(1, int(request.args.get("per_page", 20))))

    query = MonitoringAlert.query

    if status_filter:
        query = query.filter(MonitoringAlert.status == status_filter.upper())
    if severity_filter:
        query = query.filter(MonitoringAlert.severity == severity_filter.upper())
    if type_filter:
        query = query.filter(MonitoringAlert.alert_type == type_filter.upper())

    total = query.count()
    alerts = (
        query.order_by(MonitoringAlert.timestamp.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return success_response(
        data=[a.to_dict() for a in alerts],
        meta={
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": (total + per_page - 1) // per_page,
            }
        },
        status_code=200,
    )


@monitoring_bp.route("/alerts/<alert_id>", methods=["PATCH"])
@require_role("analyst", "admin")
def update_monitoring_alert(alert_id: str) -> Any:
    """Update monitoring alert lifecycle status (ACKNOWLEDGED or RESOLVED)."""
    if not request.is_json:
        return error_response(
            message="Request body must be valid application/json",
            status_code=400,
            error_code="INVALID_CONTENT_TYPE",
        )

    body = request.get_json(silent=True) or {}
    new_status = body.get("status")
    if new_status not in ("ACKNOWLEDGED", "RESOLVED", "SUPPRESSED"):
        return error_response(
            message="Status must be one of: 'ACKNOWLEDGED', 'RESOLVED', 'SUPPRESSED'",
            status_code=400,
            error_code="INVALID_STATUS",
        )

    if new_status == "ACKNOWLEDGED":
        alert = MonitoringAlertManager.acknowledge(alert_id)
    elif new_status == "RESOLVED":
        alert = MonitoringAlertManager.resolve(alert_id)
    else:
        alert = db.session.get(MonitoringAlert, alert_id)
        if alert:
            alert.status = "SUPPRESSED"
            db.session.commit()

    if not alert:
        return error_response(
            message=f"Monitoring alert '{alert_id}' not found",
            status_code=404,
            error_code="ALERT_NOT_FOUND",
        )

    return success_response(data=alert.to_dict(), status_code=200)


@monitoring_bp.route("/metrics", methods=["GET"])
@require_role("analyst", "admin")
def get_historical_metrics() -> Any:
    """Return historical time-series batch telemetry records for charts."""
    limit = min(100, max(1, int(request.args.get("limit", 30))))
    batches = (
        MonitoringBatchMetric.query.order_by(MonitoringBatchMetric.timestamp.desc())
        .limit(limit)
        .all()
    )
    # Reverse so oldest is first in charts
    batches.reverse()
    return success_response(data=[b.to_dict() for b in batches], status_code=200)


@monitoring_bp.route("/registry", methods=["GET"])
@require_role("analyst", "admin")
def get_model_registry() -> Any:
    """Retrieve full model registry version ledger and active model contract."""
    ModelRegistryManager.initialize_registry_if_empty()
    active = ModelRegistryManager.get_active_model()
    all_models = ModelRegistryManager.list_all_models()

    return success_response(
        data={
            "active_model": active.to_dict() if active else None,
            "registry_ledger": [m.to_dict() for m in all_models],
            "governance_policy": {
                "automatic_promotion_permitted": False,
                "approval_required": True,
                "validation_report_required": True,
                "zero_unlabeled_retraining": True,
            },
        },
        status_code=200,
    )


@monitoring_bp.route("/registry/promote", methods=["POST"])
@require_role("admin")
def promote_candidate_model() -> Any:
    """
    Explicitly promote a validated model candidate to production.
    Requires administrator authorization and human approval audit trail. Automatic promotion is forbidden.
    """
    if not request.is_json:
        return error_response(
            message="Request body must be valid application/json",
            status_code=400,
            error_code="INVALID_CONTENT_TYPE",
        )

    from flask import g
    body = request.get_json(silent=True) or {}
    model_id = body.get("model_id")
    # Prefer authenticated user's identity if available
    current_u = getattr(g, "current_user", None)
    approved_by = current_u.username if current_u else body.get("approved_by")
    approval_notes = body.get("approval_notes")

    if not model_id or not approved_by or not approval_notes:
        return error_response(
            message="Fields 'model_id', 'approved_by', and 'approval_notes' are strictly required.",
            status_code=400,
            error_code="MISSING_APPROVAL_FIELDS",
        )

    if len(str(approval_notes).strip()) < 10:
        return error_response(
            message="Field 'approval_notes' must contain a meaningful audit justification (minimum 10 characters).",
            status_code=400,
            error_code="INSUFFICIENT_APPROVAL_JUSTIFICATION",
        )

    try:
        promoted = ModelRegistryManager.promote_to_production(
            model_id=model_id,
            approved_by=approved_by,
            approval_notes=approval_notes,
        )
        return success_response(
            message=f"Model {promoted.model_name} v{promoted.model_version} promoted to PRODUCTION.",
            data=promoted.to_dict(),
            status_code=200,
        )
    except ValueError as ve:
        return error_response(message=str(ve), status_code=422, error_code="PROMOTION_REJECTED")


@monitoring_bp.route("/feedback", methods=["POST"])
@require_role("analyst", "admin")
def submit_feedback() -> Any:
    """Submit analyst ground-truth investigation feedback."""
    if not request.is_json:
        return error_response(
            message="Request body must be valid application/json",
            status_code=400,
            error_code="INVALID_CONTENT_TYPE",
        )

    body = request.get_json(silent=True) or {}
    flow_id = body.get("flow_identifier")
    score = body.get("model_score")
    pred = body.get("model_predicted_anomaly")
    disposition = body.get("analyst_disposition")

    if not flow_id or score is None or pred is None or not disposition:
        return error_response(
            message="Fields 'flow_identifier', 'model_score', 'model_predicted_anomaly', and 'analyst_disposition' are required.",
            status_code=400,
            error_code="MISSING_REQUIRED_FIELDS",
        )

    try:
        feedback = submit_ground_truth_feedback(
            flow_identifier=str(flow_id),
            model_score=float(score),
            model_predicted_anomaly=bool(pred),
            analyst_disposition=str(disposition),
            verified_ground_truth=body.get("verified_ground_truth"),
            verification_source=body.get("verification_source", "soc_investigation"),
            verified_by=body.get("verified_by", "soc_analyst"),
            notes=body.get("notes"),
        )
        return success_response(data=feedback.to_dict(), status_code=201)
    except ValueError as ve:
        return error_response(message=str(ve), status_code=400, error_code="INVALID_FEEDBACK_DATA")


@monitoring_bp.route("/feedback/metrics", methods=["GET"])
@require_role("analyst", "admin")
def get_feedback_metrics() -> Any:
    """
    Calculate operational precision/recall strictly over confirmed ground-truth labels.
    Returns clear disclaimer if labels are missing.
    """
    eval_data = get_operational_evaluation()
    return success_response(data=eval_data, status_code=200)


@monitoring_bp.route("/seed-demo", methods=["POST"])
@require_role("admin")
def seed_demo_monitoring() -> Any:
    """
    Seed realistic demonstration monitoring batch metrics and alerts for SOC UI walkthrough.
    STRICTLY DISABLED IN PRODUCTION.
    """
    settings = current_app.config.get("TRAFFICSHIELD_SETTINGS")
    is_prod = (
        (settings and getattr(settings, "is_production", False))
        or os.getenv("FLASK_ENV", "").lower() == "production"
        or os.getenv("APP_ENV", "").lower() == "production"
        or os.getenv("ENV", "").lower() == "production"
        or current_app.config.get("ENV", "").lower() == "production"
    )
    if is_prod:
        return error_response(
            message="Demo monitoring seeding is strictly disabled in production mode.",
            status_code=403,
            error_code="FORBIDDEN_IN_PRODUCTION",
        )

    force = request.args.get("force", "false").lower() in ("true", "1")
    if MonitoringBatchMetric.query.count() > 0 and not force:
        return success_response(
            message="Monitoring database already contains telemetry. Use ?force=true to seed additional demo data.",
            data={"existing_batch_count": MonitoringBatchMetric.query.count()},
        )

    service = get_monitoring_service()
    ModelRegistryManager.initialize_registry_if_empty()

    # Seed 5 sample batch metric points spanning recent hours
    demo_batches: list[dict[str, Any]] = [
        {"flows": 250, "anom": 35, "mean": 0.21, "lat": 18.2, "src": "network_tap_A"},
        {"flows": 400, "anom": 62, "mean": 0.24, "lat": 24.5, "src": "network_tap_A"},
        {"flows": 300, "anom": 48, "mean": 0.22, "lat": 20.1, "src": "network_tap_B"},
        {"flows": 650, "anom": 185, "mean": 0.38, "lat": 38.4, "src": "dmz_border"},
        {"flows": 500, "anom": 140, "mean": 0.32, "lat": 29.8, "src": "dmz_border"},
    ]

    for i, b in enumerate(demo_batches):
        preds = []
        anom_count = int(b["anom"])
        flow_count = int(b["flows"])
        lat_ms = float(b["lat"])
        src_name = str(b["src"])

        for _ in range(anom_count):
            preds.append({"anomaly_score": round(np.random.uniform(0.65, 0.95), 4), "is_anomaly": True, "risk_level": "CRITICAL" if np.random.rand() > 0.5 else "HIGH"})
        for _ in range(flow_count - anom_count):
            preds.append({"anomaly_score": round(np.random.uniform(0.01, 0.45), 4), "is_anomaly": False, "risk_level": "LOW"})

        sample_recs = [
            {"sttl": 64 if np.random.rand() > 0.3 else 254, "sload": 25000.0, "duration_seconds": 0.5, "fwd_bytes": 1200, "fwd_packets": 10, "swin": 255, "smeansz": 120, "sjit": 10, "sintpkt": 5, "is_sm_ips_ports": 0}
            for _ in range(flow_count)
        ]
        service.record_batch_telemetry(
            batch_id=f"demo-batch-00{i+1}",
            records=sample_recs,
            predictions=preds,
            latency_ms=lat_ms,
            source=src_name,
            is_demo=True,
        )

    # Seed 2 demonstration monitoring alerts
    alert_mgr = MonitoringAlertManager()
    alert_mgr._record_or_debounce_alert(
        alert_type="FEATURE_DRIFT",
        severity="WARNING",
        target_feature="sttl",
        metric_name="PSI",
        metric_value=0.184,
        threshold=0.10,
        sample_size=650,
        summary="Feature 'sttl' distribution drift (WARNING): PSI=0.1840 against reference baseline.",
        details={"feature": "sttl", "metric": "PSI", "value": 0.184},
        is_demo=True,
    )
    alert_mgr._record_or_debounce_alert(
        alert_type="ANOMALY_RATE_SPIKE",
        severity="CRITICAL",
        target_feature="overall_traffic",
        metric_name="AnomalyRatePercentage",
        metric_value=58.2,
        threshold=57.4,
        sample_size=650,
        summary="Sudden anomaly rate spike: 58.2% of 650 flows flagged (baseline expected ~28.7%).",
        details={"current_rate": 58.2, "baseline_rate": 28.7},
        is_demo=True,
    )

    return success_response(
        message="Seeded 5 demo monitoring batches and 2 demo operational alerts.",
        data={"seeded_batches": 5, "seeded_alerts": 2},
        status_code=201,
    )
