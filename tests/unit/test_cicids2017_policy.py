"""
Unit Tests for CICIDS2017 Unidirectional Policy
================================================
Milestone 10 — TrafficShield

Validates:
1. Classification of all CICFlowMeter fields against unidirectional monitoring principles.
2. Rejection of backward/return metrics (Total Backward Packets, Bwd IAT, etc.).
3. Rejection of bidirectional session metrics (Flow Bytes/s, Packet Length Mean).
4. Isolation of ground-truth target label (Label).
5. Availability timing annotations (packet_arrival, flow_prefix, flow_completion).
"""
from __future__ import annotations

from features.policy import FieldRole
from ingestion.adapters.cicids2017_policy import (
    CICIDS_2017_SPECS,
    AvailabilityTiming,
    CICIDSFeatureDirectionality,
    audit_cicids2017_columns,
    get_eligible_cicids_model_features,
)


def test_cicids_specs_completeness() -> None:
    """Verify that all mapped fields have valid directionality and roles."""
    assert len(CICIDS_2017_SPECS) >= 50
    for name, spec in CICIDS_2017_SPECS.items():
        assert spec.raw_name == name
        assert isinstance(spec.directionality, CICIDSFeatureDirectionality)
        assert isinstance(spec.field_role, FieldRole)
        assert isinstance(spec.availability_timing, AvailabilityTiming)


def test_audit_clean_forward_features() -> None:
    """Verify clean forward-only columns pass policy audit."""
    clean_cols = [
        " Destination Port",
        " Total Fwd Packets",
        "Total Length of Fwd Packets",
        " Fwd Packet Length Mean",
        " Fwd IAT Mean",
        "Init_Win_bytes_forward",
    ]
    res = audit_cicids2017_columns(clean_cols)
    assert res.is_clean is True
    assert len(res.forbidden_violations) == 0
    assert len(res.label_violations) == 0
    assert "Destination Port" in res.excluded_columns
    assert "Total Fwd Packets" in res.eligible_features


def test_audit_rejects_backward_metrics() -> None:
    """Verify reverse-direction columns are caught as forbidden violations."""
    dirty_cols = [
        " Total Fwd Packets",
        " Total Backward Packets",
        " Total Length of Bwd Packets",
        " Bwd IAT Mean",
        "Down/Up Ratio",
    ]
    res = audit_cicids2017_columns(dirty_cols)
    assert res.is_clean is False
    assert "Total Backward Packets" in res.forbidden_violations
    assert "Total Length of Bwd Packets" in res.forbidden_violations
    assert "Bwd IAT Mean" in res.forbidden_violations
    assert "Down/Up Ratio" in res.forbidden_violations


def test_audit_rejects_bidirectional_aggregates() -> None:
    """Verify bidirectional session aggregates are caught as forbidden violations."""
    bidi_cols = [
        " Total Fwd Packets",
        "Flow Bytes/s",
        " Flow Packets/s",
        " Flow IAT Mean",
        " Packet Length Mean",
        " SYN Flag Count",
    ]
    res = audit_cicids2017_columns(bidi_cols)
    assert res.is_clean is False
    assert "Flow Bytes/s" in res.forbidden_violations
    assert "Flow Packets/s" in res.forbidden_violations
    assert "Flow IAT Mean" in res.forbidden_violations
    assert "Packet Length Mean" in res.forbidden_violations
    assert "SYN Flag Count" in res.forbidden_violations


def test_audit_rejects_label_leakage() -> None:
    """Verify target label is strictly caught as a label violation."""
    leaked_cols = [" Total Fwd Packets", " Label"]
    res = audit_cicids2017_columns(leaked_cols)
    assert res.is_clean is False
    assert "Label" in res.label_violations


def test_get_eligible_model_features() -> None:
    """Verify eligible features list contains only forward-observable fields."""
    eligible = get_eligible_cicids_model_features()
    assert len(eligible) > 0
    for col in eligible:
        spec = CICIDS_2017_SPECS[col]
        assert spec.directionality == CICIDSFeatureDirectionality.FORWARD_OBSERVABLE
        assert spec.field_role == FieldRole.FEATURE
        assert "bwd" not in col.lower()
        assert "backward" not in col.lower()
