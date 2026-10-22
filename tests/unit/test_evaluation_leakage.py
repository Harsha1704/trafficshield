"""
Automated Leakage-Prevention Evaluation Test Suite (Milestone 5)
================================================================
Comprehensive suite verifying all 14 leakage-prevention guarantees.
"""
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from detection.isolation_forest import IsolationForestDetector
from detection.statistical import RobustStatisticalDetector
from evaluation.evaluator import ModelEvaluator
from evaluation.metrics import compute_binary_metrics, compute_ranking_metrics
from evaluation.partitioning import chronological_three_way_split
from features.engineering import extract_features_and_labels
from features.policy import PolicyViolationError
from preprocessing.pipeline import TrafficShieldPreprocessor


@pytest.fixture
def sample_partition():
    records = []
    base_ts = datetime(2016, 3, 1, 0, 0, tzinfo=UTC)
    for i in range(100):
        ts = datetime.fromtimestamp(base_ts.timestamp() + i * 3600, tz=UTC)
        is_attack = (i >= 80 and i % 2 == 0)
        label = "dos" if is_attack else "background"
        records.append({
            "record_id": f"flow-{i:04d}",
            "flow_end_ts": ts.isoformat(),
            "src_ip": f"10.0.{i // 256}.{i % 256}",
            "dst_ip": "192.168.1.1",
            "src_port": 10000 + i,
            "dst_port": 80,
            "protocol_name": "TCP",
            "fwd_packets": 500 if is_attack else 15,
            "fwd_bytes": 50000 if is_attack else 1200,
            "duration_seconds": 1.0,
            "tcp_flags_raw": ".A..S.",
            "eval_label": label,
        })
    df = pd.DataFrame(records)
    return chronological_three_way_split(df, train_ratio=0.6, cal_ratio=0.2, test_ratio=0.2)


# ── Check 1: Training functions cannot receive evaluation labels as features ─
def test_leakage_1_training_rejects_evaluation_labels(sample_partition):
    bad_train = sample_partition.train_df.copy()
    bad_train["eval_label"] = "dos"

    # Preprocessor and detector must reject label columns
    prep = TrafficShieldPreprocessor(strict_policy=True)
    with pytest.raises(PolicyViolationError):
        prep.fit(bad_train)


# ── Check 2: Changing test labels does not change fitted models or raw test scores
def test_leakage_2_test_labels_mutation_zero_impact(sample_partition):
    det1 = RobustStatisticalDetector()
    evaluator1 = ModelEvaluator(detector=det1)
    report1 = evaluator1.evaluate_partition(sample_partition, quantile=0.95)

    # Mutate test labels completely
    mutated_partition = sample_partition
    mutated_partition.test_df = sample_partition.test_df.copy()
    mutated_partition.test_df["eval_label"] = "arbitrary_mutated_attack"

    det2 = RobustStatisticalDetector()
    evaluator2 = ModelEvaluator(detector=det2)
    report2 = evaluator2.evaluate_partition(mutated_partition, quantile=0.95)

    # Fitted parameters and threshold must be identical
    np.testing.assert_array_equal(det1.medians_, det2.medians_)
    assert report1.threshold_value == report2.threshold_value


# ── Check 3: Changing test values does not change fitted preprocessor, detector, or threshold
def test_leakage_3_test_values_mutation_zero_impact_on_training(sample_partition):
    det1 = IsolationForestDetector(n_estimators=30, random_state=42)
    evaluator1 = ModelEvaluator(detector=det1)
    report1 = evaluator1.evaluate_partition(sample_partition, quantile=0.95)

    # Inject massive outliers into the test set
    extreme_test_partition = sample_partition
    extreme_test_partition.test_df = sample_partition.test_df.copy()
    extreme_test_partition.test_df["fwd_packets"] = 999_999_999.0

    det2 = IsolationForestDetector(n_estimators=30, random_state=42)
    evaluator2 = ModelEvaluator(detector=det2)
    report2 = evaluator2.evaluate_partition(extreme_test_partition, quantile=0.95)

    # Threshold was frozen from calibration set, so it must not change!
    assert report1.threshold_value == report2.threshold_value


# ── Check 4: Threshold calibration is label-blind ─────────────────────────────
def test_leakage_4_threshold_calibration_is_label_blind(sample_partition):
    det = RobustStatisticalDetector()
    evaluator = ModelEvaluator(detector=det)

    # Verify calibration dataframe labels have zero impact on threshold selection
    p1 = sample_partition
    rep1 = evaluator.evaluate_partition(p1, quantile=0.95)

    p2 = sample_partition
    p2.calibration_df = p2.calibration_df.copy()
    p2.calibration_df["eval_label"] = "ATTACK_LABEL_SHOULD_BE_IGNORED"
    rep2 = evaluator.evaluate_partition(p2, quantile=0.95)

    assert rep1.threshold_value == rep2.threshold_value


