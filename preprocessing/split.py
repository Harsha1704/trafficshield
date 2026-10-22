"""
Chronological Splitting & Temporal Boundary Enforcement
========================================================
Version: 1.0 (Milestone 3)

Provides strictly chronological data partitioning functions designed to eliminate
future lookahead and temporal leakage.

Guarantees:
1. NO FUTURE LOOKAHEAD: Training partitions strictly precede test/evaluation partitions.
   Every observation in the test set occurs on or after the latest observation
   in the training set.
2. ZERO SHUFFLING: Cross-sectional random shuffling is prohibited across time.
3. OFFICIAL UGR'16 PARTITIONING: Preconfigured boundary splitting calibration
   (March–June 2016) from test (July–August 2016).
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

import pandas as pd

from ingestion.schema.canonical_flow import CanonicalFlow


class TemporalLeakageError(ValueError):
    """Raised when test observations precede or overlap with training observations in time."""


def audit_temporal_boundary(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    timestamp_col: str = "flow_end_ts",
) -> dict[str, Any]:
    """
    Audit two partitions to verify strictly non-overlapping chronological order.

    Returns
    -------
    dict with keys:
        - is_valid (bool): True if train_max <= test_min
        - train_count (int)
        - test_count (int)
        - train_max_ts (str or None)
        - test_min_ts (str or None)
        - temporal_violations (int): count of test rows occurring before train_max
    """
    if train_df.empty or test_df.empty:
        return {
            "is_valid": True,
            "train_count": len(train_df),
            "test_count": len(test_df),
            "train_max_ts": None,
            "test_min_ts": None,
            "temporal_violations": 0,
        }

    train_ts = pd.to_datetime(train_df[timestamp_col], utc=True)
    test_ts = pd.to_datetime(test_df[timestamp_col], utc=True)

    train_max = train_ts.max()
    test_min = test_ts.min()

    violations = int((test_ts < train_max).sum())
    is_valid = bool(violations == 0)

    return {
        "is_valid": is_valid,
        "train_count": len(train_df),
        "test_count": len(test_df),
        "train_max_ts": train_max.isoformat() if pd.notna(train_max) else None,
        "test_min_ts": test_min.isoformat() if pd.notna(test_min) else None,
        "temporal_violations": violations,
    }


def chronological_split(
    data: pd.DataFrame | Sequence[CanonicalFlow],
    split_point: float | str | datetime = 0.8,
    timestamp_col: str = "flow_end_ts",
    enforce_strict_order: bool = True,
) -> tuple[Any, Any]:
    """
    Split data strictly chronologically into (train, test).

    Parameters
    ----------
    data : pd.DataFrame or Sequence of CanonicalFlow
        The input dataset to partition.
    split_point : float or str or datetime
        If float between 0.0 and 1.0, the fraction of records allocated to train.
        If str or datetime, the cutoff timestamp where records before the timestamp
        go to train, and records on or after go to test.
    timestamp_col : str
        The timestamp column to order by (default: 'flow_end_ts').
    enforce_strict_order : bool
        If True, raises TemporalLeakageError if any test timestamp precedes the train max.

    Returns
    -------
    (train, test) matching the input type.
    """
    is_flows = False
    if isinstance(data, pd.DataFrame):
        df = data.copy()
    elif isinstance(data, (list, tuple)):
        is_flows = True
        if not data:
            return [], []
        records = [f.model_dump() if hasattr(f, "model_dump") else dict(f) for f in data]
        df = pd.DataFrame.from_records(records)
    else:
        raise TypeError(f"Unsupported data type for chronological_split: {type(data)}")

    if df.empty:
        return (pd.DataFrame(), pd.DataFrame()) if not is_flows else ([], [])

    if timestamp_col not in df.columns:
        raise KeyError(f"Timestamp column '{timestamp_col}' not found in data.")

    # Convert timestamps to UTC datetime for accurate ordering
    df["_sort_ts"] = pd.to_datetime(df[timestamp_col], utc=True)
    df = df.sort_values(by="_sort_ts", ascending=True).reset_index(drop=True)

    if isinstance(split_point, (int, float)):
        if not 0.0 < split_point < 1.0:
            raise ValueError(f"Split ratio must be between 0.0 and 1.0, got {split_point}")
        n_samples = len(df)
        split_idx = int(n_samples * split_point)
        train_df = df.iloc[:split_idx].copy()
        test_df = df.iloc[split_idx:].copy()
    else:
        cutoff_dt = pd.to_datetime(split_point, utc=True)
        train_df = df[df["_sort_ts"] < cutoff_dt].copy()
        test_df = df[df["_sort_ts"] >= cutoff_dt].copy()

    train_df = train_df.drop(columns=["_sort_ts"])
    test_df = test_df.drop(columns=["_sort_ts"])

    if enforce_strict_order and not train_df.empty and not test_df.empty:
        audit = audit_temporal_boundary(train_df, test_df, timestamp_col=timestamp_col)
        if not audit["is_valid"]:
            raise TemporalLeakageError(
                f"Temporal boundary violated: {audit['temporal_violations']} test records "
                f"occur before the maximum training timestamp ({audit['train_max_ts']})."
            )

    if is_flows:
        train_records = train_df.to_dict(orient="records")
        test_records = test_df.to_dict(orient="records")
        train_flows = [CanonicalFlow(**r) for r in train_records]
        test_flows = [CanonicalFlow(**r) for r in test_records]
        return train_flows, test_flows

    return train_df, test_df


def ugr16_calibration_test_split(
    data: pd.DataFrame | Sequence[CanonicalFlow],
    timestamp_col: str = "flow_end_ts",
) -> tuple[Any, Any]:
    """
    Split UGR'16 dataset into the official Calibration and Test periods.

    - Calibration Period: March 1, 2016 00:00:00 UTC through June 30, 2016 23:59:59 UTC
      (Background-only normal operational baseline).
    - Test Period: July 1, 2016 00:00:00 UTC onwards
      (Evaluation period containing background + active attack anomalies).
    """
    ugr16_test_cutoff = "2016-07-01T00:00:00+00:00"
    return chronological_split(
        data=data,
        split_point=ugr16_test_cutoff,
        timestamp_col=timestamp_col,
        enforce_strict_order=True,
    )
