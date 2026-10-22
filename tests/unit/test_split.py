"""
Unit Tests for Chronological Splitting
======================================
"""
from datetime import UTC, datetime

import pandas as pd
import pytest

from ingestion.schema.canonical_flow import CanonicalFlow
from preprocessing.split import (
    audit_temporal_boundary,
    chronological_split,
    ugr16_calibration_test_split,
)


@pytest.fixture
def temporal_df():
    # Sequence of 10 hourly records across March 2016 and July 2016
    records = []
    # 5 calibration records (March 2016)
    for hour in range(5):
        records.append({
            "record_id": f"cal-{hour}",
            "flow_end_ts": f"2016-03-15T{hour:02d}:00:00+00:00",
            "fwd_packets": 10 + hour,
            "fwd_bytes": 1000 + hour * 100,
            "duration_seconds": 1.0,
            "eval_label": "background",
        })
    # 5 test records (July 2016)
    for hour in range(5):
        records.append({
            "record_id": f"test-{hour}",
            "flow_end_ts": f"2016-07-02T{hour:02d}:00:00+00:00",
            "fwd_packets": 50 + hour,
            "fwd_bytes": 5000 + hour * 100,
            "duration_seconds": 2.0,
            "eval_label": "dos" if hour % 2 == 0 else "background",
        })
    return pd.DataFrame(records)


def test_chronological_split_by_ratio(temporal_df):
    train_df, test_df = chronological_split(temporal_df, split_point=0.7)
    assert len(train_df) == 7
    assert len(test_df) == 3

    # Check temporal ordering
    train_max = pd.to_datetime(train_df["flow_end_ts"], utc=True).max()
    test_min = pd.to_datetime(test_df["flow_end_ts"], utc=True).min()
    assert train_max <= test_min


def test_chronological_split_by_cutoff_timestamp(temporal_df):
    train_df, test_df = chronological_split(
        temporal_df,
        split_point="2016-07-01T00:00:00+00:00",
    )
    assert len(train_df) == 5
    assert len(test_df) == 5
    assert (train_df["record_id"].str.startswith("cal-")).all()
    assert (test_df["record_id"].str.startswith("test-")).all()


def test_ugr16_calibration_test_split(temporal_df):
    train_df, test_df = ugr16_calibration_test_split(temporal_df)
    assert len(train_df) == 5
    assert len(test_df) == 5

    # Calibration set must contain background-only
    assert (train_df["eval_label"] == "background").all()
    # Test set contains both attacks and background
    assert "dos" in test_df["eval_label"].values


def test_chronological_split_flows():
    flows = [
        CanonicalFlow(
            record_id=f"flow-{i}",
            flow_end_ts=datetime(2016, 3, 1, i, 0, tzinfo=UTC),
            src_ip="192.0.2.1",
            dst_ip="198.51.100.1",
            protocol_name="TCP",
            fwd_packets=i + 1,
            fwd_bytes=100 * (i + 1),
            duration_seconds=1.0,
        )
        for i in range(4)
    ]
    train_flows, test_flows = chronological_split(flows, split_point=0.5)
    assert len(train_flows) == 2
    assert len(test_flows) == 2
    assert train_flows[0].record_id == "flow-0"
    assert test_flows[0].record_id == "flow-2"


def test_audit_temporal_boundary_valid(temporal_df):
    train_df, test_df = chronological_split(temporal_df, split_point=0.8)
    audit = audit_temporal_boundary(train_df, test_df)
    assert audit["is_valid"] is True
    assert audit["temporal_violations"] == 0


def test_audit_temporal_boundary_detects_leakage():
    train_df = pd.DataFrame([{"flow_end_ts": "2016-03-10T12:00:00+00:00"}])
    # Test record occurs BEFORE train record -> temporal leakage!
    test_df = pd.DataFrame([{"flow_end_ts": "2016-03-01T12:00:00+00:00"}])

    audit = audit_temporal_boundary(train_df, test_df)
    assert audit["is_valid"] is False
    assert audit["temporal_violations"] == 1


def test_temporal_split_raises_on_leakage():
    # If the user crafts overlapping sets and calls audit
    train_df = pd.DataFrame([{"flow_end_ts": "2016-03-10T12:00:00+00:00"}])
    test_df = pd.DataFrame([{"flow_end_ts": "2016-03-01T12:00:00+00:00"}])

    audit = audit_temporal_boundary(train_df, test_df)
    assert audit["is_valid"] is False


def test_chronological_split_empty():
    train_df, test_df = chronological_split(pd.DataFrame(), split_point=0.8)
    assert train_df.empty
    assert test_df.empty
