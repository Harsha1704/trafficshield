"""
Local Outlier Factor (LOF) Anomaly Detector
===========================================
Version: 1.0 (Milestone 6)

Density-based local outlier detection wrapping scikit-learn's LocalOutlierFactor
configured for novelty detection on unseen unidirectional IP traffic flows.

Key Characteristics:
1. NOVELTY DETECTION: Fitted with novelty=True so that reference local reachability
   densities are learned strictly on training/calibration data and can score unseen flows.
2. SCORE INVERSION: In scikit-learn, score_samples() returns negative outlier factors
   where lower values are more anomalous. This wrapper inverts them via:
       anomaly_score = -raw_score
   guaranteeing higher scores strictly and consistently denote greater anomalousness.
3. SCALING SENSITIVITY: LOF measures distances in feature space. Features MUST be
   scaled (e.g. via TrafficShieldPreprocessor) prior to fitting and scoring.
4. FROZEN THRESHOLDS: Calibrated decision thresholds remain frozen at inference time.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

import numpy as np
import pandas as pd
from sklearn.neighbors import LocalOutlierFactor

from detection.base import BaseDetector

logger = logging.getLogger(__name__)


class LOFDetector(BaseDetector):
    """
    TrafficShield novelty-detection wrapper for Local Outlier Factor (LOF).
    """

    def __init__(
        self,
        n_neighbors: int = 20,
        algorithm: Literal["auto", "ball_tree", "kd_tree", "brute"] = "auto",
        metric: str = "minkowski",
        p: int = 2,
        leaf_size: int = 30,
        contamination: float | Literal["auto"] = "auto",
        n_jobs: int | None = None,
        threshold: float | None = None,
    ) -> None:
        """
        Parameters
        ----------
        n_neighbors : int
            Number of neighbors to use for local reachability density estimation (default: 20).
        algorithm : {"auto", "ball_tree", "kd_tree", "brute"}
            Algorithm used to compute nearest neighbors.
        metric : str
            Metric to use for distance computation (default: 'minkowski' with p=2).
        p : int
            Parameter for Minkowski metric (p=2 corresponds to Euclidean distance).
        leaf_size : int
            Leaf size passed to BallTree or KDTree.
        contamination : float or "auto"
            Estimated proportion of outliers in the training set (default: 'auto').
            Never tune contamination using ground-truth attack labels!
        n_jobs : int or None
            Number of parallel jobs to run for neighbors search.
        threshold : float or None
            Decision threshold above which an observation is classified anomalous.
        """
        super().__init__(threshold=threshold)
        if n_neighbors < 1:
            raise ValueError(f"n_neighbors must be >= 1, got {n_neighbors}")

        self.n_neighbors = n_neighbors
        self.algorithm = algorithm
        self.metric = metric
        self.p = p
        self.leaf_size = leaf_size
        self.contamination = contamination
        self.n_jobs = n_jobs

        self.model_: LocalOutlierFactor | None = None

    def fit(
        self,
        X: pd.DataFrame | np.ndarray,
        y: Any = None,
    ) -> LOFDetector:
        """
        Fit the LOF model on training/calibration features only.

        Parameters
        ----------
        X : pd.DataFrame or np.ndarray of shape (n_samples, n_features)
            Eligible training feature matrix.
        y : None
            Ignored. primary training is strictly unsupervised.
        """
        arr = self._validate_data(X, is_fit=True)

        n_samples, n_features = arr.shape
        if n_samples <= self.n_neighbors:
            raise ValueError(
                f"Number of training samples ({n_samples}) must be strictly greater than "
                f"n_neighbors ({self.n_neighbors}) to compute local outlier factors."
            )

        self.model_ = LocalOutlierFactor(
            n_neighbors=self.n_neighbors,
            algorithm=self.algorithm,
            metric=self.metric,
            p=self.p,
            leaf_size=self.leaf_size,
            contamination=self.contamination,
            novelty=True,  # Crucial: enables out-of-sample scoring of unseen flows
            n_jobs=self.n_jobs,
        )

        self.model_.fit(arr)
        self.is_fitted_ = True

        logger.debug(
            "Fitted LOFDetector with %d neighbors on %d samples, %d features.",
            self.n_neighbors, n_samples, n_features,
        )
        return self

    def score_samples_raw(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        """
        Return the raw scikit-learn LocalOutlierFactor scores.

        Note: In scikit-learn, lower raw scores denote greater anomalousness.
        """
        if not self.is_fitted_ or self.model_ is None:
            raise RuntimeError("LOFDetector must be fitted before scoring samples.")

        arr = self._validate_data(X, is_fit=False)
        return np.asarray(self.model_.score_samples(arr), dtype=np.float64)

    def score_samples(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        """
        Return continuous anomaly scores where HIGHER strictly indicates MORE ANOMALOUS.

        Computed as: anomaly_score = -raw_score
        """
        raw_scores = self.score_samples_raw(X)
        inverted_scores = -raw_scores
        return np.asarray(inverted_scores, dtype=np.float64)

    def get_params(self, deep: bool = True) -> dict[str, Any]:
        """Return hyperparameter dictionary."""
        return {
            "n_neighbors": self.n_neighbors,
            "algorithm": self.algorithm,
            "metric": self.metric,
            "p": self.p,
            "leaf_size": self.leaf_size,
            "contamination": self.contamination,
            "threshold": self.threshold,
        }
