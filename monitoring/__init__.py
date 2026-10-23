"""
TrafficShield Monitoring Package
=================================
Milestone 12 — Intelligent Monitoring, Drift Detection & Model Lifecycle
"""
from monitoring.alert_manager import MonitoringAlertManager
from monitoring.baseline import load_reference_baseline
from monitoring.drift_engine import (
    calculate_ks,
    calculate_psi,
    calculate_wasserstein,
    evaluate_feature_drift,
    evaluate_score_drift,
)
from monitoring.feedback import get_operational_evaluation, submit_ground_truth_feedback
from monitoring.registry import ModelRegistryManager
from monitoring.schema import (
    AnalystDisposition,
    BatchMonitoringRecord,
    DriftMetricType,
    DriftStatus,
    FeatureDriftResult,
    ModelLifecycleStatus,
    MonitoringAlertSeverity,
    MonitoringAlertStatus,
    MonitoringAlertType,
)
from monitoring.service import MonitoringService

__all__ = [
    "AnalystDisposition",
    "BatchMonitoringRecord",
    "DriftMetricType",
    "DriftStatus",
    "FeatureDriftResult",
    "ModelLifecycleStatus",
    "ModelRegistryManager",
    "MonitoringAlertManager",
    "MonitoringAlertSeverity",
    "MonitoringAlertStatus",
    "MonitoringAlertType",
    "MonitoringService",
    "calculate_ks",
    "calculate_psi",
    "calculate_wasserstein",
    "evaluate_feature_drift",
    "evaluate_score_drift",
    "get_operational_evaluation",
    "load_reference_baseline",
    "submit_ground_truth_feedback",
]
