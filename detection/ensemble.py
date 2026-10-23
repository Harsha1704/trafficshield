"""
Calibrated Multi-Detector Anomaly Ensemble
==========================================
Version: 1.0 (Milestone 8.1)

Integrates multiple unsupervised TrafficShield anomaly detectors into a unified,
calibrated ensemble detector.

Key Principles:
1. COMMON SCORE CONTRACT:
   Every underlying detector strictly satisfies the TrafficShield convention where
   HIGHER anomaly scores indicate GREATER anomalousness:
   - RobustStatisticalDetector: scalar distance (higher = more anomalous)
   - IsolationForestDetector: -raw_score (higher = more anomalous)
   - LOFDetector: inverted novelty outlier factor (higher = more anomalous)
   - AutoencoderDetector: reconstruction MSE (higher = more anomalous)
2. CALIBRATION-BASED SCORE NORMALIZATION:
   Raw detector score distributions operate on vastly different numerical scales
   (e.g. MSE in 10^-3, distance in 10^1, isolation score in [-0.5, 0.5]).
   Normalizers are fitted exclusively on the unlabelled historical calibration
   partition (never test labels or test distribution):
   - Empirical Percentile Mapping (default): maps test scores to [0, 1] relative
     to the calibration empirical cumulative distribution function (ECDF).
3. PREDECLARED SCORE FUSION:
   Combines normalized scores via documented, predeclared weights (default: equal weights 1/K).
   Zero test-leakage: weights are never tuned against ground-truth test labels or test F1.
4. FROZEN CALIBRATION THRESHOLD:
   The ensemble decision threshold is determined via empirical quantile (default: 0.99)
   on the fused calibration scores and remains strictly frozen at inference time.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Literal

import numpy as np
import pandas as pd

from detection.autoencoder import AutoencoderDetector
from detection.base import BaseDetector
from detection.isolation_forest import IsolationForestDetector
from detection.lof import LOFDetector
from detection.statistical import RobustStatisticalDetector

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Score Normalizers (Calibration-Only)
# ─────────────────────────────────────────────────────────────────────────────

class BaseScoreNormalizer(ABC):
    """Abstract base class for calibration-only anomaly score normalization."""

    @abstractmethod
    def fit(self, calibration_scores: np.ndarray) -> BaseScoreNormalizer:
        """Fit normalization parameters from calibration scores only."""
        pass

    @abstractmethod
    def transform(self, scores: np.ndarray) -> np.ndarray:
        """Transform arbitrary raw scores into normalized [0, 1] scores."""
        pass


class EmpiricalPercentileNormalizer(BaseScoreNormalizer):
    """
    Empirical cumulative distribution function (ECDF) normalizer.

    Maps any raw anomaly score to its empirical percentile in [0.0, 1.0]
    relative to the historical calibration distribution.

    Handles ties, constant scores, extreme outliers, and small calibration sets safely.
    """

    def __init__(self) -> None:
        self.sorted_scores_: np.ndarray | None = None
        self.n_cal_: int = 0
        self.is_constant_: bool = False
        self.constant_val_: float = 0.0

    def fit(self, calibration_scores: np.ndarray) -> EmpiricalPercentileNormalizer:
        arr = np.asarray(calibration_scores, dtype=np.float64)
        if arr.size == 0:
            raise ValueError("Calibration scores array is empty.")
        if not np.all(np.isfinite(arr)):
            raise ValueError("Calibration scores contain non-finite values (NaN/Inf).")

        self.sorted_scores_ = np.sort(arr)
        self.n_cal_ = len(self.sorted_scores_)
        if self.sorted_scores_[0] == self.sorted_scores_[-1]:
            self.is_constant_ = True
            self.constant_val_ = float(self.sorted_scores_[0])
        else:
            self.is_constant_ = False

        return self

    def transform(self, scores: np.ndarray) -> np.ndarray:
        if self.sorted_scores_ is None or self.n_cal_ == 0:
            raise RuntimeError("EmpiricalPercentileNormalizer must be fitted before transforming scores.")

        arr = np.asarray(scores, dtype=np.float64)
        if self.is_constant_:
            return np.full_like(arr, 0.5, dtype=np.float64)

        # Vectorized searchsorted to obtain empirical ranks
        # side="right" gives rank = count of calibration scores <= s
        ranks = np.searchsorted(self.sorted_scores_, arr, side="right")
        percentiles = ranks.astype(np.float64) / float(self.n_cal_)
        return np.clip(percentiles, 0.0, 1.0)


class RobustMinMaxNormalizer(BaseScoreNormalizer):
    """
    Robust min-max score normalizer based on calibration 1st and 99th percentiles.
    """

    def __init__(self, low_q: float = 0.01, high_q: float = 0.99) -> None:
        self.low_q = low_q
        self.high_q = high_q
        self.min_val_: float = 0.0
        self.max_val_: float = 1.0

    def fit(self, calibration_scores: np.ndarray) -> RobustMinMaxNormalizer:
        arr = np.asarray(calibration_scores, dtype=np.float64)
        if arr.size == 0:
            raise ValueError("Calibration scores array is empty.")
        self.min_val_ = float(np.percentile(arr, self.low_q * 100.0))
        self.max_val_ = float(np.percentile(arr, self.high_q * 100.0))
        if self.max_val_ <= self.min_val_:
            self.max_val_ = self.min_val_ + 1e-6
        return self

    def transform(self, scores: np.ndarray) -> np.ndarray:
        arr = np.asarray(scores, dtype=np.float64)
        normed = (arr - self.min_val_) / (self.max_val_ - self.min_val_)
        return np.clip(normed, 0.0, 1.0)


def create_score_normalizer(method: str) -> BaseScoreNormalizer:
    """Factory helper for score normalizers."""
    m = method.lower()
    if m in ("empirical_percentile", "percentile", "ecdf"):
        return EmpiricalPercentileNormalizer()
    elif m in ("robust_minmax", "minmax"):
        return RobustMinMaxNormalizer()
    else:
        raise ValueError(f"Unknown normalizer method '{method}'. Supported: 'empirical_percentile', 'robust_minmax'.")


# ─────────────────────────────────────────────────────────────────────────────
# Calibrated Ensemble Detector
# ─────────────────────────────────────────────────────────────────────────────

class CalibratedEnsembleDetector(BaseDetector):
    """
    TrafficShield Calibrated Multi-Detector Anomaly Ensemble.

    Combines multiple BaseDetector models using calibration-fitted score normalization
    and predeclared fusion weights.
    """

    def __init__(
        self,
        detectors: dict[str, BaseDetector] | list[BaseDetector] | None = None,
        weights: dict[str, float] | list[float] | None = None,
        normalizer: Literal["empirical_percentile", "robust_minmax"] = "empirical_percentile",
        random_state: int | None = 42,
        threshold: float | None = None,
    ) -> None:
        """
        Parameters
        ----------
        detectors : dict or list of BaseDetector instances, or None
            Detectors to ensemble. If None, instantiates the standard TrafficShield quad:
            [RobustStatistical, IsolationForest, LOF, Autoencoder].
        weights : dict or list of float, or None
            Predeclared weights for each detector. If None, uses equal weights (1/K).
            Weights are automatically normalized to sum to 1.0.
        normalizer : str
            Calibration score normalization method ('empirical_percentile' or 'robust_minmax').
        random_state : int or None
            Random state passed to stochastic member detectors.
        threshold : float or None
            Ensemble decision threshold.
        """
        super().__init__(threshold=threshold)
        self.random_state = random_state
        self.normalizer_name = normalizer

        # Initialize detector dictionary
        if detectors is None:
            self.detectors: dict[str, BaseDetector] = {
                "statistical": RobustStatisticalDetector(),
                "iforest": IsolationForestDetector(random_state=random_state),
                "lof": LOFDetector(),
                "autoencoder": AutoencoderDetector(backend="auto", random_state=random_state),
            }
        elif isinstance(detectors, list):
            self.detectors = {f"detector_{i}_{d.__class__.__name__}": d for i, d in enumerate(detectors)}
        elif isinstance(detectors, dict):
            self.detectors = dict(detectors)
        else:
            raise TypeError(f"detectors must be dict, list, or None, got {type(detectors)}")

        if not self.detectors:
            raise ValueError("CalibratedEnsembleDetector requires at least one detector.")

        # Initialize and validate weights
        self.weights: dict[str, float] = self._resolve_weights(weights)

        # Member normalizers (one per detector)
        self.normalizers_: dict[str, BaseScoreNormalizer] = {
            name: create_score_normalizer(self.normalizer_name) for name in self.detectors
        }
        self.is_calibrated_: bool = False

    def _resolve_weights(self, weights: dict[str, float] | list[float] | None) -> dict[str, float]:
        """Normalize and validate member detector weights."""
        names = list(self.detectors.keys())
        k = len(names)

        if weights is None:
            # Equal weighting
            return dict.fromkeys(names, 1.0 / k)

        if isinstance(weights, list):
            if len(weights) != k:
                raise ValueError(f"Weight list has {len(weights)} entries, but there are {k} detectors.")
            w_dict = {names[i]: float(weights[i]) for i in range(k)}
        elif isinstance(weights, dict):
            missing = set(names) - set(weights.keys())
            if missing:
                raise ValueError(f"Missing weights for detectors: {sorted(missing)}")
            w_dict = {name: float(weights[name]) for name in names}
        else:
            raise TypeError(f"Expected weights as dict, list, or None, got {type(weights)}")

        # Validate non-negativity and sum
        for name, w in w_dict.items():
            if w < 0.0 or not np.isfinite(w):
                raise ValueError(f"Weight for '{name}' must be non-negative and finite, got {w}")

        total = sum(w_dict.values())
        if total <= 0.0:
            raise ValueError("Sum of ensemble weights must be strictly positive.")

        # Normalize to sum to 1.0
        return {name: w / total for name, w in w_dict.items()}

    def fit(
        self,
        X: pd.DataFrame | np.ndarray,
        y: Any = None,
    ) -> CalibratedEnsembleDetector:
        """
        Fit all member detectors on training features only.

        Parameters
        ----------
        X : pd.DataFrame or np.ndarray of shape (n_samples, n_features)
            Eligible training feature matrix.
        y : None
            Ignored. primary training is strictly unsupervised.
        """
        arr = self._validate_data(X, is_fit=True)

        for name, detector in self.detectors.items():
            logger.debug("Fitting ensemble member '%s'...", name)
            detector.fit(arr)

        # Initialize default normalizers on training data so score_samples is valid
        # before explicit calibrate_ensemble() call
        for name, detector in self.detectors.items():
            train_scores = detector.score_samples(arr)
            self.normalizers_[name].fit(train_scores)

        self.is_fitted_ = True
        logger.debug(
            "Fitted CalibratedEnsembleDetector with %d members on %d samples.",
            len(self.detectors), arr.shape[0],
        )
        return self

    def calibrate_ensemble(
        self,
        X_cal: pd.DataFrame | np.ndarray,
    ) -> np.ndarray:
        """
        Fit score normalizers strictly on the independent historical calibration partition.

        Returns
        -------
        Fused calibration anomaly scores of shape (n_cal_samples,).
        """
        if not self.is_fitted_:
            raise RuntimeError("CalibratedEnsembleDetector must be fitted before calibration.")

        arr_cal = self._validate_data(X_cal, is_fit=False)
        fused_cal_scores = np.zeros(arr_cal.shape[0], dtype=np.float64)

        for name, detector in self.detectors.items():
            raw_scores = detector.score_samples(arr_cal)
            self.normalizers_[name].fit(raw_scores)
            normed_scores = self.normalizers_[name].transform(raw_scores)
            fused_cal_scores += self.weights[name] * normed_scores

        self.is_calibrated_ = True
        return fused_cal_scores

    def score_samples(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        """
        Compute fused anomaly scores across all member detectors.

        Returns
        -------
        np.ndarray of shape (n_samples,) in [0.0, 1.0] where HIGHER strictly
        indicates MORE ANOMALOUS.
        """
        if not self.is_fitted_:
            raise RuntimeError(f"{self.__class__.__name__} must be fitted before scoring samples.")

        arr = self._validate_data(X, is_fit=False)
        n_samples = arr.shape[0]
        fused_scores = np.zeros(n_samples, dtype=np.float64)

        for name, detector in self.detectors.items():
            raw_scores = detector.score_samples(arr)
            normed_scores = self.normalizers_[name].transform(raw_scores)
            fused_scores += self.weights[name] * normed_scores

        if not np.all(np.isfinite(fused_scores)):
            raise ValueError("Ensemble computed non-finite anomaly scores.")

        return np.asarray(fused_scores, dtype=np.float64)

    def score_samples_detailed(self, X: pd.DataFrame | np.ndarray) -> dict[str, Any]:
        """
        Compute both fused scores and individual detector component scores.

        Returns
        -------
        dict containing 'fused_scores', 'raw_scores', and 'normalized_scores'.
        """
        if not self.is_fitted_:
            raise RuntimeError(f"{self.__class__.__name__} must be fitted before scoring samples.")

        arr = self._validate_data(X, is_fit=False)
        raw_dict = {}
        norm_dict = {}
        fused = np.zeros(arr.shape[0], dtype=np.float64)

        for name, detector in self.detectors.items():
            raw = detector.score_samples(arr)
            normed = self.normalizers_[name].transform(raw)
            raw_dict[name] = raw
            norm_dict[name] = normed
            fused += self.weights[name] * normed

        return {
            "fused_scores": fused,
            "raw_scores": raw_dict,
            "normalized_scores": norm_dict,
            "weights": self.weights,
        }

    def get_params(self, deep: bool = True) -> dict[str, Any]:
        """Return hyperparameter configuration dictionary."""
        return {
            "normalizer": self.normalizer_name,
            "weights": self.weights,
            "detector_names": list(self.detectors.keys()),
            "random_state": self.random_state,
            "threshold": self.threshold,
            "is_calibrated": self.is_calibrated_,
        }