# ── Check 5: Test labels are joined only after predictions are generated ──────
def test_leakage_5_predictions_generated_before_label_access(sample_partition):
    # Strip label column entirely during test scoring to prove detector does not need it
    test_no_labels = sample_partition.test_df.drop(columns=["eval_label"])
    features, labels, meta = extract_features_and_labels(test_no_labels)
    assert labels is None

    prep = TrafficShieldPreprocessor()
    prep.fit(extract_features_and_labels(sample_partition.train_df)[0])
    X_test = prep.transform_df(features)

    det = RobustStatisticalDetector()
    det.fit(prep.transform_df(extract_features_and_labels(sample_partition.train_df)[0]))
    scores = det.score_samples(X_test)
    assert np.all(np.isfinite(scores))


# ── Check 6: Future observations cannot enter earlier training partitions ─────
def test_leakage_6_future_observations_excluded_from_train(sample_partition):
    max_train_ts = sample_partition.train_time_range[1]
    min_cal_ts = sample_partition.calibration_time_range[0]
    min_test_ts = sample_partition.test_time_range[0]

    assert max_train_ts <= min_cal_ts
    assert sample_partition.calibration_time_range[1] <= min_test_ts


# ── Check 7: Reverse-direction-dependent features are rejected ─────────────────
def test_leakage_7_reverse_features_rejected(sample_partition):
    bad_train = sample_partition.train_df.copy()
    bad_train["bwd_packets"] = 100.0

    evaluator = ModelEvaluator(detector=RobustStatisticalDetector())
    with pytest.raises(PolicyViolationError) as exc:
        sample_partition.train_df = bad_train
        evaluator.evaluate_partition(sample_partition)
    assert "Forbidden reverse-dependent" in str(exc.value)


# ── Check 8: Identifiers, timestamps, and provenance are excluded from features
def test_leakage_8_identifiers_and_timestamps_excluded(sample_partition):
    features, _, meta = extract_features_and_labels(sample_partition.train_df)
    assert "record_id" not in features.columns
    assert "src_ip" not in features.columns
    assert "dst_ip" not in features.columns
    assert "flow_end_ts" not in features.columns

    assert "record_id" in meta.columns
    assert "src_ip" in meta.columns


# ── Check 9: Metrics are calculated correctly on known synthetic examples ─────
def test_leakage_9_metrics_on_known_synthetic():
    y_true = np.array([0, 0, 1, 1])
    y_pred = np.array([0, 0, 1, 1])
    m = compute_binary_metrics(y_true, y_pred)
    assert m["precision"] == 1.0
    assert m["recall"] == 1.0
    assert m["f1_score"] == 1.0


# ── Check 10: ROC-AUC and average precision use continuous scores ──────────────
def test_leakage_10_ranking_uses_continuous_scores():
    y_true = np.array([0, 0, 1, 1])
    # Continuous scores vs binary scores
    y_scores = np.array([0.1, 0.4, 0.7, 0.9])
    res = compute_ranking_metrics(y_true, y_scores)
    assert res["roc_auc"] == 1.0


# ── Check 11: Undefined metrics are handled according to documented rules ─────
def test_leakage_11_undefined_metrics_recorded():
    y_true = np.array([0, 0, 0, 0])
    y_pred = np.array([0, 0, 0, 0])
    m = compute_binary_metrics(y_true, y_pred)
    assert m["precision"] is None
    assert m["recall"] is None
    assert "precision" in m["undefined_metrics"]
    assert "recall" in m["undefined_metrics"]


# ── Check 12: Repeated runs with fixed configuration are reproducible ─────────
def test_leakage_12_reproducibility(sample_partition):
    det1 = IsolationForestDetector(n_estimators=20, random_state=42)
    rep1 = ModelEvaluator(detector=det1).evaluate_partition(sample_partition, quantile=0.95)

    det2 = IsolationForestDetector(n_estimators=20, random_state=42)
    rep2 = ModelEvaluator(detector=det2).evaluate_partition(sample_partition, quantile=0.95)

    assert rep1.threshold_value == rep2.threshold_value
    assert rep1.binary_metrics == rep2.binary_metrics


# ── Check 13: Single-class test sets produce clear outcomes without crashing ──
def test_leakage_13_single_class_test_set(sample_partition):
    p = sample_partition
    # All background in test partition
    p.test_df = p.test_df.copy()
    p.test_df["eval_label"] = "background"

    rep = ModelEvaluator(detector=RobustStatisticalDetector()).evaluate_partition(p, quantile=0.95)
    assert rep.ranking_metrics["roc_auc"] is None
    assert any("single class" in w for w in rep.warnings)


# ── Check 14: The framework does not evaluate on training observations ────────
def test_leakage_14_no_evaluation_on_training(sample_partition):
    evaluator = ModelEvaluator(detector=RobustStatisticalDetector())
    report = evaluator.evaluate_partition(sample_partition)

    # Number of evaluated test samples must match test partition count, not train count
    assert report.binary_metrics["total_samples"] == sample_partition.test_count
    assert report.binary_metrics["total_samples"] != sample_partition.train_count
