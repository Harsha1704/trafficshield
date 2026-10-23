"""
Unit Tests for Cross-Dataset Compatibility Engine
=================================================
Milestone 10 — TrafficShield

Validates:
1. Feature compatibility matrix completeness.
2. Transfer feasibility verification rejects models with missing features (sttl, is_sm_ips_ports).
3. Common forward-observable subspace feature list validity.
4. Distribution shift metric computation (KS and Wasserstein).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from evaluation.cross_dataset import (
    COMMON_CAUSAL_FEATURES,
    build_feature_compatibility_matrix,
    compute_distribution_drift,
    verify_direct_transfer_feasibility,
)


def test_build_feature_compatibility_matrix() -> None:
    """Verify matrix contains records from both datasets with required fields."""
    records = build_feature_compatibility_matrix()
    assert len(records) > 80

    sources = {r.source_dataset for r in records}
    assert "UNSW-NB15" in sources
    assert "CICIDS2017" in sources

    for r in records:
        assert r.forward_only in ("Yes", "No")
        assert r.requires_reverse_or_bidirectional in ("Yes", "No")
        assert r.status in (
            "ACCEPTED",
            "REJECTED_REVERSE",
            "REJECTED_BIDIRECTIONAL",
            "REJECTED_LABEL",
            "EXCLUDED_IDENTIFIER",
            "EXCLUDED_METADATA",
        )


def test_verify_direct_transfer_feasibility_rejected() -> None:
    """Verify missing sttl and is_sm_ips_ports causes DIRECT_TRANSFER_UNSUPPORTED."""
    prod_features = [
        "duration_seconds",
        "fwd_bytes",
        "sttl",
        "sload",
        "fwd_packets",
        "swin",
        "smeansz",
        "sjit",
        "sintpkt",
        "packet_rate",
        "byte_rate",
        "bytes_per_packet",
        "is_sm_ips_ports",
    ]
    # Candidate features without sttl and is_sm_ips_ports
    candidate_features = [
        "duration_seconds",
        "fwd_bytes",
        "sload",
        "fwd_packets",
        "swin",
        "smeansz",
        "sjit",
        "sintpkt",
        "packet_rate",
        "byte_rate",
        "bytes_per_packet",
    ]

    res = verify_direct_transfer_feasibility(prod_features, candidate_features)
    assert res["is_supported"] is False
    assert res["verdict"] == "DIRECT_TRANSFER_UNSUPPORTED"
    assert "sttl" in res["missing_features"]
    assert "is_sm_ips_ports" in res["missing_features"]
    assert "sttl" in res["scientific_rationale"]


def test_verify_direct_transfer_feasibility_supported() -> None:
    """Verify complete feature overlap passes as SUPPORTED."""
    features = ["duration_seconds", "fwd_bytes", "fwd_packets"]
    res = verify_direct_transfer_feasibility(features, features)
    assert res["is_supported"] is True
    assert res["verdict"] == "SUPPORTED"
    assert len(res["missing_features"]) == 0


def test_common_causal_features() -> None:
    """Verify common features list is strictly forward-observable and non-empty."""
    assert len(COMMON_CAUSAL_FEATURES) == 9
    for f in COMMON_CAUSAL_FEATURES:
        assert "bwd" not in f.lower()
        assert "reverse" not in f.lower()


def test_compute_distribution_drift() -> None:
    """Verify KS and Wasserstein distribution drift calculations."""
    rng = np.random.default_rng(42)
    df1 = pd.DataFrame({
        "fwd_bytes": rng.normal(1000, 100, 500),
        "fwd_packets": rng.poisson(10, 500),
    })
    df2 = pd.DataFrame({
        "fwd_bytes": rng.normal(5000, 200, 500),  # shifted
        "fwd_packets": rng.poisson(10, 500),       # identical
    })

    drift = compute_distribution_drift(df1, df2, ["fwd_bytes", "fwd_packets"])
    assert len(drift) == 2

    bytes_drift = next(d for d in drift if d["feature"] == "fwd_bytes")
    pkts_drift = next(d for d in drift if d["feature"] == "fwd_packets")

    assert bytes_drift["ks_statistic"] > 0.8
    assert bytes_drift["drift_severity"] == "HIGH"
    assert pkts_drift["ks_statistic"] < 0.2
