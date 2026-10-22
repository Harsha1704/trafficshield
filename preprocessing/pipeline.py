"""
TrafficShield Preprocessing Pipeline
====================================
Version: 1.0 (Milestone 3)

Reusable, leakage-preventing preprocessing pipeline designed for unidirectional
network traffic anomaly detection.

Guarantees:
1. TRAIN-ONLY FITTING: All scalers, imputers, and encoders are fit strictly on
   training data. Test/inference data NEVER updates pipeline parameters.
2. ZERO LEAKAGE ENFORCEMENT: Rejects forbidden reverse-direction features and
   ground-truth attack labels before fitting or transforming.
3. DETERMINISTIC REPRODUCIBILITY: Preserves deterministic column ordering and
   consistent feature names regardless of incoming column permutation.
4. UNSEEN CATEGORY RESILIENCE: Unknown categories observed at inference time
   are mapped to zero vectors without raising runtime exceptions.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import MinMaxScaler, OneHotEncoder, RobustScaler, StandardScaler

from features.policy import (
    DataType,
    PolicyViolationError,
    audit_columns,
    get_field_spec,
)

logger = logging.getLogger(__name__)


class TrafficShieldPreprocessor(BaseEstimator, TransformerMixin):
    """
    Standardized scikit-learn compatible preprocessor for TrafficShield.

    Handles numeric imputation, feature scaling, and categorical encoding
    with strict train-only fitting and automated leakage prevention.
    """

    def __init__(
        self,
        scaler: str | None = "standard",
        impute_strategy: str = "median",
        strict_policy: bool = True,
        handle_unknown_categories: str = "ignore",
    ) -> None:
        """
        Parameters
        ----------
        scaler : {"standard", "robust", "minmax", "none", None}
            Feature scaling technique applied to numeric features.
        impute_strategy : {"median", "mean", "zero"}
            Imputation strategy for missing numerical measurements.
        strict_policy : bool
            If True, raises PolicyViolationError when non-eligible, forbidden,
            or label columns are present. If False, silently filters them out.
        handle_unknown_categories : {"ignore", "error"}
            Handling of unobserved categorical values at inference.
        """
        self.scaler = scaler
        self.impute_strategy = impute_strategy
        self.strict_policy = strict_policy
        self.handle_unknown_categories = handle_unknown_categories

        # Fitted attributes
        self.is_fitted_: bool = False
        self.feature_names_in_: list[str] = []
        self.numeric_features_: list[str] = []
        self.categorical_features_: list[str] = []
        self.boolean_features_: list[str] = []
        self.feature_names_out_: list[str] = []

        # Sub-transformers
        self._numeric_imputer: SimpleImputer | None = None
        self._scaler_transformer: StandardScaler | RobustScaler | MinMaxScaler | None = None
        self._categorical_imputer: SimpleImputer | None = None
        self._categorical_encoder: OneHotEncoder | None = None
        self._boolean_imputer: SimpleImputer | None = None

    def _validate_input_columns(self, columns: list[str]) -> list[str]:
        """Validate and filter input columns according to the feature policy."""
        audit = audit_columns(columns)

        if not audit.is_clean:
            errors = []
            if audit.forbidden_violations:
                errors.append(f"Forbidden reverse-dependent columns detected: {audit.forbidden_violations}")
            if audit.label_violations:
                errors.append(f"Ground-truth label columns detected in feature input: {audit.label_violations}")
            raise PolicyViolationError("; ".join(errors))

        if self.strict_policy and audit.excluded_columns:
            non_features = list(audit.excluded_columns.keys())
            raise PolicyViolationError(
                f"Proposed input contains ineligible columns in strict mode: {non_features}. "
                "Only columns with FieldRole.FEATURE are permitted."
            )

        return audit.eligible_features

    def _categorize_feature(self, col: str) -> str:
        """Determine whether an eligible feature is numeric, categorical, or boolean."""
        spec = get_field_spec(col)
        if spec:
            if spec.data_type == DataType.CATEGORICAL:
                return "categorical"
            elif spec.data_type == DataType.BOOLEAN:
                return "boolean"
            else:
                return "numeric"
        return "numeric"

    def fit(self, X: pd.DataFrame | np.ndarray, y: Any = None) -> TrafficShieldPreprocessor:
        """
        Fit imputers, scalers, and encoders STRICTLY on training observations.

        Parameters
        ----------
        X : pd.DataFrame or np.ndarray of shape (n_samples, n_features)
            Training data containing only eligible features.
        y : None
            Ignored. primary training is unsupervised.
        """
        if isinstance(X, np.ndarray):
            if X.size == 0 or X.shape[0] == 0:
                raise ValueError("Cannot fit on empty training array.")
            # If array, generate synthetic feature names
            df = pd.DataFrame(X, columns=[f"feature_{i}" for i in range(X.shape[1])])
        elif isinstance(X, pd.DataFrame):
            if X.empty or len(X) == 0:
                raise ValueError("Cannot fit on empty training DataFrame.")
            df = X.copy()
        else:
            raise TypeError(f"Expected pandas DataFrame or numpy ndarray, got {type(X)}")

        # Audit and validate columns
        valid_cols = self._validate_input_columns(list(df.columns))
        if not valid_cols:
            raise ValueError("No eligible feature columns available for fitting.")

        df = df[valid_cols]
        self.feature_names_in_ = list(valid_cols)

        # Categorize features
        self.numeric_features_ = []
        self.categorical_features_ = []
        self.boolean_features_ = []

        for col in self.feature_names_in_:
            kind = self._categorize_feature(col)
            if kind == "categorical":
                self.categorical_features_.append(col)
            elif kind == "boolean":
                self.boolean_features_.append(col)
            else:
                self.numeric_features_.append(col)

        # ── 1. Fit Numeric Transformers ───────────────────────────────────────
        if self.numeric_features_:
            num_data = df[self.numeric_features_].apply(pd.to_numeric, errors="coerce")
            strat = "median" if self.impute_strategy == "median" else ("mean" if self.impute_strategy == "mean" else "constant")
            fill_val = 0.0 if strat == "constant" else None
            self._numeric_imputer = SimpleImputer(strategy=strat, fill_value=fill_val)
            imputed_num = self._numeric_imputer.fit_transform(num_data)

            if self.scaler == "standard":
                self._scaler_transformer = StandardScaler()
            elif self.scaler == "robust":
                self._scaler_transformer = RobustScaler()
            elif self.scaler == "minmax":
                self._scaler_transformer = MinMaxScaler()
            elif self.scaler in (None, "none"):
                self._scaler_transformer = None
            else:
                raise ValueError(f"Unknown scaler type: '{self.scaler}'. Must be standard, robust, minmax, or none.")

            if self._scaler_transformer is not None:
                self._scaler_transformer.fit(imputed_num)

        # ── 2. Fit Boolean Transformers ───────────────────────────────────────
        if self.boolean_features_:
            bool_data = df[self.boolean_features_].astype(float)
            self._boolean_imputer = SimpleImputer(strategy="constant", fill_value=0.0)
            self._boolean_imputer.fit(bool_data)

        # ── 3. Fit Categorical Transformers ───────────────────────────────────
        if self.categorical_features_:
            cat_data = df[self.categorical_features_].astype(str).fillna("missing")
            self._categorical_imputer = SimpleImputer(strategy="constant", fill_value="missing")
            imputed_cat = self._categorical_imputer.fit_transform(cat_data)

            self._categorical_encoder = OneHotEncoder(
                handle_unknown=self.handle_unknown_categories,
                sparse_output=False,
            )
            self._categorical_encoder.fit(imputed_cat)

        # ── 4. Deterministic Feature Names Out ─────────────────────────────────
        out_names: list[str] = []
        out_names.extend(self.numeric_features_)
        out_names.extend(self.boolean_features_)
        if self._categorical_encoder is not None:
            encoded_names = list(self._categorical_encoder.get_feature_names_out(self.categorical_features_))
            out_names.extend(encoded_names)

        self.feature_names_out_ = out_names
        self.is_fitted_ = True
        return self

    def transform(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        """
        Transform observations into a clean, normalized numeric feature matrix.

        Guarantees that pipeline parameters (means, scales, categories) are
        NEVER updated during transformation.
        """
        if not self.is_fitted_:
            raise RuntimeError("TrafficShieldPreprocessor must be fit before calling transform().")

        if isinstance(X, np.ndarray):
            df = pd.DataFrame(X, columns=self.feature_names_in_)
        elif isinstance(X, pd.DataFrame):
            df = X.copy()
        else:
            raise TypeError(f"Expected pandas DataFrame or numpy ndarray, got {type(X)}")

        # Leakage audit on test/inference input
        audit = audit_columns(list(df.columns))
        if not audit.is_clean:
            errors = []
            if audit.forbidden_violations:
                errors.append(f"Forbidden reverse-dependent columns in inference input: {audit.forbidden_violations}")
            if audit.label_violations:
                errors.append(f"Label columns present in inference input: {audit.label_violations}")
            raise PolicyViolationError("; ".join(errors))

        # Align columns to feature_names_in_ (handles reordered columns and missing columns safely)
        for expected_col in self.feature_names_in_:
            if expected_col not in df.columns:
                df[expected_col] = np.nan

        blocks: list[np.ndarray] = []

        # 1. Transform Numeric Features
        if self.numeric_features_:
            num_data = df[self.numeric_features_].apply(pd.to_numeric, errors="coerce")
            assert self._numeric_imputer is not None
            num_imputed = self._numeric_imputer.transform(num_data)
            if self._scaler_transformer is not None:
                num_scaled = self._scaler_transformer.transform(num_imputed)
            else:
                num_scaled = num_imputed
            blocks.append(num_scaled)

        # 2. Transform Boolean Features
        if self.boolean_features_:
            bool_data = df[self.boolean_features_].astype(float)
            assert self._boolean_imputer is not None
            bool_imputed = self._boolean_imputer.transform(bool_data)
            blocks.append(bool_imputed)

        # 3. Transform Categorical Features
        if self.categorical_features_:
            cat_data = df[self.categorical_features_].astype(str).fillna("missing")
            assert self._categorical_imputer is not None
            assert self._categorical_encoder is not None
            cat_imputed = self._categorical_imputer.transform(cat_data)
            cat_encoded = self._categorical_encoder.transform(cat_imputed)
            blocks.append(cat_encoded)

        if not blocks:
            return np.empty((len(df), 0), dtype=np.float64)

        result = np.hstack(blocks).astype(np.float64)
        # Ensure finite values
        result = np.nan_to_num(result, nan=0.0, posinf=0.0, neginf=0.0)
        return result

    def transform_df(self, X: pd.DataFrame) -> pd.DataFrame:
        """
        Transform observations and return a DataFrame with named columns and index.
        """
        arr = self.transform(X)
        return pd.DataFrame(arr, columns=self.feature_names_out_, index=X.index)

    def get_feature_names_out(self, input_features: Any = None) -> list[str]:
        """Return the deterministic list of output feature names."""
        if not self.is_fitted_:
            raise RuntimeError("Preprocessor has not been fitted.")
        return list(self.feature_names_out_)

    def get_params(self, deep: bool = True) -> dict[str, Any]:
        """Return hyperparameters for scikit-learn compatibility."""
        return {
            "scaler": self.scaler,
            "impute_strategy": self.impute_strategy,
            "strict_policy": self.strict_policy,
            "handle_unknown_categories": self.handle_unknown_categories,
        }

    def set_params(self, **params: Any) -> TrafficShieldPreprocessor:
        """Set hyperparameters for scikit-learn compatibility."""
        for key, value in params.items():
            if hasattr(self, key):
                setattr(self, key, value)
            else:
                raise ValueError(f"Invalid parameter {key} for TrafficShieldPreprocessor")
        return self
