"""
Unit Tests for Evaluation Metrics
==================================
"""
import numpy as np
import pandas as pd

from evaluation.metrics import (
    compute_binary_metrics,
    compute_per_category_metrics,
    compute_ranking_metrics,
    compute_temporal_alert_metrics,
)


def test_binary_metrics_perfect_predictions():
    # 5 negatives, 5 positives, all predicted correctly
    y_true = np.array([0, 0, 0, 0, 0, 1, 1, 1, 1, 1])
    y_pred = np.array([0, 0, 0, 0, 0, 1, 1, 1, 1, 1])

    metrics = compute_binary_metrics(y_true, y_pred)
    assert metrics["true_positives"] == 5
    assert metrics["false_positives"] == 0
    assert metrics["true_negatives"] == 5
    assert metrics["false_negatives"] == 0
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0
    assert metrics["f1_score"] == 1.0
    assert metrics["false_positive_rate"] == 0.0
    assert metrics["specificity"] == 1.0
    assert metrics["balanced_accuracy"] == 1.0
    assert len(metrics["undefined_metrics"]) == 0


def test_binary_metrics_with_known_errors():
    # y_true: [0, 0, 0, 0, 1, 1]
    # y_pred: [0, 0, 1, 0, 1, 0]
    # TP=1, FP=1, TN=3, FN=1
    y_true = np.array([0, 0, 0, 0, 1, 1])
    y_pred = np.array([0, 0, 1, 0, 1, 0])

    m = compute_binary_metrics(y_true, y_pred)
    assert m["true_positives"] == 1
    assert m["false_positives"] == 1
    assert m["true_negatives"] == 3
    assert m["false_negatives"] == 1
    assert m["precision"] == 0.5
    assert m["recall"] == 0.5
    assert m["f1_score"] == 0.5
    assert m["false_positive_rate"] == 0.25
    assert m["specificity"] == 0.75
    assert m["balanced_accuracy"] == 0.625


def test_binary_metrics_undefined_handling():
    # No positives predicted: precision is undefined
    y_true = np.array([0, 0, 1, 1])
    y_pred = np.array([0, 0, 0, 0])

    m = compute_binary_metrics(y_true, y_pred)
    assert m["precision"] is None
    assert "precision" in m["undefined_metrics"]
    assert m["recall"] == 0.0

    # No actual negatives: FPR and Specificity are undefined
    y_true_all_pos = np.array([1, 1, 1])
    y_pred_all_pos = np.array([1, 1, 0])
    m2 = compute_binary_metrics(y_true_all_pos, y_pred_all_pos)
    assert m2["false_positive_rate"] is None
    assert m2["specificity"] is None
    assert "fpr" in m2["undefined_metrics"]


def test_ranking_metrics_continuous_scores():
    y_true = np.array([0, 0, 1, 1])
    # Perfectly separated continuous scores
    y_scores = np.array([0.1, 0.2, 0.8, 0.9])

    ranking = compute_ranking_metrics(y_true, y_scores)
    assert ranking["roc_auc"] == 1.0
    assert ranking["average_precision"] == 1.0
    assert ranking["warning"] is None


def test_ranking_metrics_single_class_edge_case():
    # Only class 0 present: ROC-AUC is mathematically undefined
    y_true = np.array([0, 0, 0, 0])
    y_scores = np.array([0.1, 0.2, 0.3, 0.4])

    ranking = compute_ranking_metrics(y_true, y_scores)
    assert ranking["roc_auc"] is None
    assert ranking["average_precision"] is None
    assert "single class" in ranking["warning"]


def test_per_category_metrics():
    labels = pd.Series(["background", "background", "dos", "dos", "scan11", "background"])
    preds = np.array([0, 0, 1, 0, 1, 0])

    cat_metrics = compute_per_category_metrics(labels, preds, benign_label="background")
    assert "dos" in cat_metrics
    assert cat_metrics["dos"]["total_occurrences"] == 2
    assert cat_metrics["dos"]["detected_count"] == 1
    assert cat_metrics["dos"]["recall"] == 0.5

    assert "scan11" in cat_metrics
    assert cat_metrics["scan11"]["total_occurrences"] == 1
    assert cat_metrics["scan11"]["detected_count"] == 1
    assert cat_metrics["scan11"]["recall"] == 1.0


def test_temporal_alert_metrics():
    timestamps = [
        "2016-03-01T01:10:00Z",
        "2016-03-01T01:25:00Z",
        "2016-03-01T02:15:00Z",
    ]
    preds = [1, 1, 0]

    res = compute_temporal_alert_metrics(timestamps, preds, freq="1h")
    assert res["total_alerts"] == 2
    assert res["alerts_per_interval_max"] == 2
