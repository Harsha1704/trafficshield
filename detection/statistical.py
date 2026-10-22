"""
Robust Statistical Anomaly Detector
===================================
Version: 1.0 (Milestone 4)

Non-parametric, robust statistical baseline for unidirectional network traffic.
Uses training/calibration medians and Median Absolute Deviations (MAD) to compute
standardized feature deviations.

Key Characteristics:
1. NON-PARAMETRIC & OUTLIER RESISTANT: Medians and MADs are resistant to extreme
   unlabelled spikes that may exist in baseline calibration data.
2. ZERO-MAD FALLBACK: Explicitly handles constant or low-variance features without
   producing division-by-zero, infinite deviations, or NaN outputs.
3. CONFIGURABLE AGGREGATION: Combines individual feature deviations into an overall
   continuous anomaly score via maximum deviation, top-k mean, Euclidean norm,
   or average deviation.
4. EXPLAINABILITY PRESERVATION: Preserves feature identities and scores so operators
   can inspect which features contributed most to an anomaly score.
5. STRICT TEMPORAL ISOLATION: Baseline statistics are learned once from the
   historical calibration partition. No future observations or rolling window
   contaminations occur during inference.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

import numpy as np
import pandas as pd

from detection.base import BaseDetector

logger = logging.getLogger(__name__)

# Normal distribution scale consistency factor for MAD (1 / norm.ppf(0.75))
MAD_SCALE_FACTOR: float = 1.482602218505602


class RobustStatisticalDetector(BaseDetector):
    """
    Robust baseline anomaly detector based on standardized Median Absolute Deviation (MAD).
    """

    def __init__(
        self,
        aggregation: Literal["max", "top_k", "mean", "l2"] = "max",
        top_k: int = 3,
        threshold: float | None = None,
        zero_mad_fallback_scale: float = 1.0,
    ) -> None:
        """
        Parameters
        ----------
        aggregation : {"max", "top_k", "mean", "l2"}
            Method to aggregate multi-feature standardized deviations into a single score:
            - 'max': Maximum deviation across any feature (best for spike/burst detection).
            - 'top_k': Mean of the top-k highest feature deviations.
            - 'mean': Arithmetic mean of all feature deviations.
            - 'l2': Euclidean norm across all feature deviations.
        top_k : int
            Number of top deviant features to average when aggregation='top_k'.
        threshold : float or None
            Decision threshold above which an observation is classified as anomalous.
        zero_mad_fallback_scale : float
            Scale denominator used when a feature has MAD == 0 during calibration.
        """
        super().__init__(threshold=threshold)
        self.aggregation = aggregation
        self.top_k = top_k
        self.zero_mad_fallback_scale = zero_mad_fallback_scale

        # Learned calibration statistics
        self.medians_: np.ndarray | None = None
        self.mads_: np.ndarray | None = None
        self.scales_: np.ndarray | None = None
        self.is_constant_feature_: np.ndarray | None = None

    def fit(
        self,
        X: pd.DataFrame | np.ndarray,
        y: Any = None,
    ) -> RobustStatisticalDetector:
        """
        Fit reference statistics (medians and MADs) on training/calibration data.

        Parameters
        ----------
        X : pd.DataFrame or np.ndarray of shape (n_samples, n_features)
            Unlabelled calibration feature matrix.
        y : None
            Ignored. primary calibration is unsupervised.
        """
        arr = self._validate_data(X, is_fit=True)

        n_samples, n_features = arr.shape
        if n_samples < 2:
            raise ValueError(f"Need at least 2 observations to calculate MAD, got {n_samples}.")

        # 1. Compute median per feature
        medians = np.median(arr, axis=0)

        # 2. Compute Median Absolute Deviation (MAD)
        abs_diffs = np.abs(arr - medians)
        mads = np.median(abs_diffs, axis=0)

        # 3. Compute scale factor (MAD * 1.4826) with documented zero-MAD fallback
        scales = mads * MAD_SCALE_FACTOR
        is_constant = np.zeros(n_features, dtype=bool)

        for j in range(n_features):
            if scales[j] <= 1e-12:
                # Fallback: check Mean Absolute Deviation
                mean_ad = float(np.mean(abs_diffs[:, j]))
                if mean_ad > 1e-12:
                    scales[j] = mean_ad * 1.2533  # Normal consistency factor for MeanAD
                else:
                    # Constant feature in training set
                    scales[j] = self.zero_mad_fallback_scale
                    is_constant[j] = True

        self.medians_ = medians
        self.mads_ = mads
        self.scales_ = scales
        self.is_constant_feature_ = is_constant
        self.is_fitted_ = True

        logger.debug(
            "Fitted RobustStatisticalDetector on %d samples, %d features (%d constant).",
            n_samples, n_features, int(np.sum(is_constant)),
        )
        return self

    def compute_feature_deviations(
        self,
        X: pd.DataFrame | np.ndarray,
    ) -> np.ndarray:
        """
        Compute normalized robust deviation matrix z_ij = |x_ij - median_j| / scale_j.

        Returns
        -------
        np.ndarray of shape (n_samples, n_features) containing positive deviations.
        """
        if not self.is_fitted_ or self.medians_ is None or self.scales_ is None:
            raise RuntimeError("RobustStatisticalDetector must be fitted before computing deviations.")

        arr = self._validate_data(X, is_fit=False)
        abs_diffs = np.abs(arr - self.medians_)
        z_scores = abs_diffs / self.scales_

        # Guard against any non-finite values
        z_scores = np.nan_to_num(z_scores, nan=0.0, posinf=1e6, neginf=0.0)
        return np.asarray(z_scores, dtype=np.float64)

    def score_samples(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        """
        Compute continuous anomaly scores for observations.

        Higher score strictly indicates greater deviation from calibration baseline.

        Returns
        -------
        np.ndarray of shape (n_samples,) with finite float64 anomaly scores.
        """
        z = self.compute_feature_deviations(X)

        if self.aggregation == "max":
            scores = np.max(z, axis=1)
        elif self.aggregation == "mean":
            scores = np.mean(z, axis=1)
        elif self.aggregation == "l2":
            scores = np.sqrt(np.sum(z ** 2, axis=1))
        elif self.aggregation == "top_k":
            k = min(self.top_k, z.shape[1])
            # Partition to extract top-k elements per row efficiently
            top_k_vals = np.partition(z, -k, axis=1)[:, -k:]
            scores = np.mean(top_k_vals, axis=1)
        else:
            raise ValueError(f"Unknown aggregation method: '{self.aggregation}'")

        return np.asarray(scores, dtype=np.float64)

    def explain_samples(
        self,
        X: pd.DataFrame | np.ndarray,
        top_n: int = 3,
    ) -> list[list[dict[str, Any]]]:
        """
        Provide top contributing features and their robust deviations for each record.

        Parameters
        ----------
        X : pd.DataFrame or np.ndarray
            Observations to explain.
        top_n : int
            Number of top deviant features to return per record.

        Returns
        -------
        list of list of dicts: For each record, a list of top_n dicts with:
            - 'feature': feature name
            - 'value': observed value
            - 'median': calibration median
            - 'mad': calibration MAD
            - 'deviation': standardized robust deviation score
        """
        if not self.is_fitted_ or self.medians_ is None or self.mads_ is None:
            raise RuntimeError("Detector must be fitted before explaining samples.")

        arr = self._validate_data(X, is_fit=False)
        z = self.compute_feature_deviations(X)
        n_samples, n_features = arr.shape
        n_top = min(top_n, n_features)

        explanations: list[list[dict[str, Any]]] = []
        for i in range(n_samples):
            # Sort indices by deviation descending
            sorted_idx = np.argsort(-z[i])[:n_top]
            sample_expl: list[dict[str, Any]] = []
            for j in sorted_idx:
                fname = self.feature_names_in_[j] if j < len(self.feature_names_in_) else f"feature_{j}"
                sample_expl.append({
                    "feature": fname,
                    "value": float(arr[i, j]),
                    "median": float(self.medians_[j]),
                    "mad": float(self.mads_[j]),
                    "deviation": float(z[i, j]),
                })
            explanations.append(sample_expl)

        return explanations

    def get_params(self, deep: bool = True) -> dict[str, Any]:
        """Return hyperparameter dictionary."""
        return {
            "aggregation": self.aggregation,
            "top_k": self.top_k,
            "threshold": self.threshold,
            "zero_mad_fallback_scale": self.zero_mad_fallback_scale,
        }
