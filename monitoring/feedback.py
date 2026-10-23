"""
Ground-Truth Feedback & Operational Evaluation Engine
======================================================
Milestone 12 — Intelligent Monitoring, Drift Detection & Model Lifecycle

Segregates analyst investigation dispositions from verified ground truth:
- Tracks operational precision, recall, and false-positive rates strictly when verified labels exist
- Refuses to fabricate live accuracy when labels are missing or unverified
- Enforces clear scientific disclaimers: unlabeled traffic is neither assumed benign nor malicious
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.database.models import GroundTruthFeedback
from app.extensions import db
from monitoring.schema import AnalystDisposition

logger = logging.getLogger("monitoring_feedback")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def submit_ground_truth_feedback(
    flow_identifier: str,
    model_score: float,
    model_predicted_anomaly: bool,
    analyst_disposition: str,
    verified_ground_truth: int | None = None,
    verification_source: str = "forensics",
    verified_by: str = "soc_analyst",
    notes: str | None = None,
) -> GroundTruthFeedback:
    """Record an analyst disposition and optional verified ground-truth outcome."""
    valid_dispositions = {d.value for d in AnalystDisposition}
    if analyst_disposition not in valid_dispositions:
        raise ValueError(
            f"Invalid analyst disposition '{analyst_disposition}'. Must be one of: {sorted(valid_dispositions)}"
        )

    if verified_ground_truth is not None and verified_ground_truth not in (0, 1):
        raise ValueError("verified_ground_truth must be 0 (benign), 1 (malicious), or None (unverified)")

    record = GroundTruthFeedback(
        timestamp=_utcnow(),
        flow_identifier=flow_identifier,
        model_score=model_score,
        model_predicted_anomaly=model_predicted_anomaly,
        analyst_disposition=analyst_disposition,
        verified_ground_truth=verified_ground_truth,
        verification_source=verification_source,
        verified_by=verified_by,
        notes=notes,
    )
    db.session.add(record)
    db.session.commit()
    return record


def get_operational_evaluation() -> dict[str, Any]:
    """
    Compute operational metrics strictly over flows with verified post-incident ground truth.
    If no confirmed ground-truth labels exist, returns clear disclaimer.
    """
    all_feedbacks = GroundTruthFeedback.query.all()
    total_feedbacks = len(all_feedbacks)

    # Disposition breakdown
    disposition_counts = {
        AnalystDisposition.CONFIRMED_THREAT.value: 0,
        AnalystDisposition.BENIGN_FALSE_POSITIVE.value: 0,
        AnalystDisposition.SUSPICIOUS_UNVERIFIED.value: 0,
        AnalystDisposition.POLICY_VIOLATION.value: 0,
    }
    for f in all_feedbacks:
        if f.analyst_disposition in disposition_counts:
            disposition_counts[f.analyst_disposition] += 1

    # Filter to verified ground-truth records
    verified = [f for f in all_feedbacks if f.verified_ground_truth in (0, 1)]

    if not verified:
        return {
            "status": "NO_GROUND_TRUTH",
            "total_feedback_records": total_feedbacks,
            "verified_ground_truth_count": 0,
            "analyst_dispositions": disposition_counts,
            "disclaimer": (
                "Unlabeled traffic cannot be assumed benign or malicious. Operational precision and recall "
                "are calculated strictly when authoritative post-incident ground truth is verified."
            ),
            "metrics": None,
        }

    # Confusion matrix on verified subset
    tp = sum(1 for f in verified if f.model_predicted_anomaly and f.verified_ground_truth == 1)
    fp = sum(1 for f in verified if f.model_predicted_anomaly and f.verified_ground_truth == 0)
    fn = sum(1 for f in verified if not f.model_predicted_anomaly and f.verified_ground_truth == 1)
    tn = sum(1 for f in verified if not f.model_predicted_anomaly and f.verified_ground_truth == 0)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    accuracy = (tp + tn) / len(verified) if len(verified) > 0 else 0.0

    return {
        "status": "OPERATIONAL_METRICS_CALCULATED",
        "total_feedback_records": total_feedbacks,
        "verified_ground_truth_count": len(verified),
        "analyst_dispositions": disposition_counts,
        "disclaimer": (
            "Operational evaluation computed strictly over confirmed post-incident ground truth. "
            "Does not extrapolate to unverified or unlabeled link traffic."
        ),
        "metrics": {
            "verified_sample_size": len(verified),
            "accuracy": round(accuracy, 4),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "fpr": round(fpr, 4),
            "f1_score": round(f1, 4),
            "confusion_matrix": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        },
    }
