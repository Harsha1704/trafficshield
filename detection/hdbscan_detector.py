"""
HDBSCAN Density-Based Anomaly Detector
======================================
Version: 1.0 (Milestone 6)

Density-based clustering and outlier detection wrapping scikit-learn's HDBSCAN.

Key Characteristics:
1. CLUSTERING & DENSITY SEMANTICS: Identifies dense clusters of normal traffic patterns
   and treats low-density boundary points and noise as potential anomalies.
2. GLOSH SCORING (IN-SAMPLE): Training observations receive native Global-Local Outlier
   Score from Hierarchies (GLOSH) in [0, 1], where 1.0 is maximum outlierness.
3. OUT-OF-SAMPLE DENSITY SCORING: Scikit-learn's HDBSCAN implementation does not provide
   a native hierarchical prediction tree for unseen points. For out-of-sample inference,
   this detector computes the standardized distance to the nearest cluster medoid/core,
   documenting this as an approximate density-distance metric.
4. UNIFIED CONVENTION: Higher scores strictly indicate greater anomaly.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

import numpy as np
import pandas as pd
from sklearn.cluster import HDBSCAN

from detection.base import BaseDetector

logger = logging.getLogger(__name__)


class HDBSCANDetector(BaseDetector):
    """
    TrafficShield wrapper for HDBSCAN density and cluster anomaly detection.
    """

    def __init__(
        self,
        min_cluster_size: int = 5,
        min_samples: int | None = None,
        metric: str = "euclidean",
        cluster_selection_epsilon: float = 0.0,
        cluster_selection_method: Literal["eom", "leaf"] = "eom",
        threshold: float | None = None,
    ) -> None:
        """
        Parameters
        ----------
        min_cluster_size : int
            Minimum number of samples in a group for that group to be considered a cluster.
        min_samples : int or None
            Number of samples in a neighborhood for a point to be considered a core point.
        metric : str
            Distance metric used for cluster computation (default: 'euclidean').
        cluster_selection_epsilon : float
            Distance threshold below which clusters are not separated.
        cluster_selection_method : {"eom", "leaf"}
            Cluster selection algorithm ('eom' for Excess of Mass, 'leaf' for finest clusters).
        threshold : float or None
            Decision threshold above which an observation is classified anomalous.
        """
        super().__init__(threshold=threshold)
        if min_cluster_size < 2:
            raise ValueError(f"min_cluster_size must be >= 2, got {min_cluster_size}")

        self.min_cluster_size = min_cluster_size
        self.min_samples = min_samples
        self.metric = metric
        self.cluster_selection_epsilon = cluster_selection_epsilon
        self.cluster_selection_method = cluster_selection_method

        self.model_: HDBSCAN | None = None
        self.medoids_: np.ndarray | None = None
        self.train_outlier_scores_: np.ndarray | None = None
        self.labels_: np.ndarray | None = None
        self.n_clusters_: int = 0
        self._ref_scale: float = 1.0

    def fit(
        self,
        X: pd.DataFrame | np.ndarray,
        y: Any = None,
    ) -> HDBSCANDetector:
        """
        Fit HDBSCAN clusters on training/calibration features only.

        Parameters
        ----------
        X : pd.DataFrame or np.ndarray of shape (n_samples, n_features)
            Eligible training feature matrix.
        y : None
            Ignored. clustering is strictly unsupervised.
        """
        arr = self._validate_data(X, is_fit=True)

        n_samples, n_features = arr.shape
        if n_samples < self.min_cluster_size:
            raise ValueError(
                f"Number of training samples ({n_samples}) must be >= min_cluster_size ({self.min_cluster_size})."
            )

        self.model_ = HDBSCAN(
            min_cluster_size=self.min_cluster_size,
            min_samples=self.min_samples,
            metric=self.metric,
            cluster_selection_epsilon=self.cluster_selection_epsilon,
            cluster_selection_method=self.cluster_selection_method,
            copy=True,
            store_centers="both",
        )

        self.model_.fit(arr)
        self.labels_ = self.model_.labels_
        # In sklearn.cluster.HDBSCAN, probabilities_ measures cluster membership strength in [0, 1].
        # In-sample outlierness is derived as (1.0 - probabilities_), where 1.0 = maximal noise/outlier.
        if hasattr(self.model_, "probabilities_") and self.model_.probabilities_ is not None:
            self.train_outlier_scores_ = 1.0 - np.asarray(self.model_.probabilities_, dtype=np.float64)
        else:
            self.train_outlier_scores_ = np.zeros(n_samples, dtype=np.float64)

        unique_labels = set(self.labels_) - {-1}
        self.n_clusters_ = len(unique_labels)

        # Store cluster medoids for out-of-sample distance computation
        if hasattr(self.model_, "medoids_") and self.model_.medoids_ is not None and len(self.model_.medoids_) > 0:
            self.medoids_ = np.asarray(self.model_.medoids_, dtype=np.float64)
        else:
            # Fallback: compute medoids manually per cluster
            if self.n_clusters_ > 0:
                med_list = []
                for lab in unique_labels:
                    cluster_pts = arr[self.labels_ == lab]
                    med_list.append(np.median(cluster_pts, axis=0))
                self.medoids_ = np.asarray(med_list, dtype=np.float64)
            else:
                # All training points were classified as noise
                self.medoids_ = np.median(arr, axis=0, keepdims=True)

        # Compute characteristic scale (mean inter-medoid or cluster spread)
        diffs = arr - np.median(arr, axis=0)
        mad = float(np.median(np.abs(diffs)))
        self._ref_scale = max(1e-6, mad * 1.4826)

        self.is_fitted_ = True
        logger.debug(
            "Fitted HDBSCANDetector on %d samples: found %d clusters, %d noise points.",
            n_samples, self.n_clusters_, int(np.sum(self.labels_ == -1)),
        )
        return self

    def score_samples(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        """
        Compute anomaly scores where HIGHER strictly indicates MORE ANOMALOUS.

        For unseen observations, computes standardized distance to the nearest cluster core.
        """
        if not self.is_fitted_ or self.medoids_ is None:
            raise RuntimeError("HDBSCANDetector must be fitted before scoring samples.")

        arr = self._validate_data(X, is_fit=False)
        n_samples = arr.shape[0]

        # Compute Euclidean distance from each sample to each cluster medoid
        # shape: (n_samples, n_clusters)
        scores = np.zeros(n_samples, dtype=np.float64)

        for i in range(n_samples):
            # Distances to all cluster cores
            dists = np.linalg.norm(self.medoids_ - arr[i], axis=1)
            # Minimum distance to nearest normal cluster
            min_dist = float(np.min(dists))
            # Standardize by baseline scale
            scores[i] = min_dist / self._ref_scale

        return np.asarray(scores, dtype=np.float64)

    def get_params(self, deep: bool = True) -> dict[str, Any]:
        """Return hyperparameter dictionary."""
        return {
            "min_cluster_size": self.min_cluster_size,
            "min_samples": self.min_samples,
            "metric": self.metric,
            "cluster_selection_epsilon": self.cluster_selection_epsilon,
            "cluster_selection_method": self.cluster_selection_method,
            "threshold": self.threshold,
        }
