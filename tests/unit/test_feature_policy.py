"""
Unit Tests for Feature Eligibility Policy
==========================================
"""
import pytest

from features.policy import (
    FEATURE_POLICY_VERSION,
    FieldRole,
    PolicyViolationError,
    audit_columns,
    get_eligible_features,
    get_evaluation_labels,
    get_field_spec,
    get_forbidden_features,
    is_eligible_feature,
    validate_feature_columns,
)


def test_policy_version():
    assert FEATURE_POLICY_VERSION == "1.0"


def test_eligible_features_allowlist():
    eligible = get_eligible_features()
    assert len(eligible) > 0
    assert "fwd_packets" in eligible
    assert "fwd_bytes" in eligible
    assert "duration_seconds" in eligible
    assert "packet_rate" in eligible
    assert "byte_rate" in eligible
    assert "sin_hour" in eligible
    assert "cos_hour" in eligible

    for feat in eligible:
        assert is_eligible_feature(feat) is True
        spec = get_field_spec(feat)
        assert spec is not None
        assert spec.role == FieldRole.FEATURE
        assert spec.description != ""
        assert spec.rationale != ""


def test_forbidden_reverse_features():
    forbidden = get_forbidden_features()
    assert "bwd_packets" in forbidden
    assert "bwd_bytes" in forbidden
    assert "bwd_header_length" in forbidden
    assert "rtt_ms" in forbidden
    assert "response_latency_ms" in forbidden
    assert "session_complete" in forbidden
    assert "fwd_bwd_packet_ratio" in forbidden
    assert "fwd_bwd_byte_ratio" in forbidden

    for col in forbidden:
        assert is_eligible_feature(col) is False
        spec = get_field_spec(col)
        assert spec is not None
        assert spec.role == FieldRole.FORBIDDEN


def test_evaluation_labels_excluded():
    labels = get_evaluation_labels()
    assert "eval_label" in labels
    assert "eval_label_raw" in labels
    assert "is_attack" in labels
    assert "class" in labels
    assert "label" in labels
    assert "attack_cat" in labels

    for col in labels:
        assert is_eligible_feature(col) is False
        spec = get_field_spec(col)
        assert spec is not None
        assert spec.role == FieldRole.LABEL


def test_identifiers_and_timestamps():
    for ident in ("record_id", "src_ip", "dst_ip"):
        assert is_eligible_feature(ident) is False
        spec = get_field_spec(ident)
        assert spec is not None
        assert spec.role == FieldRole.IDENTIFIER

    for ts in ("flow_end_ts", "ingest_ts"):
        assert is_eligible_feature(ts) is False
        spec = get_field_spec(ts)
        assert spec is not None
        assert spec.role == FieldRole.TIMESTAMP


def test_audit_columns_clean():
    clean_cols = ["fwd_packets", "fwd_bytes", "duration_seconds", "packet_rate"]
    audit = audit_columns(clean_cols)
    assert audit.is_clean is True
    assert audit.eligible_features == clean_cols
    assert len(audit.forbidden_violations) == 0
    assert len(audit.label_violations) == 0
    assert len(audit.excluded_columns) == 0


def test_audit_columns_with_violations():
    dirty_cols = [
        "fwd_packets",
        "bwd_packets",      # forbidden
        "class",            # label
        "src_ip",           # identifier
        "arbitrary_column", # unregistered
    ]
    audit = audit_columns(dirty_cols)
    assert audit.is_clean is False
    assert audit.eligible_features == ["fwd_packets"]
    assert "bwd_packets" in audit.forbidden_violations
    assert "class" in audit.label_violations
    assert "src_ip" in audit.excluded_columns
    assert "arbitrary_column" in audit.excluded_columns


def test_validate_feature_columns_strict_rejects_forbidden():
    with pytest.raises(PolicyViolationError) as exc_info:
        validate_feature_columns(["fwd_packets", "bwd_packets"], strict=True)
    assert "Forbidden reverse-dependent" in str(exc_info.value)


def test_validate_feature_columns_strict_rejects_label():
    with pytest.raises(PolicyViolationError) as exc_info:
        validate_feature_columns(["fwd_packets", "eval_label"], strict=True)
    assert "Evaluation label columns cannot be features" in str(exc_info.value)


def test_validate_feature_columns_strict_rejects_unregistered():
    with pytest.raises(PolicyViolationError) as exc_info:
        validate_feature_columns(["fwd_packets", "unknown_noise"], strict=True)
    assert "non-feature columns" in str(exc_info.value)


def test_validate_feature_columns_non_strict_filters():
    cols = ["fwd_packets", "src_ip", "unknown_col", "fwd_bytes"]
    result = validate_feature_columns(cols, strict=False)
    assert result == ["fwd_packets", "fwd_bytes"]
