"""
TrafficShield Features Package
==============================
Version: 1.0 (Milestone 3)
"""
from features.engineering import (
    FeatureEngineer,
    categorize_port,
    categorize_protocol,
    extract_features_and_labels,
    parse_tcp_flags,
)
from features.policy import (
    FEATURE_POLICY_VERSION,
    DataType,
    FeatureAuditResult,
    FieldRole,
    FieldSpec,
    PolicyViolationError,
    audit_columns,
    get_eligible_features,
    get_evaluation_labels,
    get_field_spec,
    get_forbidden_features,
    is_eligible_feature,
    validate_feature_columns,
)
from features.temporal import TemporalFeatureEngineer

__all__ = [
    "FEATURE_POLICY_VERSION",
    "FieldRole",
    "DataType",
    "FieldSpec",
    "FeatureAuditResult",
    "PolicyViolationError",
    "get_field_spec",
    "is_eligible_feature",
    "get_eligible_features",
    "get_forbidden_features",
    "get_evaluation_labels",
    "audit_columns",
    "validate_feature_columns",
    "FeatureEngineer",
    "TemporalFeatureEngineer",
    "parse_tcp_flags",
    "categorize_port",
    "categorize_protocol",
    "extract_features_and_labels",
]
