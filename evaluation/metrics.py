"""
Comprehensive Anomaly Detection Evaluation Metrics
===================================================
Version: 1.0 (Milestone 5)

Calculates threshold-dependent, ranking, and operational performance metrics
strictly after predictions have been generated.

Policy on Undefined Metrics & Single-Class Sets:
-----------------------------------------------
1. When a metric denominator is zero (e.g. Precision when TP + FP == 0, or Recall
   when TP + FN == 0), the metric is set to None (or NaN in numeric exports)
   and explicitly cataloged in the 'undefined_metrics' list.
2. When the evaluation set contains only a single class (all normal or all attack),
   ROC-AUC and Average Precision cannot be computed mathematically; they are set
   to None with an explicit warning recorded.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

logger = logging.getLogger(__name__)


def compute_binary_metrics(
    y_true: np.ndarray | pd.Series,
    y_pred: np.ndarray | pd.Series,
) -> dict[str, Any]:
    """
    Compute comprehensive threshold-dependent classification metrics.

    Parameters
    ----------
    y_true : binary ground-truth array (1 = anomaly/attack, 0 = benign/background)
    y_pred : binary detector prediction array (1 = anomaly flagged, 0 = normal)

    Returns
    -------
    dict containing counts, rates, and catalog of undefined metrics.
    """
    yt = np.asarray(y_true, dtype=int).ravel()
    yp = np.asarray(y_pred, dtype=int).ravel()

    if len(yt) != len(yp):
        raise ValueError(f"Length mismatch between y_true ({len(yt)}) and y_pred ({len(yp)})")
    if len(yt) == 0:
        raise ValueError("Cannot compute metrics on empty evaluation arrays.")

    # Compute confusion matrix elements
    # Ensure 2x2 shape even if one class is absent in predictions or ground-truth
    tn = int(np.sum((yt == 0) & (yp == 0)))
    fp = int(np.sum((yt == 0) & (yp == 1)))
    fn = int(np.sum((yt == 1) & (yp == 0)))
    tp = int(np.sum((yt == 1) & (yp == 1)))

    total = len(yt)
    actual_positives = tp + fn
    actual_negatives = tn + fp
    predicted_positives = tp + fp

    undefined: list[str] = []

    # Precision = TP / (TP + FP)
    if predicted_positives > 0:
        precision = float(tp / predicted_positives)
    else:
        precision = None
        undefined.append("precision")

    # Recall / TPR = TP / (TP + FN)
    if actual_positives > 0:
        recall = float(tp / actual_positives)
    else:
        recall = None
        undefined.append("recall")

    # Specificity / TNR = TN / (TN + FP)
    if actual_negatives > 0:
        specificity = float(tn / actual_negatives)
        fpr = float(fp / actual_negatives)
    else:
        specificity = None
        fpr = None
        undefined.append("specificity")
        undefined.append("fpr")

    # F1 Score = 2 * (Precision * Recall) / (Precision + Recall)
    if precision is not None and recall is not None and (precision + recall) > 0:
        f1 = float(2 * (precision * recall) / (precision + recall))
    else:
        f1 = None
        undefined.append("f1")

    # Balanced Accuracy = (TPR + TNR) / 2
    if recall is not None and specificity is not None:
        balanced_accuracy = float((recall + specificity) / 2.0)
    else:
        balanced_accuracy = None
        undefined.append("balanced_accuracy")

    flagged_pct = float(predicted_positives / total * 100.0)

    return {
        "total_samples": total,
        "true_positives": tp,
        "false_positives": fp,
        "true_negatives": tn,
        "false_negatives": fn,
        "actual_positives": actual_positives,
        "actual_negatives": actual_negatives,
        "flagged_count": predicted_positives,
        "flagged_percentage": round(flagged_pct, 4),
        "precision": round(precision, 6) if precision is not None else None,
        "recall": round(recall, 6) if recall is not None else None,
        "specificity": round(specificity, 6) if specificity is not None else None,
        "false_positive_rate": round(fpr, 6) if fpr is not None else None,
        "f1_score": round(f1, 6) if f1 is not None else None,
        "balanced_accuracy": round(balanced_accuracy, 6) if balanced_accuracy is not None else None,
        "confusion_matrix": [[tn, fp], [fn, tp]],
        "undefined_metrics": undefined,
    }


def compute_ranking_metrics(
    y_true: np.ndarray | pd.Series,
    y_scores: np.ndarray | pd.Series,
) -> dict[str, Any]:
    """
    Compute threshold-independent ranking metrics using continuous anomaly scores.

    Parameters
    ----------
    y_true : binary ground truth (1 = anomaly, 0 = benign)
    y_scores : continuous anomaly scores where higher means more anomalous

    Returns
    -------
    dict with 'roc_auc', 'average_precision', and 'warning' if single-class.
    """
    yt = np.asarray(y_true, dtype=int).ravel()
    ys = np.asarray(y_scores, dtype=np.float64).ravel()

    if len(yt) != len(ys):
        raise ValueError(f"Length mismatch: y_true ({len(yt)}) vs y_scores ({len(ys)})")
    if len(yt) == 0:
        raise ValueError("Cannot compute ranking metrics on empty arrays.")

    unique_classes = np.unique(yt)
    if len(unique_classes) < 2:
        return {
            "roc_auc": None,
            "average_precision": None,
            "warning": (
                f"Evaluation set contains only a single class ({unique_classes[0]}). "
                "ROC-AUC and Average Precision are mathematically undefined."
            ),
        }

    try:
        roc_auc = float(roc_auc_score(yt, ys))
    except Exception as exc:
        logger.warning("ROC-AUC computation failed: %s", exc)
        roc_auc = None

    try:
        avg_prec = float(average_precision_score(yt, ys))
    except Exception as exc:
        logger.warning("Average Precision computation failed: %s", exc)
        avg_prec = None

    return {
        "roc_auc": round(roc_auc, 6) if roc_auc is not None else None,
        "average_precision": round(avg_prec, 6) if avg_prec is not None else None,
        "warning": None,
    }


def compute_per_category_metrics(
    y_true_labels: pd.Series | Sequence[str],
    y_pred: np.ndarray | pd.Series,
    benign_label: str = "background",
) -> dict[str, dict[str, Any]]:
    """
    Break down detection performance across individual attack categories.

    Parameters
    ----------
    y_true_labels : raw string labels (e.g. 'dos', 'scan11', 'nerisbotnet', 'background')
    y_pred : binary predictions (1 = anomaly, 0 = normal)
    benign_label : label designated as normal/benign

    Returns
    -------
    dict mapping each distinct attack category to detection counts and recall rate.
    """
    labels = pd.Series(y_true_labels).astype(str).reset_index(drop=True)
    preds = pd.Series(y_pred).astype(int).reset_index(drop=True)

    results: dict[str, dict[str, Any]] = {}

    for cat in sorted(labels.unique()):
        if cat == benign_label:
            continue
        mask = (labels == cat)
        cat_total = int(mask.sum())
        cat_detected = int((preds[mask] == 1).sum())
        recall = float(cat_detected / cat_total) if cat_total > 0 else 0.0

        results[cat] = {
            "total_occurrences": cat_total,
            "detected_count": cat_detected,
            "missed_count": cat_total - cat_detected,
            "recall": round(recall, 6),
        }

    return results


def compute_temporal_alert_metrics(
    timestamps: pd.Series | Sequence[Any],
    y_pred: np.ndarray | pd.Series,
    freq: str = "1h",
) -> dict[str, Any]:
    """
    Calculate operational alert frequency over time windows.

    Parameters
    ----------
    timestamps : observation datetime series
    y_pred : binary prediction indicators
    freq : pandas resampling frequency string (default: '1h')
    """
    ts = pd.to_datetime(pd.Series(timestamps), utc=True).reset_index(drop=True)
    preds = pd.Series(y_pred, name="alert").astype(int).reset_index(drop=True)

    if ts.isna().all() or len(ts) == 0:
        return {
            "total_alerts": int(preds.sum()),
            "alerts_per_interval_mean": None,
            "alerts_per_interval_max": None,
            "interval_freq": freq,
        }

    df = pd.DataFrame({"ts": ts, "alert": preds}).set_index("ts")
    binned = df["alert"].resample(freq).sum()

    return {
        "total_alerts": int(preds.sum()),
        "interval_freq": freq,
        "n_intervals": len(binned),
        "alerts_per_interval_mean": round(float(binned.mean()), 4) if len(binned) > 0 else 0.0,
        "alerts_per_interval_max": int(binned.max()) if len(binned) > 0 else 0,
        "alerts_per_interval_std": round(float(binned.std()), 4) if len(binned) > 1 else 0.0,
    }
