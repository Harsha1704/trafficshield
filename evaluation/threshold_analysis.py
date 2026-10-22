"""
Threshold and False-Alarm Analysis
===================================
Version: 1.0 (Milestone 5)

Performs empirical threshold sweeps on calibration scores (without labels) and
evaluates resulting operational false-alarm and detection trade-offs on test data.

Policy Statement on Distribution Shift:
---------------------------------------
An empirical calibration quantile (e.g. 0.99 for a 1% false alarm target on normal
calibration traffic) is a CALIBRATION TARGET, NOT a guaranteed production outcome.
Non-stationary traffic patterns, concept drift, and novel network services can
cause the observed test false-positive rate to diverge from the calibration target.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from evaluation.metrics import compute_binary_metrics


def evaluate_threshold_sweep(
    calibration_scores: np.ndarray,
    test_scores: np.ndarray,
    test_labels: np.ndarray | pd.Series,
    quantiles: Sequence[float] = (0.90, 0.95, 0.98, 0.99, 0.995, 0.999),
) -> list[dict[str, Any]]:
    """
    Perform a calibration-quantile threshold sweep.

    Parameters
    ----------
    calibration_scores : anomaly scores from calibration partition (unlabelled)
    test_scores : anomaly scores from held-out test partition
    test_labels : binary ground-truth labels for test partition (1=attack, 0=benign)
    quantiles : sequence of empirical calibration percentiles to evaluate

    Returns
    -------
    list of dicts, each detailing:
        - calibration_quantile
        - target_calibration_fpr (1.0 - quantile)
        - threshold_value (computed on calibration scores)
        - test_alert_count
        - test_alert_percentage
        - test_false_positive_rate
        - test_precision
        - test_recall
        - test_f1_score
    """
    cal_scores = np.asarray(calibration_scores, dtype=np.float64).ravel()
    t_scores = np.asarray(test_scores, dtype=np.float64).ravel()
    t_labels = np.asarray(test_labels, dtype=int).ravel()

    if len(cal_scores) == 0:
        raise ValueError("Calibration scores array is empty.")
    if len(t_scores) == 0:
        raise ValueError("Test scores array is empty.")

    sweep_results: list[dict[str, Any]] = []

    for q in sorted(quantiles):
        if not (0.0 < q < 1.0):
            continue

        # 1. Derive frozen threshold strictly on calibration scores
        thresh = float(np.percentile(cal_scores, q * 100.0))
        target_cal_fpr = round(1.0 - q, 6)

        # 2. Apply frozen threshold to held-out test scores
        t_preds = (t_scores >= thresh).astype(int)

        # 3. Compute metrics on test predictions
        metrics = compute_binary_metrics(y_true=t_labels, y_pred=t_preds)

        sweep_results.append({
            "calibration_quantile": q,
            "target_calibration_fpr": target_cal_fpr,
            "threshold_value": round(thresh, 6),
            "calibration_sample_size": len(cal_scores),
            "test_sample_size": len(t_scores),
            "test_alert_count": metrics["flagged_count"],
            "test_alert_percentage": metrics["flagged_percentage"],
            "test_observed_fpr": metrics["false_positive_rate"],
            "test_precision": metrics["precision"],
            "test_recall": metrics["recall"],
            "test_f1_score": metrics["f1_score"],
            "fpr_divergence": (
                round(metrics["false_positive_rate"] - target_cal_fpr, 6)
                if metrics["false_positive_rate"] is not None else None
            ),
        })

    return sweep_results
