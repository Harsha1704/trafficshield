"""
Isolation Forest Anomaly Detector
=================================
Version: 1.0 (Milestone 4)

Unsupervised tree-based anomaly detector wrapping scikit-learn's IsolationForest
for unidirectional IP traffic flows.

Key Characteristics:
1. CONSISTENT SCORE DIRECTION: Scikit-learn's native score_samples() returns negative
   values where lower is more anomalous. This wrapper converts scores via:
       anomaly_score = -raw_score
   ensuring higher scores strictly and consistently indicate greater anomalousness.
2. RAW DIAGNOSTIC ACCESS: Provides score_samples_raw() alongside score_samples()
   for debugging and model diagnostics.
3. REPRODUCIBLE SEEDING: Defaults to random_state=42 for deterministic results.
4. STRICT SCHEMA VALIDATION: Verifies column presence and ordering between fit and inference.
5. FROZEN THRESHOLDS: Calibrated decision thresholds are derived from training/calibration
   quantiles and remain frozen at inference time.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from detection.base import BaseDetector

logger = logging.getLogger(__name__)


class IsolationForestDetector(BaseDetector):
    """
    TrafficShield wrapper for scikit-learn's IsolationForest algorithm.
    """

    def __init__(
        self,
        n_estimators: int = 100,
        max_samples: int | float | Literal["auto"] = "auto",
        contamination: float | Literal["auto"] = "auto",
        max_features: int | float = 1.0,
        random_state: int | None = 42,
        n_jobs: int | None = None,
        threshold: float | None = None,
    ) -> None:
        """
        Parameters
        ----------
        n_estimators : int
            Number of base isolation trees in the ensemble.
        max_samples : int, float, or "auto"
            Number of samples drawn from training data to train each tree.
        contamination : float or "auto"
            Expected proportion of outliers in the training set (default: 'auto').
            Never tune contamination using ground-truth attack labels!
        max_features : int or float
            Number of features drawn to train each tree.
        random_state : int or None
            Random seed for reproducible forest construction (default: 42).
        n_jobs : int or None
            Number of CPU cores for parallel tree building.
        threshold : float or None
            Decision threshold above which an observation is classified anomalous.
        """
        super().__init__(threshold=threshold)
        self.n_estimators = n_estimators
        self.max_samples = max_samples
        self.contamination = contamination
        self.max_features = max_features
        self.random_state = random_state
        self.n_jobs = n_jobs

        self.model_: IsolationForest | None = None

    def fit(
        self,
        X: pd.DataFrame | np.ndarray,
        y: Any = None,
    ) -> IsolationForestDetector:
        """
        Fit the isolation forest on training/calibration features only.

        Parameters
        ----------
        X : pd.DataFrame or np.ndarray of shape (n_samples, n_features)
            Eligible training feature matrix.
        y : None
            Ignored. primary training is strictly unsupervised.
        """
        arr = self._validate_data(X, is_fit=True)

        self.model_ = IsolationForest(
            n_estimators=self.n_estimators,
            max_samples=self.max_samples,
            contamination=self.contamination,
            max_features=self.max_features,
            random_state=self.random_state,
            n_jobs=self.n_jobs,
        )

        self.model_.fit(arr)
        self.is_fitted_ = True

        logger.debug(
            "Fitted IsolationForestDetector with %d estimators on %d samples, %d features.",
            self.n_estimators, arr.shape[0], arr.shape[1],
        )
        return self

    def score_samples_raw(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        """
        Return the raw scikit-learn IsolationForest scores.

        Note: In scikit-learn, lower raw scores denote greater anomalousness.
        """
        if not self.is_fitted_ or self.model_ is None:
            raise RuntimeError("IsolationForestDetector must be fitted before scoring samples.")

        arr = self._validate_data(X, is_fit=False)
        return np.asarray(self.model_.score_samples(arr), dtype=np.float64)

    def score_samples(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        """
        Return continuous anomaly scores where HIGHER strictly indicates MORE ANOMALOUS.

        Computed as: anomaly_score = -raw_score
        """
        raw_scores = self.score_samples_raw(X)
        # Invert score direction so higher = more anomalous
        inverted_scores = -raw_scores
        return np.asarray(inverted_scores, dtype=np.float64)

    def get_params(self, deep: bool = True) -> dict[str, Any]:
        """Return hyperparameter dictionary."""
        return {
            "n_estimators": self.n_estimators,
            "max_samples": self.max_samples,
            "contamination": self.contamination,
            "max_features": self.max_features,
            "random_state": self.random_state,
            "n_jobs": self.n_jobs,
            "threshold": self.threshold,
        }
