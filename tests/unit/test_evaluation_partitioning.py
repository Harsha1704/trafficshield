"""
Unit Tests for Evaluation Partitioning
======================================
"""
from datetime import UTC, datetime

import pandas as pd
import pytest

from evaluation.partitioning import (
    chronological_three_way_split,
    ugr16_three_way_split,
)


@pytest.fixture
def sequence_of_flows():
    # 30 hourly records
    records = []
    base_ts = datetime(2016, 3, 1, 0, 0, tzinfo=UTC)
    for i in range(30):
        ts = datetime.fromtimestamp(base_ts.timestamp() + i * 3600, tz=UTC)
        records.append({
            "record_id": f"rec-{i:03d}",
            "flow_end_ts": ts.isoformat(),
            "fwd_packets": 10 + i,
            "fwd_bytes": 1000 + i * 100,
            "duration_seconds": 1.0,
            "eval_label": "background",
        })
    return pd.DataFrame(records)


def test_chronological_three_way_split_ratios(sequence_of_flows):
    part = chronological_three_way_split(
        sequence_of_flows,
        train_ratio=0.6,
        cal_ratio=0.2,
        test_ratio=0.2,
    )

    assert part.train_count == 18
    assert part.calibration_count == 6
    assert part.test_count == 6
    assert part.total_count == 30

    # Assert non-overlapping chronological ordering
    assert part.train_time_range[1] <= part.calibration_time_range[0]
    assert part.calibration_time_range[1] <= part.test_time_range[0]


def test_invalid_ratios_raise(sequence_of_flows):
    with pytest.raises(ValueError) as exc:
        chronological_three_way_split(
            sequence_of_flows,
            train_ratio=0.5,
            cal_ratio=0.2,
            test_ratio=0.1,  # Sum = 0.8 != 1.0
        )
    assert "Ratios must sum to 1.0" in str(exc.value)


def test_ugr16_three_way_split():
    # Test UGR'16 official boundaries: March-April train, May-June cal, July-Aug test
    records = [
        {"flow_end_ts": "2016-03-15T12:00:00Z", "fwd_packets": 10, "eval_label": "background"},
        {"flow_end_ts": "2016-04-10T12:00:00Z", "fwd_packets": 12, "eval_label": "background"},
        {"flow_end_ts": "2016-05-15T12:00:00Z", "fwd_packets": 15, "eval_label": "background"},
        {"flow_end_ts": "2016-06-20T12:00:00Z", "fwd_packets": 18, "eval_label": "background"},
        {"flow_end_ts": "2016-07-05T12:00:00Z", "fwd_packets": 50, "eval_label": "dos"},
        {"flow_end_ts": "2016-08-10T12:00:00Z", "fwd_packets": 60, "eval_label": "scan11"},
    ]
    df = pd.DataFrame(records)
    part = ugr16_three_way_split(df)

    assert part.train_count == 2
    assert part.calibration_count == 2
    assert part.test_count == 2

    # Assert training and calibration are purely background
    assert (part.train_df["eval_label"] == "background").all()
    assert (part.calibration_df["eval_label"] == "background").all()

    # Assert test contains attacks
    assert "dos" in part.test_df["eval_label"].values


def test_empty_partition():
    empty_df = pd.DataFrame()
    part = chronological_three_way_split(empty_df)
    assert part.train_count == 0
    assert part.calibration_count == 0
    assert part.test_count == 0
