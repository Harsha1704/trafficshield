"""
Statistical Drift Engine & Data Quality Verification
=====================================================
Milestone 12 — Intelligent Monitoring, Drift Detection & Model Lifecycle

Implements mathematically sound, explainable drift detection:
- Population Stability Index (PSI) using quantile binning with Laplace smoothing
- Two-sample Kolmogorov-Smirnov (KS) test for continuous distribution shift
- Wasserstein Distance (Earth Mover's Distance)
- Sample size safeguards (N < min_sample_size flagged as INSUFFICIENT_DATA)
- Input data quality, missingness, and range boundary auditing
- Non-causal disclaimer: Statistical shift detects covariate/concept drift, NOT proof of attack
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import ks_2samp, wasserstein_distance

from monitoring.schema import DriftMetricType, DriftStatus, FeatureDriftResult

logger = logging.getLogger("drift_engine")

# Default thresholds recommended by industry credit/risk and ML monitoring literature
DEFAULT_PSI_WARNING_THRESHOLD = 0.10
DEFAULT_PSI_CRITICAL_THRESHOLD = 0.25
DEFAULT_KS_STAT_THRESHOLD = 0.15
DEFAULT_KS_PVALUE_THRESHOLD = 0.01
DEFAULT_MIN_SAMPLE_SIZE = 30


def calculate_psi(
    baseline_values: np.ndarray,
    current_values: np.ndarray,
    bins: int = 10,
    epsilon: float = 1e-4,
    bin_edges: list[float] | None = None,
) -> float:
    """
    Calculate Population Stability Index (PSI) with quantile-based binning.

    PSI = sum((Actual% - Expected%) * ln(Actual% / Expected%))

    Laplace smoothing with epsilon prevents division by zero or ln(0)
    when current data contains empty bins.
    """
    base = np.asarray(baseline_values, dtype=float)
    curr = np.asarray(current_values, dtype=float)

    # Filter out NaNs/infs for robust calculation
    base = base[np.isfinite(base)]
    curr = curr[np.isfinite(curr)]

    if len(base) == 0 or len(curr) == 0:
        return 0.0

    if bin_edges is None:
        # Quantile decile edges from baseline
        quantiles = np.linspace(0, 100, bins + 1)
        edges = np.unique(np.percentile(base, quantiles))
        if len(edges) < 2:
            edges = np.array([float(np.min(base)) - 1.0, float(np.max(base)) + 1.0])
    else:
        edges = np.unique(np.asarray(bin_edges, dtype=float))
        if len(edges) < 2:
            edges = np.array([float(np.min(base)) - 1.0, float(np.max(base)) + 1.0])

    # Extend boundaries to cover full range
    edges[0] = -np.inf
    edges[-1] = np.inf

    # Calculate bin counts
    base_counts, _ = np.histogram(base, bins=edges)
    curr_counts, _ = np.histogram(curr, bins=edges)

    n_bins = len(base_counts)
    if n_bins == 0:
        return 0.0

    # Smooth proportions
    q = (base_counts + epsilon) / (np.sum(base_counts) + epsilon * n_bins)
    p = (curr_counts + epsilon) / (np.sum(curr_counts) + epsilon * n_bins)

    psi_val = np.sum((p - q) * np.log(p / q))
    return float(max(0.0, psi_val))


def calculate_ks(
    baseline_values: np.ndarray,
    current_values: np.ndarray,
) -> tuple[float, float]:
    """
    Two-sample Kolmogorov-Smirnov test.

    Returns:
        (statistic, p_value): KS maximum vertical distance D and asymptotic p-value.
    """
    base = np.asarray(baseline_values, dtype=float)
    curr = np.asarray(current_values, dtype=float)

    base = base[np.isfinite(base)]
    curr = curr[np.isfinite(curr)]

    if len(base) == 0 or len(curr) == 0:
        return 0.0, 1.0

    res = ks_2samp(base, curr)
    return float(res.statistic), float(res.pvalue)


def calculate_wasserstein(
    baseline_values: np.ndarray,
    current_values: np.ndarray,
) -> float:
    """Calculate first Wasserstein distance (Earth Mover's Distance)."""
    base = np.asarray(baseline_values, dtype=float)
    curr = np.asarray(current_values, dtype=float)

    base = base[np.isfinite(base)]
    curr = curr[np.isfinite(curr)]

    if len(base) == 0 or len(curr) == 0:
        return 0.0

    return float(wasserstein_distance(base, curr))


def evaluate_feature_drift(
    baseline_profile: dict[str, Any],
    current_df: pd.DataFrame,
    features: list[str],
    min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
    psi_warning: float = DEFAULT_PSI_WARNING_THRESHOLD,
    psi_critical: float = DEFAULT_PSI_CRITICAL_THRESHOLD,
    ks_threshold: float = DEFAULT_KS_STAT_THRESHOLD,
    ks_pvalue: float = DEFAULT_KS_PVALUE_THRESHOLD,
) -> list[FeatureDriftResult]:
    """
    Evaluate feature distribution shift for all active features.

    Applies strict sample size safeguards and returns explanatory reasons.
    """
    results: list[FeatureDriftResult] = []
    feat_baselines = baseline_profile.get("feature_baselines", {})

    for feat in features:
        if feat not in current_df.columns:
            continue

        raw_col = current_df[feat]
        curr_vals = pd.to_numeric(raw_col, errors="coerce").dropna().values
        curr_valid_n = len(curr_vals)

        # Baseline parameters
        base_meta = feat_baselines.get(feat, {})
        base_mean = float(base_meta.get("mean", 0.0))
        base_std = float(base_meta.get("std", 1.0))
        base_deciles = base_meta.get("deciles", None)

        curr_mean = float(np.mean(curr_vals)) if curr_valid_n > 0 else 0.0
        curr_std = float(np.std(curr_vals)) if curr_valid_n > 1 else 0.0

        # Sample size safeguard
        if curr_valid_n < min_sample_size:
            results.append(
                FeatureDriftResult(
                    feature=feat,
                    metric_type=DriftMetricType.PSI,
                    metric_value=0.0,
                    threshold_warning=psi_warning,
                    threshold_critical=psi_critical,
                    status=DriftStatus.INSUFFICIENT_DATA,
                    p_value=None,
                    baseline_mean=base_mean,
                    current_mean=curr_mean,
                    baseline_std=base_std,
                    current_std=curr_std,
                    sample_size=curr_valid_n,
                    explanation=(
                        f"Sample count (N={curr_valid_n}) is below statistical reliability threshold "
                        f"({min_sample_size}). Drift testing deferred until sufficient flows accumulate."
                    ),
                )
            )
            continue

        # If baseline deciles are present, use them for PSI
        if base_deciles and len(base_deciles) >= 2:
            psi_val = calculate_psi(
                baseline_values=np.array(base_deciles),
                current_values=curr_vals,
                bin_edges=base_deciles,
            )
        else:
            # Fallback if no explicit deciles: synthesize standard baseline
            synthetic_base = np.random.normal(base_mean, max(base_std, 1e-4), size=1000)
            psi_val = calculate_psi(synthetic_base, curr_vals)

        # KS statistic
        if base_deciles:
            # Construct comparison points from baseline deciles
            synthetic_base = np.linspace(base_deciles[0], base_deciles[-1], 200)
            ks_stat, ks_p = calculate_ks(synthetic_base, curr_vals)
        else:
            synthetic_base = np.random.normal(base_mean, max(base_std, 1e-4), size=1000)
            ks_stat, ks_p = calculate_ks(synthetic_base, curr_vals)

        # Determine Drift Status
        if psi_val >= psi_critical or (ks_stat >= 0.35 and ks_p < 0.001):
            status = DriftStatus.CRITICAL
            explanation = (
                f"Severe distribution shift detected (PSI={psi_val:.4f} >= {psi_critical}, KS D={ks_stat:.4f}). "
                f"Mean shifted from {base_mean:.2f} to {curr_mean:.2f} (delta: {curr_mean - base_mean:+.2f})."
            )
        elif psi_val >= psi_warning or (ks_stat >= ks_threshold and ks_p < ks_pvalue):
            status = DriftStatus.WARNING
            explanation = (
                f"Moderate distribution shift detected (PSI={psi_val:.4f} >= {psi_warning}, KS D={ks_stat:.4f}). "
                f"Traffic profile deviating from reference baseline."
            )
        else:
            status = DriftStatus.STABLE
            explanation = f"Distribution is consistent with reference baseline (PSI={psi_val:.4f} < {psi_warning})."

        results.append(
            FeatureDriftResult(
                feature=feat,
                metric_type=DriftMetricType.PSI,
                metric_value=round(psi_val, 4),
                threshold_warning=psi_warning,
                threshold_critical=psi_critical,
                status=status,
                p_value=round(ks_p, 6) if ks_p is not None else None,
                baseline_mean=round(base_mean, 4),
                current_mean=round(curr_mean, 4),
                baseline_std=round(base_std, 4),
                current_std=round(curr_std, 4),
                sample_size=curr_valid_n,
                explanation=explanation,
            )
        )

    return results


def evaluate_score_drift(
    baseline_score_profile: dict[str, Any],
    current_scores: np.ndarray,
    min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
    psi_warning: float = DEFAULT_PSI_WARNING_THRESHOLD,
    psi_critical: float = DEFAULT_PSI_CRITICAL_THRESHOLD,
) -> FeatureDriftResult:
    """
    Evaluate anomaly score distribution drift against reference score deciles.
    """
    scores = np.asarray(current_scores, dtype=float)
    scores = scores[np.isfinite(scores)]
    n = len(scores)

    base_mean = float(baseline_score_profile.get("mean", 0.25))
    base_std = float(baseline_score_profile.get("std", 0.15))
    base_deciles = baseline_score_profile.get("deciles", list(np.linspace(0.0, 1.0, 11)))

    curr_mean = float(np.mean(scores)) if n > 0 else 0.0
    curr_std = float(np.std(scores)) if n > 1 else 0.0

    if n < min_sample_size:
        return FeatureDriftResult(
            feature="anomaly_score",
            metric_type=DriftMetricType.PSI,
            metric_value=0.0,
            threshold_warning=psi_warning,
            threshold_critical=psi_critical,
            status=DriftStatus.INSUFFICIENT_DATA,
            baseline_mean=base_mean,
            current_mean=curr_mean,
            baseline_std=base_std,
            current_std=curr_std,
            sample_size=n,
            explanation=f"Insufficient flow scores (N={n} < {min_sample_size}) for score drift calculation.",
        )

    psi_val = calculate_psi(
        baseline_values=np.array(base_deciles),
        current_values=scores,
        bin_edges=base_deciles,
    )
    ks_stat, ks_p = calculate_ks(np.array(base_deciles), scores)

    if psi_val >= psi_critical:
        status = DriftStatus.CRITICAL
        exp = f"Critical score drift (PSI={psi_val:.4f}). Anomaly prevalence or score calibration departed from baseline."
    elif psi_val >= psi_warning:
        status = DriftStatus.WARNING
        exp = f"Moderate score drift (PSI={psi_val:.4f}). Shift in output probability density profile."
    else:
        status = DriftStatus.STABLE
        exp = f"Anomaly score distribution is stable (PSI={psi_val:.4f} < {psi_warning})."

    return FeatureDriftResult(
        feature="anomaly_score",
        metric_type=DriftMetricType.PSI,
        metric_value=round(psi_val, 4),
        threshold_warning=psi_warning,
        threshold_critical=psi_critical,
        status=status,
        p_value=round(ks_p, 6),
        baseline_mean=round(base_mean, 4),
        current_mean=round(curr_mean, 4),
        baseline_std=round(base_std, 4),
        current_std=round(curr_std, 4),
        sample_size=n,
        explanation=exp,
    )


def check_data_quality(
    df: pd.DataFrame,
    features: list[str],
) -> dict[str, Any]:
    """
    Audit batch data quality: missingness, NaNs, infinities, negative values, and range violations.
    """
    total_rows = len(df)
    missing_by_feature: dict[str, int] = {}
    invalid_by_feature: dict[str, int] = {}
    violations: list[str] = []

    for f in features:
        if f not in df.columns:
            missing_by_feature[f] = total_rows
            violations.append(f"Missing required feature column: '{f}'")
            continue

        col = df[f]
        missing_count = int(col.isna().sum())
        missing_by_feature[f] = missing_count

        # Check numeric types for invalid bounds
        numeric_series = pd.to_numeric(col, errors="coerce")
        nan_or_inf = int(numeric_series.isna().sum() - missing_count)

        invalids = nan_or_inf
        # Non-negative checks for durations, bytes, packets
        if f in ("duration_seconds", "fwd_bytes", "fwd_packets", "packet_rate", "byte_rate", "bytes_per_packet"):
            invalids += int((numeric_series < 0).sum())
        # IP TTL bounds: [1, 255]
        if f == "sttl":
            invalids += int(((numeric_series < 0) | (numeric_series > 255)).sum())
        # is_sm_ips_ports must be binary 0 or 1
        if f == "is_sm_ips_ports":
            invalids += int((~numeric_series.isin([0, 1])).sum())

        invalid_by_feature[f] = invalids
        if invalids > 0:
            violations.append(f"Feature '{f}' contains {invalids} invalid or out-of-range values.")

    total_missing = sum(missing_by_feature.values())
    total_invalid = sum(invalid_by_feature.values())

    return {
        "total_rows": total_rows,
        "total_missing_cells": total_missing,
        "total_invalid_cells": total_invalid,
        "missing_by_feature": missing_by_feature,
        "invalid_by_feature": invalid_by_feature,
        "is_clean": total_missing == 0 and total_invalid == 0,
        "violations": violations,
    }
