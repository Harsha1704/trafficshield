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
    get_disjoint_unsw_policy_categories,
    get_eligible_unsw_model_features,
    get_strict_causal_unsw_model_features,
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


def test_unsw_policy_exact_disjoint_partition():
    """Verify that all 49 columns form an exact disjoint partition summing to 49."""
    cats = get_disjoint_unsw_policy_categories()

    # Exact expected counts
    assert len(cats["forward_observable_numeric"]) == 19
    assert len(cats["forward_observable_metadata"]) == 4
    assert len(cats["reverse_direction"]) == 13
    assert len(cats["bidirectional_or_future_dependent"]) == 6
    assert len(cats["identifier_or_grouping_only"]) == 7

    total = sum(len(v) for v in cats.values())
    assert total == 49

    # Check pairwise disjointness (no overlapping columns)
    all_raws = []
    for _cat_name, col_list in cats.items():
        for col in col_list:
            assert col not in all_raws, f"Column '{col}' appears in multiple categories!"
            all_raws.append(col)

    assert len(all_raws) == 49
    # All 49 raw column names from specs must be in the partition
    spec_raws = [s.raw_name for s in UNSW_NB15_SPECS]
    assert set(all_raws) == set(spec_raws)


def test_causal_observability_distinction():
    """Verify distinction between 10 per-flow causal features and 9 batch aggregates."""
    causal_feats = get_strict_causal_unsw_model_features()
    assert len(causal_feats) == 10

    # The 10 intrinsic per-flow forward features
    expected_causal = {
        "duration_seconds", "fwd_bytes", "sttl", "sload", "fwd_packets",
        "swin", "smeansz", "sjit", "sintpkt", "is_sm_ips_ports",
    }
    assert set(causal_feats) == expected_causal

    all_eligible = get_eligible_unsw_model_features(strict_causal_only=False)
    assert len(all_eligible) == 19

    strict_eligible = get_eligible_unsw_model_features(strict_causal_only=True)
    assert strict_eligible == causal_feats

    # The 9 precomputed batch-window features (ct_*) must have is_causal == False
    batch_window_feats = [
        s for s in UNSW_NB15_SPECS if s.is_model_feature and not s.is_causal
    ]
    assert len(batch_window_feats) == 9
    for s in batch_window_feats:
        assert s.raw_name.startswith("ct_")
        assert len(s.causal_notes) > 0
        assert "lookahead" in s.causal_notes.lower() or "batch" in s.causal_notes.lower()

