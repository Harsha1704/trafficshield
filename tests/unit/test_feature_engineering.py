"""
Unit Tests for One-Way Feature Engineering
===========================================
"""
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from features.engineering import (
    FeatureEngineer,
    categorize_port,
    categorize_protocol,
    extract_features_and_labels,
    parse_tcp_flags,
)
from ingestion.schema.canonical_flow import CanonicalFlow


def test_categorize_protocol():
    assert categorize_protocol("TCP") == "TCP"
    assert categorize_protocol("tcp") == "TCP"
    assert categorize_protocol("6") == "TCP"
    assert categorize_protocol("UDP") == "UDP"
    assert categorize_protocol("17") == "UDP"
    assert categorize_protocol("ICMP") == "ICMP"
    assert categorize_protocol("1") == "ICMP"
    assert categorize_protocol("GRE") == "OTHER"
    assert categorize_protocol(None) == "OTHER"


def test_categorize_port():
    assert categorize_port(80) == "well_known"
    assert categorize_port(443) == "well_known"
    assert categorize_port(0) == "well_known"
    assert categorize_port(1023) == "well_known"
    assert categorize_port(1024) == "registered"
    assert categorize_port(8080) == "registered"
    assert categorize_port(49151) == "registered"
    assert categorize_port(49152) == "ephemeral"
    assert categorize_port(65535) == "ephemeral"
    assert categorize_port(70000) == "unknown"
    assert categorize_port(-1) == "unknown"
    assert categorize_port(None) == "unknown"


def test_parse_tcp_flags():
    flags = parse_tcp_flags(".A..S.")
    assert flags["has_syn"] == 1
    assert flags["has_ack"] == 1
    assert flags["has_fin"] == 0
    assert flags["has_rst"] == 0
    assert flags["has_psh"] == 0
    assert flags["has_urg"] == 0

    flags_all = parse_tcp_flags("FSRPAU")
    assert all(v == 1 for v in flags_all.values())

    flags_empty = parse_tcp_flags("")
    assert all(v == 0 for v in flags_empty.values())

    flags_none = parse_tcp_flags(None)
    assert all(v == 0 for v in flags_none.values())


def test_feature_engineer_empty():
    fe = FeatureEngineer()
    res = fe.transform_dataframe(pd.DataFrame())
    assert res.empty


def test_feature_engineer_numerical_rates_and_division_guards():
    fe = FeatureEngineer()
    df = pd.DataFrame([
        # Row 1: normal flow with positive duration
        {"fwd_packets": 10, "fwd_bytes": 1000, "duration_seconds": 2.0},
        # Row 2: zero duration (instantaneous single packet or syn flood)
        {"fwd_packets": 1, "fwd_bytes": 60, "duration_seconds": 0.0},
        # Row 3: negative duration or packets (must clamp cleanly)
        {"fwd_packets": -5, "fwd_bytes": -100, "duration_seconds": -1.0},
        # Row 4: missing fields
        {"duration_seconds": None},
    ])
    out = fe.transform_dataframe(df)

    # Row 1
    assert out.loc[0, "packet_rate"] == 5.0
    assert out.loc[0, "byte_rate"] == 500.0
    assert out.loc[0, "bytes_per_packet"] == 100.0

    # Row 2 (zero duration: rates default to packet count, no inf)
    assert out.loc[1, "packet_rate"] == 1.0
    assert out.loc[1, "byte_rate"] == 60.0
    assert out.loc[1, "bytes_per_packet"] == 60.0
    assert not np.isinf(out.loc[1, "packet_rate"])

    # Row 3 (negative inputs clamped to 0)
    assert out.loc[2, "fwd_packets"] == 0.0
    assert out.loc[2, "fwd_bytes"] == 0.0
    assert out.loc[2, "duration_seconds"] == 0.0

    # Row 4 (missing fields handled cleanly)
    assert out.loc[3, "fwd_packets"] == 0.0
    assert out.loc[3, "fwd_bytes"] == 0.0
    assert out.loc[3, "duration_seconds"] == 0.0

    # Verify log transforms exist and are finite
    assert "log_fwd_packets" in out.columns
    assert "log_fwd_bytes" in out.columns
    assert np.all(np.isfinite(out["log_fwd_packets"]))
    assert np.all(np.isfinite(out["log_fwd_bytes"]))


def test_feature_engineer_cyclic_temporal_features():
    fe = FeatureEngineer()
    df = pd.DataFrame([
        {"flow_end_ts": "2016-03-15T00:00:00+00:00"}, # Midnight Tuesday (dow=1)
        {"flow_end_ts": "2016-03-15T06:00:00+00:00"}, # 06:00
        {"flow_end_ts": "2016-03-15T12:00:00+00:00"}, # Noon
        {"flow_end_ts": "2016-03-19T18:00:00+00:00"}, # Saturday (dow=5, weekend)
    ])
    out = fe.transform_dataframe(df)

    assert out.loc[0, "hour_of_day"] == 0
    assert out.loc[0, "is_weekend"] == 0
    assert pytest.approx(out.loc[0, "sin_hour"], abs=1e-5) == 0.0
    assert pytest.approx(out.loc[0, "cos_hour"], abs=1e-5) == 1.0

    assert out.loc[1, "hour_of_day"] == 6
    assert pytest.approx(out.loc[1, "sin_hour"], abs=1e-5) == 1.0

    assert out.loc[3, "is_weekend"] == 1

    # Bounds check
    assert (out["sin_hour"] >= -1.0).all() and (out["sin_hour"] <= 1.0).all()
    assert (out["cos_hour"] >= -1.0).all() and (out["cos_hour"] <= 1.0).all()


def test_feature_engineer_canonical_flows():
    flow = CanonicalFlow(
        record_id="550e8400-e29b-41d4-a716-446655440000",
        flow_end_ts=datetime(2016, 4, 1, 10, 30, tzinfo=UTC),
        src_ip="192.0.2.1",
        dst_ip="198.51.100.1",
        src_port=54321,
        dst_port=80,
        protocol_name="TCP",
        fwd_packets=5,
        fwd_bytes=500,
        duration_seconds=1.0,
        tcp_flags_raw=".A..S.",
        eval_label="background",
    )
    fe = FeatureEngineer()
    out = fe.transform_flows([flow])

    assert len(out) == 1
    assert out.loc[0, "fwd_packets"] == 5.0
    assert out.loc[0, "fwd_bytes"] == 500.0
    assert out.loc[0, "dst_port_category"] == "well_known"
    assert out.loc[0, "src_port_category"] == "ephemeral"
    assert out.loc[0, "protocol_category"] == "TCP"
    assert out.loc[0, "has_syn"] == 1
    assert out.loc[0, "has_ack"] == 1


def test_extract_features_and_labels_isolates_labels():
    df = pd.DataFrame([
        {
            "record_id": "flow-1",
            "src_ip": "10.0.0.1",
            "dst_ip": "10.0.0.2",
            "flow_end_ts": "2016-03-01T12:00:00+00:00",
            "fwd_packets": 10,
            "fwd_bytes": 1000,
            "duration_seconds": 1.0,
            "eval_label": "dos",
        }
    ])
    features, labels, meta = extract_features_and_labels(df)

    # Features must NOT contain eval_label, record_id, src_ip, dst_ip
    assert "eval_label" not in features.columns
    assert "record_id" not in features.columns
    assert "src_ip" not in features.columns
    assert "dst_ip" not in features.columns

    # Label extracted cleanly
    assert labels is not None
    assert labels.iloc[0] == "dos"

    # Metadata preserves IDs and provenance
    assert "record_id" in meta.columns
    assert "src_ip" in meta.columns
