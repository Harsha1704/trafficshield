"""
SQLAlchemy database models — base mixins and audit columns.
Concrete domain models are added in later milestones.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


def _utcnow() -> datetime:
    return datetime.now(UTC)


class UUIDMixin:
    """Primary-key mixin using UUID strings."""
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )


class TimestampMixin:
    """Automatic created_at / updated_at timestamps (UTC)."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class AuditMixin(UUIDMixin, TimestampMixin):
    """Combined UUID PK + timestamps — base for most domain models."""
    __abstract__ = True


# ─── User Authentication & RBAC (Milestone 13) ──────────────────────────────
class User(AuditMixin, db.Model):  # type: ignore[name-defined]
    """
    User account for SOC analysts and system administrators.
    Stores scrypt/pbkdf2 password hash and assigned role ('analyst', 'admin').
    """
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="analyst", nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def set_password(self, password: str) -> None:
        """Hash and store user password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Verify candidate password against hash."""
        return check_password_hash(self.password_hash, password)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
        }


# ─── Placeholder model (keeps SQLAlchemy happy in M1) ─────────────────────────
class SystemEvent(AuditMixin, db.Model):  # type: ignore[name-defined]
    """
    Audit log for system-level events (startup, config changes, etc.).
    Provides a minimal DB schema for Milestone 1.
    """
    __tablename__ = "system_events"

    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(512), nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ─── SOC Security Alert Persistence (Milestone 11) ───────────────────────────
class SecurityAlert(AuditMixin, db.Model):  # type: ignore[name-defined]
    """
    Durable storage for security anomaly detections and analyst investigation lifecycle.
    Keeps analyst notes and status tracking strictly separate from ML predictions.
    """
    __tablename__ = "security_alerts"

    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    is_anomaly: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    anomaly_score: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    decision_threshold: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(
        String(64), default="OptunaTuned_XGBoost", nullable=False
    )
    model_version: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="NEW", nullable=False, index=True
    )  # 'NEW', 'INVESTIGATING', 'RESOLVED', 'FALSE_POSITIVE'
    analyst_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    input_features: Mapped[dict] = mapped_column(JSON, nullable=False)
    top_contributing_features: Mapped[list | None] = mapped_column(JSON, nullable=True)
    protocol: Mapped[str | None] = mapped_column(String(16), nullable=True)
    src_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dst_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), default="batch_upload", nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "request_id": self.request_id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "is_anomaly": self.is_anomaly,
            "anomaly_score": round(self.anomaly_score, 6),
            "decision_threshold": round(self.decision_threshold, 6),
            "risk_level": self.risk_level,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "status": self.status,
            "analyst_notes": self.analyst_notes,
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "input_features": self.input_features,
            "top_contributing_features": self.top_contributing_features or [],
            "protocol": self.protocol,
            "src_port": self.src_port,
            "dst_port": self.dst_port,
            "is_demo": self.is_demo,
            "source": self.source,
        }


# ─── Monitoring & Operational Telemetry (Milestone 12) ────────────────────────
class MonitoringBatchMetric(AuditMixin, db.Model):  # type: ignore[name-defined]
    """
    Aggregated operational telemetry per scoring batch or window.
    Stores statistical aggregates and feature parameters to monitor distribution shifts
    without hoarding raw traffic payloads or sensitive identifiers.
    """
    __tablename__ = "monitoring_batch_metrics"

    batch_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    model_name: Mapped[str] = mapped_column(
        String(64), default="OptunaTuned_XGBoost", nullable=False
    )
    model_version: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)
    artifact_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_threshold: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="batch_upload", nullable=False)
    flow_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    anomaly_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    anomaly_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    mean_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    p95_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    validation_failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    severity_counts: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    score_histogram: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    feature_metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "batch_id": self.batch_id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "artifact_hash": self.artifact_hash,
            "decision_threshold": round(self.decision_threshold, 6),
            "source": self.source,
            "flow_count": self.flow_count,
            "anomaly_count": self.anomaly_count,
            "anomaly_rate": round(self.anomaly_rate, 4),
            "mean_score": round(self.mean_score, 6),
            "p95_score": round(self.p95_score, 6),
            "latency_ms": round(self.latency_ms, 2),
            "validation_failure_count": self.validation_failure_count,
            "severity_counts": self.severity_counts,
            "score_histogram": self.score_histogram,
            "feature_metrics": self.feature_metrics,
            "is_demo": self.is_demo,
        }


