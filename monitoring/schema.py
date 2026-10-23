"""
TrafficShield Monitoring Data Model & Contracts
================================================
Milestone 12 — Intelligent Monitoring, Drift Detection & Model Lifecycle

Defines strongly-typed schemas and enumerations for:
- Operational telemetry and batch-level metrics
- Feature distribution summaries and data quality tracking
- Statistical drift metrics (PSI, KS, Wasserstein) and status indicators
- Operational monitoring alerts, severity levels, and lifecycle states
- Model registry metadata, artifact hashes, and promotion governance
- Ground-truth feedback and verification tracking
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


def _utcnow() -> datetime:
    return datetime.now(UTC)


class DriftStatus(StrEnum):
    """Categorical status of feature or score drift relative to reference baseline."""
    STABLE = "STABLE"                      # PSI < 0.10, KS p >= 0.01 or D < 0.15
    WARNING = "WARNING"                    # 0.10 <= PSI < 0.25, moderate shift
    CRITICAL = "CRITICAL"                  # PSI >= 0.25, severe shift requiring triage
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"  # Sample size N < min_sample_size (e.g. 30)


class DriftMetricType(StrEnum):
    """Supported statistical drift metric methodologies."""
    PSI = "PSI"                          # Population Stability Index
    KS = "KS"                            # Two-sample Kolmogorov-Smirnov test (D-statistic)
    WASSERSTEIN = "WASSERSTEIN"          # First Wasserstein (Earth Mover's) Distance
    TVD = "TVD"                          # Total Variation Distance for categorical features


class MonitoringAlertSeverity(StrEnum):
    """Severity classification for operational and data drift alerts."""
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class MonitoringAlertType(StrEnum):
    """Operational anomaly and telemetry alert types."""
    FEATURE_DRIFT = "FEATURE_DRIFT"              # Sustained distribution shift on input features
    SCORE_DRIFT = "SCORE_DRIFT"                  # Deviation in continuous anomaly score profile
    ANOMALY_RATE_SPIKE = "ANOMALY_RATE_SPIKE"    # Sudden jump in percentage of flows flagged as anomalies
    VALIDATION_SPIKE = "VALIDATION_SPIKE"        # Excessive schema rejections or policy violations
    LATENCY_DEGRADATION = "LATENCY_DEGRADATION"  # Inference latency exceeds operational SLA
    VERSION_MISMATCH = "VERSION_MISMATCH"        # Mismatch between model/preprocessor version or hash
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"      # Scoring batch too small for statistical validity


class MonitoringAlertStatus(StrEnum):
    """Lifecycle state machine for operational monitoring alerts."""
    ACTIVE = "ACTIVE"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    SUPPRESSED = "SUPPRESSED"


class ModelLifecycleStatus(StrEnum):
    """Controlled lifecycle states in the model registry."""
    CANDIDATE = "CANDIDATE"      # Newly evaluated candidate model under independent audit
    VALIDATED = "VALIDATED"      # Passed causal policy and independent verification
    PRODUCTION = "PRODUCTION"    # Deployed active inference engine
    ARCHIVED = "ARCHIVED"        # Previously deployed model replaced by verified promotion
    RETIRED = "RETIRED"          # Superseded or deprecated model artifact


class AnalystDisposition(StrEnum):
    """Analyst investigation verdict for an alert or scored flow."""
    CONFIRMED_THREAT = "CONFIRMED_THREAT"            # Verified malicious or policy-violating activity
    BENIGN_FALSE_POSITIVE = "BENIGN_FALSE_POSITIVE"  # Normal operational traffic falsely flagged
    SUSPICIOUS_UNVERIFIED = "SUSPICIOUS_UNVERIFIED"  # Inconclusive / pending deeper forensics
    POLICY_VIOLATION = "POLICY_VIOLATION"            # Unauthorized network use without malicious intent


@dataclass(frozen=True)
class FeatureDriftResult:
    """Detailed statistical comparison of an individual feature against baseline."""
    feature: str
    metric_type: DriftMetricType
    metric_value: float
    threshold_warning: float
    threshold_critical: float
    status: DriftStatus
    p_value: float | None = None
    baseline_mean: float = 0.0
    current_mean: float = 0.0
    baseline_std: float = 0.0
    current_std: float = 0.0
    sample_size: int = 0
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["metric_type"] = self.metric_type.value
        d["status"] = self.status.value
        return d


@dataclass(frozen=True)
class FeatureSummaryMetric:
    """Empirical distribution parameters for an input feature in a batch."""
    feature: str
    count: int
    mean: float
    std: float
    min_val: float
    max_val: float
    missing_count: int
    invalid_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BatchMonitoringRecord:
    """Aggregated batch telemetry capturing operational and inference profile."""
    batch_id: str
    timestamp: datetime = field(default_factory=_utcnow)
    model_name: str = "OptunaTuned_XGBoost"
    model_version: str = "1.0.0"
    artifact_hash: str = ""
    decision_threshold: float = 0.5
    source: str = "batch_upload"
    flow_count: int = 0
    anomaly_count: int = 0
    anomaly_rate: float = 0.0
    mean_score: float = 0.0
    p95_score: float = 0.0
    latency_ms: float = 0.0
    validation_failure_count: int = 0
    severity_counts: dict[str, int] = field(default_factory=dict)
    feature_metrics: dict[str, dict[str, Any]] = field(default_factory=dict)
    score_histogram: list[int] = field(default_factory=list)
    is_demo: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "timestamp": self.timestamp.isoformat(),
            "model_name": self.model_name,
            "model_version": self.model_version,
            "artifact_hash": self.artifact_hash,
            "decision_threshold": self.decision_threshold,
            "source": self.source,
            "flow_count": self.flow_count,
            "anomaly_count": self.anomaly_count,
            "anomaly_rate": round(self.anomaly_rate, 4),
            "mean_score": round(self.mean_score, 6),
            "p95_score": round(self.p95_score, 6),
            "latency_ms": round(self.latency_ms, 2),
            "validation_failure_count": self.validation_failure_count,
            "severity_counts": self.severity_counts,
            "feature_metrics": self.feature_metrics,
            "score_histogram": self.score_histogram,
            "is_demo": self.is_demo,
        }


@dataclass
class GroundTruthRecord:
    """Explicitly verified ground-truth outcome tracked separately from prediction."""
    id: str
    timestamp: datetime = field(default_factory=_utcnow)
    flow_identifier: str = ""
    model_score: float = 0.0
    model_predicted_anomaly: bool = False
    analyst_disposition: AnalystDisposition = AnalystDisposition.SUSPICIOUS_UNVERIFIED
    verified_ground_truth: int | None = None  # 1 = Attack, 0 = Normal, None = Unverified
    verification_source: str = "forensics"
    verified_by: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "flow_identifier": self.flow_identifier,
            "model_score": round(self.model_score, 6),
            "model_predicted_anomaly": self.model_predicted_anomaly,
            "analyst_disposition": self.analyst_disposition.value,
            "verified_ground_truth": self.verified_ground_truth,
            "verification_source": self.verification_source,
            "verified_by": self.verified_by,
            "notes": self.notes,
        }
