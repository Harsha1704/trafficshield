"""
Three-Way Chronological Partitioning for Leakage-Safe Evaluation
=================================================================
Version: 1.0 (Milestone 5)

Enforces strict separation of data into three distinct roles:
1. TRAINING PARTITION: Fits feature preprocessor and detector parameters without labels.
2. THRESHOLD-CALIBRATION PARTITION: Selects decision thresholds (e.g. alert budgets)
   without labels. Never updates preprocessor or detector parameters.
3. HELD-OUT TEST PARTITION: Evaluates frozen predictions against ground-truth labels.
   Never influences fitting or threshold selection.

Boundary Definitions:
---------------------
- Train: [t_min, t_train_end)
- Threshold Calibration: [t_train_end, t_cal_end)
- Final Test: [t_cal_end, t_max]

Guarantees:
-----------
- train_max <= calibration_min <= calibration_max <= test_min
- Overlapping partitions, future lookahead, and timestamp corruption are strictly prohibited.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ingestion.schema.canonical_flow import CanonicalFlow
from preprocessing.split import TemporalLeakageError


@dataclass
class ChronologicalPartition:
    """Stores the three partitioned datasets along with audit metadata."""
    train_df: pd.DataFrame
    calibration_df: pd.DataFrame
    test_df: pd.DataFrame

    timestamp_col: str = "flow_end_ts"
    train_time_range: tuple[str | None, str | None] = (None, None)
    calibration_time_range: tuple[str | None, str | None] = (None, None)
    test_time_range: tuple[str | None, str | None] = (None, None)

    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def train_count(self) -> int:
        return len(self.train_df)

    @property
    def calibration_count(self) -> int:
        return len(self.calibration_df)

    @property
    def test_count(self) -> int:
        return len(self.test_df)

    @property
    def total_count(self) -> int:
        return self.train_count + self.calibration_count + self.test_count


def chronological_three_way_split(
    data: pd.DataFrame | Sequence[CanonicalFlow],
    train_ratio: float = 0.6,
    cal_ratio: float = 0.2,
    test_ratio: float = 0.2,
    timestamp_col: str = "flow_end_ts",
    enforce_strict_order: bool = True,
) -> ChronologicalPartition:
    """
    Partition observations chronologically into Train, Calibration, and Test splits.

    Parameters
    ----------
    data : pd.DataFrame or Sequence of CanonicalFlow
    train_ratio : float proportion allocated to training (default: 0.6)
    cal_ratio : float proportion allocated to threshold calibration (default: 0.2)
    test_ratio : float proportion allocated to final held-out test (default: 0.2)
    timestamp_col : str timestamp column name
    enforce_strict_order : bool if True, validates non-overlapping timestamps

    Returns
    -------
    ChronologicalPartition containing train_df, calibration_df, test_df and metadata.
    """
    total_ratio = train_ratio + cal_ratio + test_ratio
    if not (0.999 <= total_ratio <= 1.001):
        raise ValueError(
            f"Ratios must sum to 1.0, got train={train_ratio}, cal={cal_ratio}, test={test_ratio} (sum={total_ratio})"
        )

    if isinstance(data, pd.DataFrame):
        df = data.copy()
    elif isinstance(data, (list, tuple)):
        if not data:
            empty_df = pd.DataFrame()
            return ChronologicalPartition(empty_df, empty_df, empty_df, timestamp_col=timestamp_col)
        records = [f.model_dump() if hasattr(f, "model_dump") else dict(f) for f in data]
        df = pd.DataFrame.from_records(records)
    else:
        raise TypeError(f"Unsupported input data type: {type(data)}")

    if df.empty:
        empty_df = pd.DataFrame()
        return ChronologicalPartition(empty_df, empty_df, empty_df, timestamp_col=timestamp_col)

    if timestamp_col not in df.columns:
        raise KeyError(f"Timestamp column '{timestamp_col}' not found in data.")

    # Convert timestamps and drop invalid ones
    df["_sort_ts"] = pd.to_datetime(df[timestamp_col], utc=True, errors="coerce")
    n_missing_ts = int(df["_sort_ts"].isna().sum())
    if n_missing_ts > 0:
        df = df.dropna(subset=["_sort_ts"])

    # Sort strictly chronologically
    df = df.sort_values(by="_sort_ts", ascending=True).reset_index(drop=True)
    n_samples = len(df)

    idx_train = int(n_samples * train_ratio)
    idx_cal = int(n_samples * (train_ratio + cal_ratio))

    train_df = df.iloc[:idx_train].copy()
    calibration_df = df.iloc[idx_train:idx_cal].copy()
    test_df = df.iloc[idx_cal:].copy()

    # Time ranges
    def get_range(d: pd.DataFrame) -> tuple[str | None, str | None]:
        if d.empty:
            return (None, None)
        return (d["_sort_ts"].min().isoformat(), d["_sort_ts"].max().isoformat())

    train_range = get_range(train_df)
    cal_range = get_range(calibration_df)
    test_range = get_range(test_df)

    # Drop sort helper column
    train_df = train_df.drop(columns=["_sort_ts"])
    calibration_df = calibration_df.drop(columns=["_sort_ts"])
    test_df = test_df.drop(columns=["_sort_ts"])

    # Audit boundaries
    if enforce_strict_order:
        if train_range[1] and cal_range[0] and train_range[1] > cal_range[0]:
            raise TemporalLeakageError(
                f"Training max timestamp ({train_range[1]}) overlaps with calibration min ({cal_range[0]})"
            )
        if cal_range[1] and test_range[0] and cal_range[1] > test_range[0]:
            raise TemporalLeakageError(
                f"Calibration max timestamp ({cal_range[1]}) overlaps with test min ({test_range[0]})"
            )

    return ChronologicalPartition(
        train_df=train_df,
        calibration_df=calibration_df,
        test_df=test_df,
        timestamp_col=timestamp_col,
        train_time_range=train_range,
        calibration_time_range=cal_range,
        test_time_range=test_range,
        metadata={
            "train_ratio": train_ratio,
            "cal_ratio": cal_ratio,
            "test_ratio": test_ratio,
            "missing_timestamps_dropped": n_missing_ts,
        },
    )


def ugr16_three_way_split(
    data: pd.DataFrame | Sequence[CanonicalFlow],
    timestamp_col: str = "flow_end_ts",
) -> ChronologicalPartition:
    """
    Official UGR'16 Three-Way Chronological Partition:
    1. Training Partition: March 1, 2016 – April 30, 2016 (Calibration background, months 03-04)
    2. Threshold Calibration Partition: May 1, 2016 – June 30, 2016 (Calibration background, months 05-06)
    3. Final Evaluation Test Partition: July 1, 2016 – August 31, 2016 (Test background + attacks)
    """
    if isinstance(data, pd.DataFrame):
        df = data.copy()
    elif isinstance(data, (list, tuple)):
        if not data:
            empty_df = pd.DataFrame()
            return ChronologicalPartition(empty_df, empty_df, empty_df, timestamp_col=timestamp_col)
        records = [f.model_dump() if hasattr(f, "model_dump") else dict(f) for f in data]
        df = pd.DataFrame.from_records(records)
    else:
        raise TypeError(f"Unsupported data type: {type(data)}")

    df["_sort_ts"] = pd.to_datetime(df[timestamp_col], utc=True, errors="coerce")
    df = df.dropna(subset=["_sort_ts"]).sort_values(by="_sort_ts", ascending=True).reset_index(drop=True)

    t_train_end = pd.to_datetime("2016-05-01T00:00:00Z", utc=True)
    t_cal_end = pd.to_datetime("2016-07-01T00:00:00Z", utc=True)

    train_df = df[df["_sort_ts"] < t_train_end].copy()
    calibration_df = df[(df["_sort_ts"] >= t_train_end) & (df["_sort_ts"] < t_cal_end)].copy()
    test_df = df[df["_sort_ts"] >= t_cal_end].copy()

    def get_range(d: pd.DataFrame) -> tuple[str | None, str | None]:
        if d.empty:
            return (None, None)
        return (d["_sort_ts"].min().isoformat(), d["_sort_ts"].max().isoformat())

    train_range = get_range(train_df)
    cal_range = get_range(calibration_df)
    test_range = get_range(test_df)

    train_df = train_df.drop(columns=["_sort_ts"])
    calibration_df = calibration_df.drop(columns=["_sort_ts"])
    test_df = test_df.drop(columns=["_sort_ts"])

    return ChronologicalPartition(
        train_df=train_df,
        calibration_df=calibration_df,
        test_df=test_df,
        timestamp_col=timestamp_col,
        train_time_range=train_range,
        calibration_time_range=cal_range,
        test_time_range=test_range,
        metadata={"split_policy": "ugr16_official_3way"},
    )
