"""
Thresholding Policy & Calibration Management
============================================
Version: 1.0 (Milestone 4)

Manages continuous score thresholding policies and frozen calibration boundaries.

Guarantees:
1. SEPARATION OF CONCERNS: Raw continuous scoring is strictly decoupled from
   binary classification decisions.
2. FROZEN CALIBRATION: Thresholds computed on training/calibration sets remain
   frozen during inference. Incoming test batches NEVER adjust the decision boundary.
3. UNSUPERVISED CALIBRATION: Decision boundaries are derived from empirical quantiles
   of unlabelled baseline traffic, NEVER from held-out attack labels.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np


class ThresholdStrategy(StrEnum):
    """Supported decision thresholding strategies."""
    CALIBRATION_QUANTILE = "calibration_quantile"
    MANUAL = "manual"


@dataclass(frozen=True)
class ThresholdConfig:
    """Configuration and provenance for an established decision threshold."""
    strategy: ThresholdStrategy
    threshold_value: float
    quantile: float | None = None
    calibration_sample_size: int | None = None
    description: str = ""


def compute_quantile_threshold(
    calibration_scores: np.ndarray,
    quantile: float = 0.99,
) -> float:
    """
    Calculate an empirical percentile threshold from calibration scores.

    Parameters
    ----------
    calibration_scores : np.ndarray
        Array of continuous anomaly scores computed on calibration observations.
    quantile : float
        Percentile cutoff in (0, 1), e.g. 0.99 for 99th percentile (1% alarm rate
        on baseline calibration traffic).

    Returns
    -------
    float threshold value.
    """
    if len(calibration_scores) == 0:
        raise ValueError("Cannot compute threshold from empty calibration scores array.")

    if not (0.0 < quantile < 1.0):
        raise ValueError(f"Quantile must be strictly in range (0, 1), got {quantile}.")

    scores = np.asarray(calibration_scores, dtype=np.float64)
    if not np.all(np.isfinite(scores)):
        raise ValueError("Calibration scores contain non-finite values (NaN or Inf).")

    threshold_val = float(np.percentile(scores, quantile * 100.0))
    return threshold_val


def create_threshold_config(
    strategy: ThresholdStrategy,
    threshold_value: float,
    quantile: float | None = None,
    calibration_sample_size: int | None = None,
) -> ThresholdConfig:
    """Create a documented, immutable ThresholdConfig."""
    desc = f"Frozen threshold at {threshold_value:.6f} via {strategy}"
    if quantile is not None:
        desc += f" (quantile={quantile:.4f}, n={calibration_sample_size})"

    return ThresholdConfig(
        strategy=strategy,
        threshold_value=threshold_value,
        quantile=quantile,
        calibration_sample_size=calibration_sample_size,
        description=desc,
    )
