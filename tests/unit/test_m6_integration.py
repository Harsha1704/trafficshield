"""
Milestone 6 Integration & Leakage Tests
========================================
Validates end-to-end integration of Temporal Behavioural Features,
LOF novelty detection, and HDBSCAN density anomaly detection within
the TrafficShield evaluation and leakage prevention framework.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from detection.hdbscan_detector import HDBSCANDetector
from detection.lof import LOFDetector
from evaluation.cli import main as eval_cli_main
from evaluation.evaluator import ModelEvaluator
from evaluation.partitioning import chronological_three_way_split
from features.engineering import extract_features_and_labels
from features.policy import PolicyViolationError
from features.temporal import TemporalFeatureEngineer
from ingestion.schema.canonical_flow import CanonicalFlow
from preprocessing.pipeline import TrafficShieldPreprocessor


def generate_synthetic_flow_records(n: int = 150) -> list[CanonicalFlow]:
    """Generate synthetic unidirectional CanonicalFlow objects with timestamps."""
    np.random.seed(42)
    flows: list[CanonicalFlow] = []
    base_time = datetime(2016, 3, 1, 10, 0, 0, tzinfo=UTC)

    for i in range(n):
        # Time steps every 10 seconds
        ts = datetime.fromtimestamp(base_time.timestamp() + (i * 10), tz=UTC)
        is_attack = (i >= 120) and (i % 2 == 0)

        pkts = int(np.random.normal(loc=100.0 if is_attack else 15.0, scale=3.0))
        pkts = max(1, pkts)
        bytes_val = int(np.random.normal(loc=50000.0 if is_attack else 1200.0, scale=100.0))
        bytes_val = max(10, bytes_val)

        flows.append(
            CanonicalFlow(
                record_id=f"flow-{i:04d}",
                flow_end_ts=ts,
                src_ip="192.168.1.50" if is_attack else f"10.0.0.{(i % 5) + 1}",
                dst_ip="10.0.0.99",
                src_port=40000 + (i % 20000),
                dst_port=80 if (i % 3 != 0) else 443,
                protocol_name="TCP",
                fwd_packets=pkts,
                fwd_bytes=bytes_val,
                duration_seconds=float(np.random.uniform(0.1, 1.5)),
                tcp_flags_raw=".A..S." if not is_attack else ".FSA.",
                eval_label="dos" if is_attack else "background",
            )
        )
    return flows


def test_end_to_end_m6_pipeline_with_temporal_features():
    """Verify end-to-end integration: Temporal Engineer -> Preprocessing -> LOF & HDBSCAN -> Evaluator."""
    flows = generate_synthetic_flow_records(150)
    raw_df = pd.DataFrame([f.model_dump() for f in flows])

    # 1. Temporal Feature Engineering
    t_eng = TemporalFeatureEngineer(window_seconds=60.0, group_by="src_ip")
    temporal_df = t_eng.transform_dataframe(raw_df)
    assert "rolling_flow_count" in temporal_df.columns
    assert "inter_arrival_time" in temporal_df.columns
    assert len(temporal_df) == 150

    # Combine temporal features into raw_df
    combined_raw = pd.concat([raw_df, temporal_df], axis=1)

    # 2. Extract Features & Labels
    feat_df, labels, meta = extract_features_and_labels(combined_raw)
    assert "eval_label" not in feat_df.columns
    assert "src_ip" not in feat_df.columns
    assert "rolling_flow_count" in feat_df.columns

    # 3. Chronological 3-way split (train=60%, cal=20%, test=20%)
    partition = chronological_three_way_split(
        pd.concat([feat_df, labels.to_frame(), meta[["flow_end_ts"]]], axis=1),
        train_ratio=0.6,
        cal_ratio=0.2,
        test_ratio=0.2,
        timestamp_col="flow_end_ts",
    )

    assert partition.train_count == 90
    assert partition.calibration_count == 30
    assert partition.test_count == 30

    # 4. Evaluate LOF detector
    lof = LOFDetector(n_neighbors=10)
    prep_lof = TrafficShieldPreprocessor(scaler="standard")
    evaluator_lof = ModelEvaluator(detector=lof, preprocessor=prep_lof)

    report_lof = evaluator_lof.evaluate_partition(
        partition=partition,
        quantile=0.90,
        label_col="eval_label",
        benign_label="background",
        dataset_name="synthetic_m6",
    )
    assert report_lof.detector_type == "LOFDetector"
    assert report_lof.train_count == 90
    assert np.isfinite(report_lof.threshold_value)
    assert 0.0 <= report_lof.ranking_metrics["roc_auc"] <= 1.0

    # 5. Evaluate HDBSCAN detector
    hdbscan = HDBSCANDetector(min_cluster_size=5)
    prep_hdbscan = TrafficShieldPreprocessor(scaler="standard")
    evaluator_hdbscan = ModelEvaluator(detector=hdbscan, preprocessor=prep_hdbscan)

    report_hdbscan = evaluator_hdbscan.evaluate_partition(
        partition=partition,
        quantile=0.90,
        label_col="eval_label",
        benign_label="background",
        dataset_name="synthetic_m6",
    )
    assert report_hdbscan.detector_type == "HDBSCANDetector"
    assert report_hdbscan.train_count == 90
    assert np.isfinite(report_hdbscan.threshold_value)
    assert 0.0 <= report_hdbscan.ranking_metrics["roc_auc"] <= 1.0


def test_m6_detectors_strict_leakage_isolation():
    """Verify test labels and test data do not leak into fitted LOF or HDBSCAN models."""
    np.random.seed(42)
    X_train = np.random.normal(loc=0.0, scale=1.0, size=(50, 4))
    X_cal = np.random.normal(loc=0.0, scale=1.0, size=(20, 4))
    X_test = np.random.normal(loc=5.0, scale=1.0, size=(20, 4))

    # Fit LOF
    lof = LOFDetector(n_neighbors=5)
    lof.fit(X_train)
    cal_scores_1 = lof.score_samples(X_cal)
    thresh_1 = lof.calibrate_threshold(cal_scores_1, quantile=0.95)

    # Invert or alter test observations
    _ = lof.score_samples(X_test)
    _ = lof.score_samples(X_test * 100.0)

    # Re-score cal and re-check threshold; parameters must remain frozen
    cal_scores_2 = lof.score_samples(X_cal)
    np.testing.assert_array_equal(cal_scores_1, cal_scores_2)
    assert lof.threshold_ == thresh_1

    # Fit HDBSCAN
    hdb = HDBSCANDetector(min_cluster_size=5)
    hdb.fit(X_train)
    hdb_cal_scores_1 = hdb.score_samples(X_cal)
    hdb_thresh_1 = hdb.calibrate_threshold(hdb_cal_scores_1, quantile=0.95)

    _ = hdb.score_samples(X_test)
    _ = hdb.score_samples(X_test * 100.0)

    hdb_cal_scores_2 = hdb.score_samples(X_cal)
    np.testing.assert_array_equal(hdb_cal_scores_1, hdb_cal_scores_2)
    assert hdb.threshold_ == hdb_thresh_1


def test_m6_detectors_reject_forbidden_columns():
    """Verify LOF and HDBSCAN raise PolicyViolationError when forbidden columns are passed."""
    df_forbidden = pd.DataFrame({
        "fwd_packets": [10.0, 20.0, 30.0, 40.0, 50.0],
        "eval_label": ["background", "background", "dos", "background", "background"],
    })

    lof = LOFDetector(n_neighbors=3)
    with pytest.raises(PolicyViolationError):
        lof.fit(df_forbidden)

    hdb = HDBSCANDetector(min_cluster_size=2)
    with pytest.raises(PolicyViolationError):
        hdb.fit(df_forbidden)


def test_evaluation_cli_with_m6_detectors(tmp_path: Path):
    """Test evaluation CLI running end-to-end for LOF and HDBSCAN with temporal features."""
    flows = generate_synthetic_flow_records(100)
    data = []
    for f in flows:
        d = f.model_dump()
        d["flow_end_ts"] = f.flow_end_ts.isoformat()
        data.append(d)
    csv_file = tmp_path / "synthetic_m6_flows.csv"
    pd.DataFrame(data).to_csv(csv_file, index=False)

    out_lof = tmp_path / "out_lof"
    exit_code_lof = eval_cli_main([
        "--data", str(csv_file),
        "--out-dir", str(out_lof),
        "--detector", "lof",
        "--use-temporal-features",
        "--lof-neighbors", "5",
        "--quantile", "0.95",
        "--timestamp-col", "flow_end_ts",
    ])
    assert exit_code_lof == 0
    assert (out_lof / "evaluation_report_LOFDetector.json").exists()
    assert (out_lof / "evaluation_summary_LOFDetector.csv").exists()

    out_hdb = tmp_path / "out_hdb"
    exit_code_hdb = eval_cli_main([
        "--data", str(csv_file),
        "--out-dir", str(out_hdb),
        "--detector", "hdbscan",
        "--hdbscan-min-cluster-size", "5",
        "--quantile", "0.95",
        "--timestamp-col", "flow_end_ts",
    ])
    assert exit_code_hdb == 0
    assert (out_hdb / "evaluation_report_HDBSCANDetector.json").exists()
    assert (out_hdb / "evaluation_summary_HDBSCANDetector.csv").exists()
