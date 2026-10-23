"""
Integration & Leakage Tests for UNSW-NB15 Evaluation
===================================================
Milestone 7 — TrafficShield
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from detection.isolation_forest import IsolationForestDetector
from detection.statistical import RobustStatisticalDetector
from evaluation.cli import main as eval_cli_main
from evaluation.evaluator import ModelEvaluator
from evaluation.partitioning import chronological_three_way_split
from features.policy import PolicyViolationError
from ingestion.adapters.unsw_nb15 import UNSW15Adapter
from preprocessing.pipeline import TrafficShieldPreprocessor
from tests.unit.test_unsw15_adapter import create_synthetic_unsw_csv


def test_unsw15_evaluation_pipeline_end_to_end(tmp_path: Path):
    """Verify UNSW-NB15 adapter -> preprocessor -> detector -> evaluator workflow."""
    csv_file = tmp_path / "eval_unsw.csv"
    create_synthetic_unsw_csv(csv_file, n_rows=120)

    adapter = UNSW15Adapter()
    feat_df, lbl_series, meta_df = adapter.load_unidirectional_dataframe(csv_file)
    combined = pd.concat([feat_df, lbl_series, meta_df[["flow_end_ts"]]], axis=1)

    partition = chronological_three_way_split(
        combined,
        train_ratio=0.6,
        cal_ratio=0.2,
        test_ratio=0.2,
        timestamp_col="flow_end_ts",
    )

    # 1. Evaluate RobustStatisticalDetector
    det_stat = RobustStatisticalDetector()
    prep_stat = TrafficShieldPreprocessor(scaler="standard")
    evaluator_stat = ModelEvaluator(detector=det_stat, preprocessor=prep_stat)

    report_stat = evaluator_stat.evaluate_partition(
        partition=partition,
        quantile=0.95,
        label_col="eval_label",
        benign_label="normal",
        dataset_name="synthetic_unsw",
    )
    assert report_stat.detector_type == "RobustStatisticalDetector"
    assert report_stat.train_count == 72
    assert report_stat.calibration_count == 24
    assert report_stat.test_count == 24
    assert np.isfinite(report_stat.threshold_value)
    assert 0.0 <= report_stat.ranking_metrics["roc_auc"] <= 1.0

    # 2. Evaluate IsolationForestDetector
    det_if = IsolationForestDetector(n_estimators=30, random_state=42)
    prep_if = TrafficShieldPreprocessor(scaler="standard")
    evaluator_if = ModelEvaluator(detector=det_if, preprocessor=prep_if)

    report_if = evaluator_if.evaluate_partition(
        partition=partition,
        quantile=0.95,
        label_col="eval_label",
        benign_label="normal",
        dataset_name="synthetic_unsw",
    )
    assert report_if.detector_type == "IsolationForestDetector"
    assert np.isfinite(report_if.threshold_value)
    assert 0.0 <= report_if.ranking_metrics["roc_auc"] <= 1.0


def test_unsw15_evaluator_rejects_reverse_features(tmp_path: Path):
    """Verify evaluator raises PolicyViolationError if reverse features enter partition."""
    df_with_reverse = pd.DataFrame({
        "fwd_packets": [10.0, 20.0, 30.0, 40.0],
        "dbytes": [100.0, 200.0, 300.0, 400.0],  # Forbidden reverse feature
        "flow_end_ts": pd.date_range("2015-01-01", periods=4, freq="min"),
        "eval_label": ["normal", "normal", "exploits", "normal"],
    })

    partition = chronological_three_way_split(df_with_reverse, 0.5, 0.25, 0.25, "flow_end_ts")
    evaluator = ModelEvaluator(detector=RobustStatisticalDetector())

    with pytest.raises(PolicyViolationError) as exc:
        evaluator.evaluate_partition(partition, benign_label="normal")
    assert "dbytes" in str(exc.value)


def test_unsw15_label_mutation_has_zero_effect_on_training_and_calibration(tmp_path: Path):
    """Verify altering test set labels has 0 impact on fitted detector or threshold."""
    csv_file = tmp_path / "mutation_unsw.csv"
    create_synthetic_unsw_csv(csv_file, n_rows=100)

    adapter = UNSW15Adapter()
    feat_df, lbl_series, meta_df = adapter.load_unidirectional_dataframe(csv_file)
    combined = pd.concat([feat_df, lbl_series, meta_df[["flow_end_ts"]]], axis=1)

    part1 = chronological_three_way_split(combined, 0.6, 0.2, 0.2, "flow_end_ts")

    # Invert/mutate all test labels in part2
    combined2 = combined.copy()
    test_idx = part1.test_df.index
    combined2.loc[test_idx, "eval_label"] = "normal"  # change all attacks to normal
    part2 = chronological_three_way_split(combined2, 0.6, 0.2, 0.2, "flow_end_ts")

    det1 = RobustStatisticalDetector()
    prep1 = TrafficShieldPreprocessor(scaler="standard")
    evaluator1 = ModelEvaluator(detector=det1, preprocessor=prep1)
    rep1 = evaluator1.evaluate_partition(part1, quantile=0.95, benign_label="normal")

    det2 = RobustStatisticalDetector()
    prep2 = TrafficShieldPreprocessor(scaler="standard")
    evaluator2 = ModelEvaluator(detector=det2, preprocessor=prep2)
    rep2 = evaluator2.evaluate_partition(part2, quantile=0.95, benign_label="normal")

    # Fitted parameters and calibrated threshold must be identical
    assert rep1.threshold_value == rep2.threshold_value
    np.testing.assert_array_equal(det1.medians_, det2.medians_)
    np.testing.assert_array_equal(det1.mads_, det2.mads_)


def test_cli_unsw15_smoke_integration(tmp_path: Path):
    """Test CLI --dataset unsw15 end-to-end execution on synthetic CSV."""
    csv_file = tmp_path / "UNSW-NB15_1.csv"
    create_synthetic_unsw_csv(csv_file, n_rows=60)

    out_dir = tmp_path / "reports_cli"
    exit_code = eval_cli_main([
        "--dataset", "unsw15",
        "--data", str(csv_file),
        "--max-rows", "50",
        "--detector", "statistical",
        "--out-dir", str(out_dir),
    ])
    assert exit_code == 0
    assert (out_dir / "evaluation_report_RobustStatisticalDetector.json").exists()
    assert (out_dir / "evaluation_summary_RobustStatisticalDetector.csv").exists()
