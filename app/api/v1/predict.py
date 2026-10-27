"""
Production Anomaly Scoring API Endpoints
=========================================
Version: 1.0 (Milestone Sprint)

Routes:
- POST /api/v1/predict: Score single flow observation with risk level and explanation.
- POST /api/v1/predict/batch: Score batch flow observations with summary analytics.
- GET  /api/v1/model/info: Retrieve deployed model architecture, version, and schema metadata.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from flask import Blueprint, request

from app.utils.auth import require_role
from app.utils.response import error_response, success_response
from features.policy import PolicyViolationError
from ml.production_service import ProductionInferenceService

logger = logging.getLogger("predict_api")

predict_bp = Blueprint("predict", __name__)

# Global production inference service singleton
_SERVICE_INSTANCE: ProductionInferenceService | None = None


def get_inference_service() -> ProductionInferenceService:
    """Lazily initialize or return production inference service singleton."""
    global _SERVICE_INSTANCE
    if _SERVICE_INSTANCE is None:
        model_path = Path("artifacts/models/production_detector.joblib")
        prep_path = Path("artifacts/models/production_preprocessor.joblib")
        _SERVICE_INSTANCE = ProductionInferenceService(
            model_path=model_path,
            preprocessor_path=prep_path,
            threshold=0.5,
        )
    return _SERVICE_INSTANCE


@predict_bp.route("/predict", methods=["POST"])
@require_role("analyst", "admin")
def predict_single() -> Any:
    """
    Score a single flow record.

    Payload format: JSON object with forward-observable numeric flow metrics.
    Rejects reverse-direction features (dbytes, tcprtt) and target labels.
    """
    if not request.is_json:
        return error_response(
            message="Request body must be valid application/json",
            status_code=400,
            error_code="INVALID_CONTENT_TYPE",
        )

    flow_data = request.get_json(silent=True)
    if not isinstance(flow_data, dict) or not flow_data:
        return error_response(
            message="Request payload must be a non-empty JSON object",
            status_code=400,
            error_code="EMPTY_PAYLOAD",
        )

    service = get_inference_service()

    try:
        result = service.predict_single(flow_data)
        return success_response(data=result, status_code=200)

    except PolicyViolationError as pve:
        logger.warning("Feature policy violation: %s", pve)
        return error_response(
            message=str(pve),
            status_code=422,
            error_code="FEATURE_POLICY_VIOLATION",
        )
    except ValueError as ve:
        logger.warning("Schema validation error: %s", ve)
        return error_response(
            message=str(ve),
            status_code=400,
            error_code="SCHEMA_VALIDATION_ERROR",
        )
    except Exception as exc:
        logger.error("Inference internal error: %s", exc, exc_info=True)
        return error_response(
            message="Inference processing encountered an unexpected internal error.",
            status_code=500,
            error_code="INTERNAL_INFERENCE_ERROR",
        )


@predict_bp.route("/predict/batch", methods=["POST"])
@require_role("analyst", "admin")
def predict_batch() -> Any:
    """Score a batch of flow records with summary statistics."""
    if not request.is_json:
        return error_response(
            message="Request body must be valid application/json",
            status_code=400,
            error_code="INVALID_CONTENT_TYPE",
        )

    payload = request.get_json(silent=True)
    if isinstance(payload, dict) and "records" in payload:
        records = payload["records"]
    elif isinstance(payload, list):
        records = payload
    else:
        return error_response(
            message="Batch payload must be a list of flow records or {'records': [...]}",
            status_code=400,
            error_code="INVALID_BATCH_FORMAT",
        )

    if not records or not isinstance(records, list):
        return error_response(
            message="Batch records list cannot be empty",
            status_code=400,
            error_code="EMPTY_BATCH",
        )

    if len(records) > 5000:
        return error_response(
            message=f"Batch size exceeds maximum limit of 5,000 records (received {len(records)})",
            status_code=413,
            error_code="BATCH_SIZE_EXCEEDED",
        )

    service = get_inference_service()

    import time
    t_start = time.perf_counter()
    try:
        batch_result = service.predict_batch(records)
        elapsed_ms = (time.perf_counter() - t_start) * 1000.0

        # Record aggregate operational monitoring telemetry
        try:
            from app.api.v1.monitoring import get_monitoring_service
            mon_service = get_monitoring_service()
            mon_service.record_batch_telemetry(
                batch_id=request.headers.get("X-Batch-ID"),
                records=records,
                predictions=batch_result["predictions"],
                latency_ms=elapsed_ms,
                source=request.headers.get("X-Source", "batch_upload"),
            )
        except Exception as mon_err:
            logger.warning("Monitoring telemetry recording non-fatal error: %s", mon_err)

        return success_response(data=batch_result, status_code=200)

    except PolicyViolationError as pve:
        return error_response(
            message=str(pve),
            status_code=422,
            error_code="FEATURE_POLICY_VIOLATION",
        )
    except ValueError as ve:
        return error_response(
            message=str(ve),
            status_code=400,
            error_code="SCHEMA_VALIDATION_ERROR",
        )
    except Exception as exc:
        logger.error("Batch inference internal error: %s", exc, exc_info=True)
        return error_response(
            message="Batch inference encountered an unexpected internal error.",
            status_code=500,
            error_code="INTERNAL_INFERENCE_ERROR",
        )


@predict_bp.route("/model/info", methods=["GET"])
def model_info() -> Any:
    """Return deployed model architecture, version, threshold, and feature metadata."""
    service = get_inference_service()
    info = service.get_info()
    return success_response(data=info, status_code=200)


@predict_bp.route("/model/evaluation", methods=["GET"])
@require_role("analyst", "admin")
def model_evaluation() -> Any:
    """Return comprehensive model evaluation benchmarks, confusion matrix, and comparisons."""
    from ml.evaluation_service import get_evaluation_service

    service = get_evaluation_service()
    report = service.get_evaluation_report()
    return success_response(data=report, status_code=200)
