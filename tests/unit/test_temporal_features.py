"""
Unit Tests for Causal Temporal Behavioural Features
====================================================
"""
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from features.temporal import TemporalFeatureEngineer


@pytest.fixture
def chronological_flow_df():
    base_ts = datetime(2016, 3, 1, 10, 0, tzinfo=UTC)
    records = []
    # 5 flows spaced 60 seconds apart for host 10.0.0.1
    for i in range(5):
        ts = datetime.fromtimestamp(base_ts.timestamp() + i * 60, tz=UTC)
        records.append({
            "flow_end_ts": ts.isoformat(),
            "src_ip": "10.0.0.1",
            "dst_port": 80 if i % 2 == 0 else 443,
            "fwd_packets": 10 * (i + 1),
            "fwd_bytes": 1000 * (i + 1),
        })
    # 2 flows for host 10.0.0.2
    for i in range(2):
        ts = datetime.fromtimestamp(base_ts.timestamp() + i * 120, tz=UTC)
        records.append({
            "flow_end_ts": ts.isoformat(),
            "src_ip": "10.0.0.2",
            "dst_port": 22,
            "fwd_packets": 5,
            "fwd_bytes": 500,
        })
    return pd.DataFrame(records)


def test_temporal_features_causality_and_exclusion_of_current_row(chronological_flow_df):
    t_eng = TemporalFeatureEngineer(window_seconds=300.0, group_by="src_ip")
    out = t_eng.transform_dataframe(chronological_flow_df)

    assert "rolling_flow_count" in out.columns
    assert "rolling_packet_sum" in out.columns
    assert "inter_arrival_time" in out.columns
    assert "burst_packet_ratio" in out.columns

    # First flow of host 10.0.0.1 (row 0):
    # Strictly prior flows in window MUST be 0
    assert out.loc[0, "rolling_flow_count"] == 0.0
    assert out.loc[0, "rolling_packet_sum"] == 0.0
    assert out.loc[0, "inter_arrival_time"] == t_eng.fallback_iat

    # Second flow of host 10.0.0.1 (row 1, 60s later):
    # Exactly 1 prior flow in window, with 10 packets
    assert out.loc[1, "rolling_flow_count"] == 1.0
    assert out.loc[1, "rolling_packet_sum"] == 10.0
    assert out.loc[1, "inter_arrival_time"] == 60.0

    # Third flow of host 10.0.0.1 (row 2, 120s from start):
    # Exactly 2 prior flows in window (10 + 20 = 30 packets)
    assert out.loc[2, "rolling_flow_count"] == 2.0
    assert out.loc[2, "rolling_packet_sum"] == 30.0
    assert out.loc[2, "inter_arrival_time"] == 60.0


def test_future_observations_cannot_alter_earlier_features(chronological_flow_df):
    t_eng = TemporalFeatureEngineer(window_seconds=300.0, group_by="src_ip")
    out_original = t_eng.transform_dataframe(chronological_flow_df)

    # Mutate future flows (e.g. modify the last flow)
    mutated_df = chronological_flow_df.copy()
    mutated_df.loc[4, "fwd_packets"] = 999999.0
    mutated_df.loc[4, "fwd_bytes"] = 99999999.0

    out_mutated = t_eng.transform_dataframe(mutated_df)

    # Rows 0-3 MUST be strictly identical
    pd.testing.assert_frame_equal(out_original.iloc[:4], out_mutated.iloc[:4])


def test_identifiers_and_timestamps_excluded():
    df = pd.DataFrame([{
        "flow_end_ts": "2016-03-01T12:00:00Z",
        "src_ip": "10.0.0.1",
        "dst_port": 80,
        "fwd_packets": 10,
        "fwd_bytes": 1000,
    }])
    t_eng = TemporalFeatureEngineer(group_by="src_ip")
    out = t_eng.transform_dataframe(df)

    # Grouping key 'src_ip' and timestamp 'flow_end_ts' must NOT be in output
    assert "src_ip" not in out.columns
    assert "flow_end_ts" not in out.columns
    assert "_epoch_sec" not in out.columns


def test_empty_and_single_row():
    t_eng = TemporalFeatureEngineer()
    out_empty = t_eng.transform_dataframe(pd.DataFrame())
    assert out_empty.empty

    single_df = pd.DataFrame([{
        "flow_end_ts": "2016-03-01T12:00:00Z",
        "fwd_packets": 10,
        "fwd_bytes": 1000,
    }])
    out_single = t_eng.transform_dataframe(single_df)
    assert len(out_single) == 1
    assert out_single.loc[0, "rolling_flow_count"] == 0.0
    assert np.all(np.isfinite(out_single.to_numpy()))


def test_port_diversity_tracking(chronological_flow_df):
    t_eng = TemporalFeatureEngineer(window_seconds=300.0, group_by="src_ip")
    out = t_eng.transform_dataframe(chronological_flow_df)

    # Row 0: 0 ports in prior window
    assert out.loc[0, "rolling_dst_port_diversity"] == 0.0
    # Row 1 (after port 80 seen): 1 distinct port
    assert out.loc[1, "rolling_dst_port_diversity"] == 1.0
    # Row 2 (after ports 80 and 443 seen): 2 distinct ports
    assert out.loc[2, "rolling_dst_port_diversity"] == 2.0
