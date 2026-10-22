"""
TrafficShield Common Detector Interface
========================================
Version: 1.0 (Milestone 4)

Defines the abstract base class and common contracts for all TrafficShield
anomaly detection models.

Guarantees:
1. CONSISTENT SCORE CONVENTION: Higher scores strictly and consistently indicate
   greater anomaly across all detectors.
2. FINITE SCORES: Valid inputs produce finite, non-NaN, non-Inf anomaly scores.
3. ZERO LEAKAGE: Rejects prohibited reverse-direction features and evaluation labels
   before fitting or scoring.
4. IMMUTABLE PARAMETERS AT INFERENCE: Detectors are strictly read-only during scoring.
   Parameters are never refitted or updated on test/inference data.
5. DETERMINISTIC FEATURE SCHEMA: Enforces column names and ordering compatibility
   between fitting and inference.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import numpy as np
import pandas as pd

from features.policy import (
    PolicyViolationError,
    audit_columns,
)


class BaseDetector(ABC):
    """
    Abstract base class for all TrafficShield anomaly detectors.
    """

    def __init__(self, threshold: float | None = None) -> None:
        self.threshold: float | None = threshold
        self.threshold_: float | None = threshold
        self.is_fitted_: bool = False
        self.feature_names_in_: list[str] = []
        self.n_features_in_: int = 0

    def _validate_data(
        self,
        X: pd.DataFrame | np.ndarray,
        is_fit: bool = False,
    ) -> np.ndarray:
        """
        Validate input data format, feature names, column ordering, and policy rules.

        Parameters
        ----------
        X : pd.DataFrame or np.ndarray
            Input features to validate.
        is_fit : bool
            True if called during fit(), False if called during inference.

        Returns
        -------
        np.ndarray of shape (n_samples, n_features) with dtype float64.
        """
        if isinstance(X, np.ndarray):
            if X.size == 0 or X.shape[0] == 0:
                raise ValueError("Input feature array is empty.")
            arr = np.asarray(X, dtype=np.float64)
            if not np.all(np.isfinite(arr)):
                raise ValueError("Input array contains non-finite values (NaN or Inf).")

            if is_fit:
                self.feature_names_in_ = [f"feature_{i}" for i in range(arr.shape[1])]
                self.n_features_in_ = arr.shape[1]
            else:
                if arr.shape[1] != self.n_features_in_:
                    raise ValueError(
                        f"Input has {arr.shape[1]} features, but detector was fitted with {self.n_features_in_} features."
                    )
            return arr

        elif isinstance(X, pd.DataFrame):
            if X.empty or len(X) == 0:
                raise ValueError("Input feature DataFrame is empty.")

            # Feature policy audit
            cols = list(X.columns)
            audit = audit_columns(cols)
            if not audit.is_clean:
                errors: list[str] = []
                if audit.forbidden_violations:
                    errors.append(f"Forbidden reverse-dependent columns: {audit.forbidden_violations}")
                if audit.label_violations:
                    errors.append(f"Evaluation label columns cannot be model input: {audit.label_violations}")
                raise PolicyViolationError("; ".join(errors))

            # Disallow identifiers and timestamps in strict detector input
            if audit.excluded_columns:
                non_feature_cols = [
                    c for c, desc in audit.excluded_columns.items()
                    if not desc.startswith("Unregistered")
                ]
                if non_feature_cols:
                    raise PolicyViolationError(
                        f"Ineligible non-feature columns passed to detector: {non_feature_cols}. "
                        "Only numeric model features may enter detector algorithms."
                    )

            if is_fit:
                self.feature_names_in_ = list(X.columns)
                self.n_features_in_ = len(self.feature_names_in_)
                df_ordered = X
            else:
                # Enforce exact column schema and ordering
                missing_cols = set(self.feature_names_in_) - set(X.columns)
                if missing_cols:
                    raise ValueError(f"Input is missing fitted feature columns: {sorted(missing_cols)}")
                df_ordered = X[self.feature_names_in_]

            # Verify all columns can be converted to float64
            non_numeric: list[str] = []
            for col in self.feature_names_in_:
                if not pd.api.types.is_numeric_dtype(df_ordered[col]):
                    non_numeric.append(col)

            if non_numeric:
                raise ValueError(
                    f"Detector received non-numeric columns: {non_numeric}. "
                    "Categorical features must be encoded (e.g. via TrafficShieldPreprocessor) "
                    "before passing to anomaly detectors."
                )

            arr = df_ordered.to_numpy(dtype=np.float64)
            if not np.all(np.isfinite(arr)):
                raise ValueError("Input DataFrame contains non-finite values (NaN or Inf).")
            return np.asarray(arr, dtype=np.float64)

        else:
            raise TypeError(f"Expected pandas DataFrame or numpy ndarray, got {type(X)}")

    @abstractmethod
    def fit(self, X: pd.DataFrame | np.ndarray, y: Any = None) -> BaseDetector:
        """
        Fit detector parameters on training/calibration features only.

        Parameters
        ----------
        X : pd.DataFrame or np.ndarray of shape (n_samples, n_features)
            Eligible training feature matrix.
        y : None
            Ignored. primary training is unsupervised.
        """
        pass

    @abstractmethod
    def score_samples(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        """
        Compute continuous anomaly scores for observations.

        Returns
        -------
        np.ndarray of shape (n_samples,) where HIGHER values strictly indicate
        GREATER anomalousness.
        """
        pass

    def predict(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        """
        Predict binary anomaly indicators: 1 for anomaly, 0 for normal.

        Requires an established decision threshold.
        """
        if not self.is_fitted_:
            raise RuntimeError(f"{self.__class__.__name__} must be fit before calling predict().")

        if self.threshold_ is None:
            raise ValueError(
                "No decision threshold has been established. "
                "Set a threshold explicitly or use calibrate_threshold()."
            )

        scores = self.score_samples(X)
        return (scores >= self.threshold_).astype(int)

    def set_threshold(self, threshold: float) -> None:
        """Explicitly set a decision threshold."""
        if not np.isfinite(threshold):
            raise ValueError(f"Threshold must be a finite float, got {threshold}")
        self.threshold_ = float(threshold)

    def calibrate_threshold(
        self,
        calibration_scores: np.ndarray,
        quantile: float = 0.99,
    ) -> float:
        """
        Calibrate and freeze a decision threshold from calibration scores.

        Parameters
        ----------
        calibration_scores : np.ndarray
            Anomaly scores computed on the historical calibration partition.
        quantile : float
            Quantile cutoff in (0, 1), e.g. 0.99 for 99th percentile.

        Returns
        -------
        The established threshold value.
        """
        if not (0.0 < quantile < 1.0):
            raise ValueError(f"Quantile must be in (0, 1), got {quantile}")
        if len(calibration_scores) == 0:
            raise ValueError("Calibration scores array is empty.")

        thresh = float(np.percentile(calibration_scores, quantile * 100.0))
        self.set_threshold(thresh)
        return thresh

    @abstractmethod
    def get_params(self, deep: bool = True) -> dict[str, Any]:
        """Return hyperparameter configuration dictionary."""
        pass
