"""
Unit and Integration Tests for Calibrated Multi-Detector Ensemble
=================================================================
Version: 1.0 (Milestone 8.1)

Validates:
1. Calibration score normalizers (Empirical Percentile & Robust MinMax)
2. Normalizer robustness against constant scores, ties, and edge distributions
3. Ensemble initialization, weight normalization, and validation
4. Predeclared fusion without label optimization
5. Common score orientation across diverse detector families
6. Calibration-only normalization and frozen thresholding (zero test leakage)
7. Detailed score diagnostics (component raw and normalized scores)
8. Artifact serialization and SHA-256 integrity verification
9. End-to-end integration with ModelEvaluator
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from detection.artifacts import load_detector, save_detector
from detection.autoencoder import AutoencoderDetector
from detection.ensemble import (
    CalibratedEnsembleDetector,
    EmpiricalPercentileNormalizer,
    RobustMinMaxNormalizer,
)
from detection.isolation_forest import IsolationForestDetector
from detection.statistical import RobustStatisticalDetector
from evaluation.evaluator import ModelEvaluator
from evaluation.partitioning import ChronologicalPartition
from features.policy import PolicyViolationError


@pytest.fixture
def synthetic_normal_df() -> pd.DataFrame:
    """Generate normal feature matrix."""
    rng = np.random.default_rng(42)
    n = 120
    return pd.DataFrame({
        "fwd_packets": rng.normal(15.0, 2.0, size=n).clip(1.0),
        "fwd_bytes": rng.normal(1200.0, 100.0, size=n).clip(10.0),
        "duration_seconds": rng.uniform(0.1, 2.0, size=n),
        "packet_rate": rng.normal(20.0, 3.0, size=n).clip(1.0),
        "byte_rate": rng.normal(1500.0, 200.0, size=n).clip(10.0),
        "bytes_per_packet": rng.normal(80.0, 5.0, size=n).clip(10.0),
    })


@pytest.fixture
def synthetic_anom_df() -> pd.DataFrame:
    """Generate distinct anomalies."""
    return pd.DataFrame({
        "fwd_packets": [4000.0, 6000.0],
        "fwd_bytes": [4_000_000.0, 9_000_000.0],
        "duration_seconds": [0.001, 0.002],
        "packet_rate": [400_000.0, 600_000.0],
        "byte_rate": [40_000_000.0, 90_000_000.0],
        "bytes_per_packet": [1000.0, 1500.0],
    })


# ─────────────────────────────────────────────────────────────────────────────
# 1. Normalizer Unit Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_empirical_percentile_normalizer() -> None:
    """Verify empirical percentile normalizer maps scores to [0, 1] monotonically."""
    cal_scores = np.array([10.0, 20.0, 30.0, 40.0, 50.0])
    norm = EmpiricalPercentileNormalizer().fit(cal_scores)

    # Test values below, within, and above calibration range
    test_scores = np.array([5.0, 10.0, 25.0, 50.0, 100.0])
    res = norm.transform(test_scores)

    # 5.0 <= min -> rank 0 -> 0.0
    # 10.0 == min -> rank 1 -> 0.2
    # 25.0 between 20 and 30 -> rank 2 -> 0.4
    # 50.0 == max -> rank 5 -> 1.0
    # 100.0 > max -> rank 5 -> 1.0
    expected = np.array([0.0, 0.2, 0.4, 1.0, 1.0])
    np.testing.assert_allclose(res, expected)
    assert np.all(res >= 0.0) and np.all(res <= 1.0)


def test_empirical_percentile_normalizer_constant_scores() -> None:
    """Verify constant calibration scores map safely to 0.5 without divide-by-zero."""
    cal_scores = np.full(50, 42.0)
    norm = EmpiricalPercentileNormalizer().fit(cal_scores)

    res = norm.transform(np.array([10.0, 42.0, 99.0]))
    np.testing.assert_allclose(res, np.array([0.5, 0.5, 0.5]))


def test_robust_minmax_normalizer() -> None:
    """Verify robust minmax normalizer scales scores linearly within quantiles."""
    cal_scores = np.linspace(0.0, 100.0, 101)
    norm = RobustMinMaxNormalizer(low_q=0.0, high_q=1.0).fit(cal_scores)

    res = norm.transform(np.array([-10.0, 50.0, 110.0]))
    np.testing.assert_allclose(res, np.array([0.0, 0.5, 1.0]))


# ─────────────────────────────────────────────────────────────────────────────
# 2. Ensemble Architecture and Weight Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_ensemble_initialization_defaults() -> None:
    """Verify default initialization creates standard 4-member ensemble with equal weights."""
    ens = CalibratedEnsembleDetector()
    assert len(ens.detectors) == 4
    assert "statistical" in ens.detectors
    assert "iforest" in ens.detectors
    assert "lof" in ens.detectors
    assert "autoencoder" in ens.detectors

    # Equal weights (0.25 each)
    for w in ens.weights.values():
        assert pytest.approx(w) == 0.25
    assert pytest.approx(sum(ens.weights.values())) == 1.0
    assert not ens.is_fitted_


def test_ensemble_custom_weights() -> None:
    """Verify custom weights are normalized to sum to 1.0."""
    ens = CalibratedEnsembleDetector(
        detectors={
            "stat": RobustStatisticalDetector(),
            "if": IsolationForestDetector(random_state=42),
        },
        weights={"stat": 3.0, "if": 1.0},
    )
    assert pytest.approx(ens.weights["stat"]) == 0.75
    assert pytest.approx(ens.weights["if"]) == 0.25


def test_ensemble_weight_validation() -> None:
    """Verify negative weights or missing detectors raise ValueError."""
    with pytest.raises(ValueError, match="non-negative"):
        CalibratedEnsembleDetector(
            detectors={"stat": RobustStatisticalDetector()},
            weights={"stat": -1.0},
        )

    with pytest.raises(ValueError, match="Missing weights"):
        CalibratedEnsembleDetector(
            detectors={"stat": RobustStatisticalDetector(), "if": IsolationForestDetector()},
            weights={"stat": 1.0},
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Fitting, Calibration, Scoring, and Leakage Prevention
# ─────────────────────────────────────────────────────────────────────────────

def test_ensemble_fit_calibrate_and_score(
    synthetic_normal_df: pd.DataFrame,
    synthetic_anom_df: pd.DataFrame,
) -> None:
    """Verify full ensemble training, calibration-phase normalizer fitting, and scoring."""
    train_df = synthetic_normal_df.iloc[:60]
    cal_df = synthetic_normal_df.iloc[60:]

    ens = CalibratedEnsembleDetector(
        detectors={
            "stat": RobustStatisticalDetector(),
            "iforest": IsolationForestDetector(n_estimators=30, random_state=42),
            "ae": AutoencoderDetector(backend="numpy", epochs=5, random_state=42),
        },
        random_state=42,
    )

    # 1. Fit on train only
    ens.fit(train_df)
    assert ens.is_fitted_

    # 2. Calibrate on calibration partition only
    cal_fused = ens.calibrate_ensemble(cal_df)
    assert ens.is_calibrated_
    assert cal_fused.shape == (len(cal_df),)
    assert np.all(cal_fused >= 0.0) and np.all(cal_fused <= 1.0)

    # 3. Score test/anomalous samples
    normal_scores = ens.score_samples(cal_df)
    anom_scores = ens.score_samples(synthetic_anom_df)

    assert normal_scores.shape == (len(cal_df),)
    assert anom_scores.shape == (len(synthetic_anom_df),)
    assert np.all(np.isfinite(normal_scores))
    assert np.all(np.isfinite(anom_scores))

    # Anomalies should receive higher fused scores than benign traffic
    assert np.mean(anom_scores) > np.mean(normal_scores)


def test_ensemble_score_samples_detailed(synthetic_normal_df: pd.DataFrame) -> None:
    """Verify detailed scoring dictionary provides component breakdown."""
    ens = CalibratedEnsembleDetector(
        detectors={
            "stat": RobustStatisticalDetector(),
            "ae": AutoencoderDetector(backend="numpy", epochs=5, random_state=42),
        },
    )
    ens.fit(synthetic_normal_df)

    details = ens.score_samples_detailed(synthetic_normal_df)
    assert "fused_scores" in details
    assert "raw_scores" in details
    assert "normalized_scores" in details
    assert "stat" in details["raw_scores"]
    assert "ae" in details["raw_scores"]
    assert "stat" in details["normalized_scores"]
    assert "ae" in details["normalized_scores"]


def test_ensemble_policy_enforcement() -> None:
    """Verify ensemble rejects prohibited reverse-direction features and evaluation labels."""
    ens = CalibratedEnsembleDetector()

    df_bwd = pd.DataFrame({"fwd_packets": [10.0, 20.0], "bwd_packets": [5.0, 10.0]})
    with pytest.raises(PolicyViolationError, match="Forbidden reverse-dependent columns"):
        ens.fit(df_bwd)

    df_lbl = pd.DataFrame({"fwd_packets": [10.0, 20.0], "eval_label": ["normal", "attack"]})
    with pytest.raises(PolicyViolationError, match="Evaluation label columns cannot be model input"):
        ens.fit(df_lbl)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Artifact Serialization and Tamper Proofing
# ─────────────────────────────────────────────────────────────────────────────

def test_ensemble_artifact_persistence(
    synthetic_normal_df: pd.DataFrame,
    tmp_path: Path,
) -> None:
    """Verify artifact serialization and SHA-256 verification for the ensemble."""
    ens = CalibratedEnsembleDetector(
        detectors={
            "stat": RobustStatisticalDetector(),
            "iforest": IsolationForestDetector(n_estimators=20, random_state=42),
        },
    )
    ens.fit(synthetic_normal_df)
    cal_scores = ens.calibrate_ensemble(synthetic_normal_df)
    ens.calibrate_threshold(cal_scores, quantile=0.99)

    artifact_file = tmp_path / "ensemble_detector.joblib"
    joblib_path, manifest_path = save_detector(ens, artifact_file)

    assert joblib_path.exists()
    assert manifest_path.exists()

    loaded_ens, manifest = load_detector(artifact_file, verify_checksum=True)
    assert isinstance(loaded_ens, CalibratedEnsembleDetector)
    assert loaded_ens.is_fitted_
    assert loaded_ens.is_calibrated_
    assert loaded_ens.threshold_ == ens.threshold_
    assert manifest["detector_type"] == "CalibratedEnsembleDetector"

    # Score comparison
    orig_scores = ens.score_samples(synthetic_normal_df)
    loaded_scores = loaded_ens.score_samples(synthetic_normal_df)
    np.testing.assert_allclose(orig_scores, loaded_scores)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Integration with ModelEvaluator
# ─────────────────────────────────────────────────────────────────────────────

def test_ensemble_model_evaluator_integration(synthetic_normal_df: pd.DataFrame) -> None:
    """Verify end-to-end evaluation lifecycle with ModelEvaluator."""
    n = len(synthetic_normal_df)
    df = synthetic_normal_df.copy()
    df["flow_end_ts"] = pd.date_range("2026-03-01", periods=n, freq="min")
    # Mark last 5% as attack
    labels = ["normal"] * n
    for i in range(int(n * 0.95), n):
        labels[i] = "dos"
    df["eval_label"] = labels

    train_df = df.iloc[:70]
    cal_df = df.iloc[70:95]
    test_df = df.iloc[95:]

    partition = ChronologicalPartition(
        train_df=train_df,
        calibration_df=cal_df,
        test_df=test_df,
        timestamp_col="flow_end_ts",
    )

    ens = CalibratedEnsembleDetector(
        detectors={
            "stat": RobustStatisticalDetector(),
            "iforest": IsolationForestDetector(n_estimators=25, random_state=42),
            "ae": AutoencoderDetector(backend="numpy", epochs=5, random_state=42),
        },
    )

    evaluator = ModelEvaluator(detector=ens)
    report = evaluator.evaluate_partition(
        partition=partition,
        quantile=0.95,
        label_col="eval_label",
        benign_label="normal",
        dataset_name="synthetic_test",
    )

    assert report.detector_type == "CalibratedEnsembleDetector"
    assert report.train_count == 70
    assert report.calibration_count == 25
    assert report.test_count == 25
    assert report.threshold_value > 0.0
    assert "precision" in report.binary_metrics
    assert "recall" in report.binary_metrics
    assert "roc_auc" in report.ranking_metrics
