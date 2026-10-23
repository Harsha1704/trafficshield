"""
Unit Tests for CICIDS2017 Adapter
==================================
Milestone 10 — TrafficShield

Validates:
1. Column whitespace cleaning.
2. Handling of non-finite values (Infinity/NaN).
3. Label normalization (BENIGN -> normal, DoS Hulk -> dos_hulk).
4. Strict forward-only extraction from CSV streams.
5. Ingestion of synthetic fixtures with rate derivation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ingestion.adapters.cicids2017 import CICIDS2017Adapter


@pytest.fixture
def adapter() -> CICIDS2017Adapter:
    return CICIDS2017Adapter(chunk_size=1000)


def test_clean_column_names(adapter: CICIDS2017Adapter) -> None:
    """Verify leading/trailing spaces are cleanly stripped from column names."""
    raw_df = pd.DataFrame({
        " Destination Port": [80],
        " Flow Duration ": [1000],
        "Label": ["BENIGN"],
    })
    clean_df = adapter.clean_column_names(raw_df)
    assert list(clean_df.columns) == ["Destination Port", "Flow Duration", "Label"]


def test_sanitize_values(adapter: CICIDS2017Adapter) -> None:
    """Verify string and float infinities are sanitized to NaN."""
    df = pd.DataFrame({
        "Flow Bytes/s": ["Infinity", "-inf", 1234.5],
        "Flow Packets/s": [np.inf, -np.inf, 45.0],
    })
    sanitized = adapter.sanitize_values(df)
    assert pd.isna(sanitized["Flow Bytes/s"].iloc[0])
    assert pd.isna(sanitized["Flow Bytes/s"].iloc[1])
    assert sanitized["Flow Bytes/s"].iloc[2] == 1234.5
    assert pd.isna(sanitized["Flow Packets/s"].iloc[0])
    assert pd.isna(sanitized["Flow Packets/s"].iloc[1])
    assert sanitized["Flow Packets/s"].iloc[2] == 45.0


def test_normalize_label(adapter: CICIDS2017Adapter) -> None:
    """Verify label string standardisation."""
    cat, is_att = adapter.normalize_label("BENIGN")
    assert cat == "normal"
    assert is_att == 0

    cat, is_att = adapter.normalize_label("DoS Hulk")
    assert cat == "dos_hulk"
    assert is_att == 1

    cat, is_att = adapter.normalize_label("PortScan ")
    assert cat == "portscan"
    assert is_att == 1


def test_synthetic_stream_ingestion(adapter: CICIDS2017Adapter, tmp_path) -> None:
    """Verify end-to-end ingestion on a realistic synthetic stream."""
    synth_df = adapter.generate_synthetic_cicids_dataframe(n_samples=200, anomaly_ratio=0.2, random_seed=42)
    csv_file = tmp_path / "test_cicids.csv"
    synth_df.to_csv(csv_file, index=False)

    feat_df, lbl_s, meta_df = adapter.load_unidirectional_dataframe(
        filepaths=[csv_file],
        max_rows=200,
        include_rates=True,
    )

    assert len(feat_df) == 200
    assert len(lbl_s) == 200
    assert len(meta_df) == 200

    # Ensure NO reverse-direction columns are in feat_df
    for col in feat_df.columns:
        assert "bwd" not in col.lower()
        assert "backward" not in col.lower()
        assert "label" not in col.lower()

    # Verify forward rate derivations
    assert "packet_rate" in feat_df.columns
    assert "byte_rate" in feat_df.columns
    assert "bytes_per_packet" in feat_df.columns

    # Verify attack label separation
    assert int(meta_df["is_attack"].sum()) == 40  # 20% of 200
    assert "normal" in lbl_s.values
    assert "dos_hulk" in lbl_s.values or "portscan" in lbl_s.values
