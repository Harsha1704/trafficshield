"""
Unit Tests for UNSW-NB15 Unidirectional Feature Policy
======================================================
Milestone 7 — TrafficShield
"""
from __future__ import annotations

from pathlib import Path

import pytest

from features.policy import FieldRole, PolicyViolationError
from ingestion.adapters.unsw_nb15_policy import (
    UNSW_NB15_SPECS,
    UNSWFeatureDirectionality,
    audit_unsw_feature_columns,
    export_unsw_policy_json,
    export_unsw_policy_markdown,
    get_unsw_spec_by_raw,
)


def test_unsw_policy_complete_49_columns():
    """Verify all 49 columns from UNSW-NB15 are explicitly catalogued."""
    assert len(UNSW_NB15_SPECS) == 49
    indices = [s.index for s in UNSW_NB15_SPECS]
    assert indices == list(range(1, 50))

    # All specs must have non-empty metadata
    for spec in UNSW_NB15_SPECS:
        assert spec.raw_name
        assert spec.normalized_name
        assert isinstance(spec.directionality, UNSWFeatureDirectionality)
        assert isinstance(spec.field_role, FieldRole)
        assert len(spec.description) > 0
        assert len(spec.rationale) > 0


def test_reverse_direction_features_are_strictly_forbidden():
    """Verify destination-to-source return features are categorized as REVERSE_DIRECTION and FORBIDDEN."""
    reverse_raw_names = [
        "dbytes", "dttl", "dloss", "Dload", "Dpkts", "dwin",
        "dtcpb", "dmeansz", "res_bdy_len", "Djit", "Dintpkt",
        "tcprtt", "synack",
    ]
    for rname in reverse_raw_names:
        spec = get_unsw_spec_by_raw(rname)
        assert spec is not None, f"Spec missing for {rname}"
        assert spec.directionality == UNSWFeatureDirectionality.REVERSE_DIRECTION, (
            f"{rname} should be REVERSE_DIRECTION"
        )
        assert spec.field_role == FieldRole.FORBIDDEN
        assert spec.is_model_feature is False


def test_bidirectional_and_future_features_are_forbidden():
    """Verify state machine, RTT response, and server validation features are FORBIDDEN."""
    bidi_raw_names = ["state", "sloss", "trans_depth", "ackdat", "ct_state_ttl", "is_ftp_login"]
    for bname in bidi_raw_names:
        spec = get_unsw_spec_by_raw(bname)
        assert spec is not None, f"Spec missing for {bname}"
        assert spec.directionality == UNSWFeatureDirectionality.BIDIRECTIONAL_OR_FUTURE_DEPENDENT
        assert spec.field_role == FieldRole.FORBIDDEN
        assert spec.is_model_feature is False


def test_labels_and_identifiers_are_excluded():
    """Verify ground-truth labels and raw network identifiers are never model features."""
    targets = ["attack_cat", "Label"]
    for t in targets:
        spec = get_unsw_spec_by_raw(t)
        assert spec is not None
        assert spec.field_role == FieldRole.LABEL
        assert spec.is_model_feature is False

    identifiers = ["srcip", "dstip", "stcpb", "Stime", "Ltime"]
    for ident in identifiers:
        spec = get_unsw_spec_by_raw(ident)
        assert spec is not None
        assert spec.field_role in (FieldRole.IDENTIFIER, FieldRole.TIMESTAMP)
        assert spec.is_model_feature is False


def test_audit_unsw_feature_columns_detects_violations():
    """Verify policy audit flags reverse, bidirectional, and label columns."""
    # 1. Clean forward observable columns should pass
    clean_cols = ["duration_seconds", "fwd_packets", "fwd_bytes", "sttl", "swin", "sjit"]
    audit = audit_unsw_feature_columns(clean_cols)
    assert audit.is_clean
    assert set(audit.eligible_features) == set(clean_cols)

    # 2. Reverse direction column should raise PolicyViolationError
    with pytest.raises(PolicyViolationError) as exc_rev:
        audit_unsw_feature_columns(["fwd_packets", "dbytes"])
    assert "dbytes" in str(exc_rev.value)
    assert "reverse_direction" in str(exc_rev.value)

    # 3. Label column should raise PolicyViolationError
    with pytest.raises(PolicyViolationError) as exc_lbl:
        audit_unsw_feature_columns(["fwd_packets", "attack_cat"])
    assert "attack_cat" in str(exc_lbl.value)

    # 4. Unknown column should raise PolicyViolationError
    with pytest.raises(PolicyViolationError) as exc_unk:
        audit_unsw_feature_columns(["fwd_packets", "unregistered_bogus_col"])
    assert "unregistered_bogus_col" in str(exc_unk.value)


def test_policy_export_json_and_markdown(tmp_path: Path):
    """Verify policy export to JSON and Markdown documents."""
    json_path = tmp_path / "policy.json"
    md_path = tmp_path / "policy.md"

    export_unsw_policy_json(json_path)
    export_unsw_policy_markdown(md_path)

    assert json_path.exists()
    assert md_path.exists()
    assert "UNSW-NB15" in json_path.read_text(encoding="utf-8")
    assert "forward_observable" in md_path.read_text(encoding="utf-8")