class MonitoringAlert(AuditMixin, db.Model):  # type: ignore[name-defined]
    """
    Operational alerts for feature drift, score drift, anomaly rate spikes, and SLA deviations.
    Maintains alert lifecycle state and supports debouncing/deduplication.
    """
    __tablename__ = "monitoring_alerts"

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    alert_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    target_feature: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    metric_name: Mapped[str] = mapped_column(String(32), default="PSI", nullable=False)
    metric_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    summary: Mapped[str] = mapped_column(String(512), nullable=False)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default="ACTIVE", nullable=False, index=True
    )  # 'ACTIVE', 'ACKNOWLEDGED', 'RESOLVED', 'SUPPRESSED'
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "alert_type": self.alert_type,
            "severity": self.severity,
            "target_feature": self.target_feature,
            "metric_name": self.metric_name,
            "metric_value": round(self.metric_value, 4),
            "threshold": round(self.threshold, 4),
            "sample_size": self.sample_size,
            "summary": self.summary,
            "details": self.details or {},
            "status": self.status,
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "occurrence_count": self.occurrence_count,
            "is_demo": self.is_demo,
        }


class GroundTruthFeedback(AuditMixin, db.Model):  # type: ignore[name-defined]
    """
    Verified ground-truth outcomes and analyst investigation feedback.
    Keeps analyst dispositions strictly segregated from verified ground-truth labels.
    """
    __tablename__ = "ground_truth_feedbacks"

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    flow_identifier: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model_score: Mapped[float] = mapped_column(Float, nullable=False)
    model_predicted_anomaly: Mapped[bool] = mapped_column(Boolean, nullable=False)
    analyst_disposition: Mapped[str] = mapped_column(
        String(32), default="SUSPICIOUS_UNVERIFIED", nullable=False
    )
    verified_ground_truth: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # 1 = Attack, 0 = Benign, None = Unverified
    verification_source: Mapped[str] = mapped_column(
        String(64), default="forensics", nullable=False
    )
    verified_by: Mapped[str] = mapped_column(String(64), default="analyst", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "flow_identifier": self.flow_identifier,
            "model_score": round(self.model_score, 6),
            "model_predicted_anomaly": self.model_predicted_anomaly,
            "analyst_disposition": self.analyst_disposition,
            "verified_ground_truth": self.verified_ground_truth,
            "verification_source": self.verification_source,
            "verified_by": self.verified_by,
            "notes": self.notes,
        }


class ModelRegistryEntry(AuditMixin, db.Model):  # type: ignore[name-defined]
    """
    Lightweight model version ledger and governance lifecycle ledger.
    Governs candidate, validated, and production states without automatic promotion.
    """
    __tablename__ = "model_registry_entries"

    model_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    preprocessor_version: Mapped[str] = mapped_column(String(32), nullable=False)
    model_artifact_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    preprocessor_artifact_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(
        String(32), default="PRODUCTION", nullable=False, index=True
    )  # 'PRODUCTION', 'VALIDATED', 'CANDIDATE', 'ARCHIVED', 'RETIRED'
    decision_threshold: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    feature_contract: Mapped[list] = mapped_column(JSON, nullable=False)
    training_dataset_provenance: Mapped[dict] = mapped_column(JSON, nullable=False)
    evaluation_split_metrics: Mapped[dict] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    promoted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approval_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "preprocessor_version": self.preprocessor_version,
            "model_artifact_hash": self.model_artifact_hash,
            "preprocessor_artifact_hash": self.preprocessor_artifact_hash,
            "lifecycle_status": self.lifecycle_status,
            "decision_threshold": round(self.decision_threshold, 6),
            "feature_contract": self.feature_contract,
            "training_dataset_provenance": self.training_dataset_provenance,
            "evaluation_split_metrics": self.evaluation_split_metrics,
            "is_active": self.is_active,
            "promoted_at": self.promoted_at.isoformat() if self.promoted_at else None,
            "promoted_by": self.promoted_by,
            "approval_notes": self.approval_notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
