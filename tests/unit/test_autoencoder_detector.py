"""
Unit Tests for Autoencoder Anomaly Detector
===========================================
Version: 1.0 (Milestone 8)

Validates:
1. Model initialization and hyperparameter configuration
2. CPU training and inference on numeric feature matrices
3. Score orientation: higher reconstruction MSE for anomalous flows
4. Policy enforcement: rejects forbidden reverse-direction features and labels
5. Schema consistency: rejects missing or mismatched features at inference
6. Deterministic seeding reproducibility
7. Calibration-based label-blind thresholding
8. Artifact serialization, checksum verification, and tampering detection
9. Graceful backend handling (NumPy reference and PyTorch error handling)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from detection.artifacts import load_detector, save_detector
from detection.autoencoder import TORCH_AVAILABLE, AutoencoderDetector
from features.policy import PolicyViolationError


@pytest.fixture
def synthetic_training_data() -> pd.DataFrame:
    """Generate small normal-traffic feature matrix for testing."""
    rng = np.random.default_rng(42)
    n = 100
    return pd.DataFrame({
        "fwd_packets": rng.normal(15.0, 2.0, size=n).clip(1.0),
        "fwd_bytes": rng.normal(1200.0, 100.0, size=n).clip(10.0),
        "duration_seconds": rng.uniform(0.1, 2.0, size=n),
        "packet_rate": rng.normal(20.0, 3.0, size=n).clip(1.0),
        "byte_rate": rng.normal(1500.0, 200.0, size=n).clip(10.0),
        "bytes_per_packet": rng.normal(80.0, 5.0, size=n).clip(10.0),
    })


@pytest.fixture
def synthetic_anomalous_data() -> pd.DataFrame:
    """Generate distinct anomalous flows."""
    return pd.DataFrame({
        "fwd_packets": [5000.0, 8000.0],
        "fwd_bytes": [5_000_000.0, 12_000_000.0],
        "duration_seconds": [0.001, 0.002],
        "packet_rate": [500_000.0, 800_000.0],
        "byte_rate": [50_000_000.0, 120_000_000.0],
        "bytes_per_packet": [1000.0, 1500.0],
    })


def test_autoencoder_initialization() -> None:
    """Verify default initialization parameters."""
    ae = AutoencoderDetector()
    assert ae.hidden_dims == [32, 16]
    assert ae.learning_rate == 1e-3
    assert ae.epochs == 20
    assert ae.batch_size == 128
    assert ae.early_stopping is True
    assert ae.patience == 3
    assert ae.val_split == 0.1
    assert ae.random_state == 42
    assert ae.threshold is None
    assert ae.backend in ("auto", "torch", "numpy")
    assert not ae.is_fitted_


def test_autoencoder_fit_and_score_numpy_backend(
    synthetic_training_data: pd.DataFrame,
    synthetic_anomalous_data: pd.DataFrame,
) -> None:
    """Verify CPU training and inference using the pure-NumPy backend."""
    ae = AutoencoderDetector(
        hidden_dims=[16, 8],
        epochs=15,
        batch_size=32,
        backend="numpy",
        random_state=42,
    )
    ae.fit(synthetic_training_data)

    assert ae.is_fitted_
    assert ae.backend_used_ == "numpy"
    assert ae.n_features_in_ == 6
    assert len(ae.feature_names_in_) == 6

    # Score normal training samples
    normal_scores = ae.score_samples(synthetic_training_data)
    assert isinstance(normal_scores, np.ndarray)
    assert normal_scores.shape == (len(synthetic_training_data),)
    assert np.all(np.isfinite(normal_scores))
    assert np.all(normal_scores >= 0.0)

    # Score anomalies
    anom_scores = ae.score_samples(synthetic_anomalous_data)
    assert np.all(np.isfinite(anom_scores))
    # Extreme anomalies should yield significantly higher reconstruction MSE
    assert np.mean(anom_scores) > np.mean(normal_scores)


def test_autoencoder_backend_resolution(synthetic_training_data: pd.DataFrame) -> None:
    """Verify backend resolution and informative error when torch is missing."""
    if not TORCH_AVAILABLE:
        # Requesting torch when unavailable must raise an informative ImportError
        ae = AutoencoderDetector(backend="torch")
        with pytest.raises(ImportError, match="PyTorch.*is not installed"):
            ae.fit(synthetic_training_data)

        # 'auto' should gracefully fall back to numpy
        ae_auto = AutoencoderDetector(backend="auto", epochs=5)
        ae_auto.fit(synthetic_training_data)
        assert ae_auto.backend_used_ == "numpy"
    else:
        # If PyTorch is installed, test PyTorch execution directly
        ae_torch = AutoencoderDetector(backend="torch", epochs=5)
        ae_torch.fit(synthetic_training_data)
        assert ae_torch.backend_used_ == "torch"
        scores = ae_torch.score_samples(synthetic_training_data)
        assert np.all(np.isfinite(scores))


def test_autoencoder_reproducibility(synthetic_training_data: pd.DataFrame) -> None:
    """Verify identical random seed produces identical reconstruction scores."""
    ae1 = AutoencoderDetector(backend="numpy", epochs=10, random_state=123)
    ae1.fit(synthetic_training_data)
    scores1 = ae1.score_samples(synthetic_training_data)

    ae2 = AutoencoderDetector(backend="numpy", epochs=10, random_state=123)
    ae2.fit(synthetic_training_data)
    scores2 = ae2.score_samples(synthetic_training_data)

    np.testing.assert_allclose(scores1, scores2, rtol=1e-5, atol=1e-5)


def test_autoencoder_policy_enforcement() -> None:
    """Verify prohibited reverse-direction features and labels are rejected."""
    ae = AutoencoderDetector(backend="numpy")

    # Reverse-direction violation
    df_leak = pd.DataFrame({
        "fwd_packets": [10.0, 20.0],
        "bwd_packets": [15.0, 25.0],  # PROHIBITED
    })
    with pytest.raises(PolicyViolationError, match="Forbidden reverse-dependent columns"):
        ae.fit(df_leak)

    # Label violation
    df_label = pd.DataFrame({
        "fwd_packets": [10.0, 20.0],
        "eval_label": ["background", "dos"],  # PROHIBITED
    })
    with pytest.raises(PolicyViolationError, match="Evaluation label columns cannot be model input"):
        ae.fit(df_label)


def test_autoencoder_schema_consistency(synthetic_training_data: pd.DataFrame) -> None:
    """Verify mismatched or missing columns at scoring time raise ValueError."""
    ae = AutoencoderDetector(backend="numpy", epochs=5)
    ae.fit(synthetic_training_data)

    # Missing column
    df_missing = synthetic_training_data.drop(columns=["byte_rate"])
    with pytest.raises(ValueError, match="Input is missing fitted feature columns"):
        ae.score_samples(df_missing)


def test_autoencoder_calibration_and_predict(
    synthetic_training_data: pd.DataFrame,
    synthetic_anomalous_data: pd.DataFrame,
) -> None:
    """Verify label-blind calibration and binary prediction."""
    ae = AutoencoderDetector(backend="numpy", epochs=10, random_state=42)
    ae.fit(synthetic_training_data)

    # Calling predict before setting threshold must raise ValueError
    with pytest.raises(ValueError, match="No decision threshold has been established"):
        ae.predict(synthetic_training_data)

    # Calibrate on validation/calibration partition scores
    cal_scores = ae.score_samples(synthetic_training_data)
    thresh = ae.calibrate_threshold(cal_scores, quantile=0.95)

    assert np.isfinite(thresh)
    assert ae.threshold_ == thresh

    # Predict binary indicators
    preds_normal = ae.predict(synthetic_training_data)
    preds_anom = ae.predict(synthetic_anomalous_data)

    assert set(np.unique(preds_normal)).issubset({0, 1})
    # Most normal traffic should be 0 (normal)
    assert np.mean(preds_normal == 0) >= 0.90
    # Anomalies should be flagged as 1
    assert np.all(preds_anom == 1)


def test_autoencoder_artifact_persistence(
    synthetic_training_data: pd.DataFrame,
    tmp_path: Path,
) -> None:
    """Verify artifact serialization and tamper-proof SHA-256 loading."""
    ae = AutoencoderDetector(backend="numpy", epochs=10, random_state=42)
    ae.fit(synthetic_training_data)
    cal_scores = ae.score_samples(synthetic_training_data)
    ae.calibrate_threshold(cal_scores, quantile=0.99)

    artifact_file = tmp_path / "ae_detector.joblib"
    joblib_path, manifest_path = save_detector(ae, artifact_file)

    assert joblib_path.exists()
    assert manifest_path.exists()

    # Load and verify
    loaded_ae, manifest = load_detector(artifact_file, verify_checksum=True)
    assert isinstance(loaded_ae, AutoencoderDetector)
    assert loaded_ae.is_fitted_
    assert loaded_ae.threshold_ == ae.threshold_
    assert loaded_ae.feature_names_in_ == ae.feature_names_in_
    assert manifest["detector_type"] == "AutoencoderDetector"

    # Verify predictions match exactly
    orig_scores = ae.score_samples(synthetic_training_data)
    loaded_scores = loaded_ae.score_samples(synthetic_training_data)
    np.testing.assert_allclose(orig_scores, loaded_scores)

    # Tampering test: corrupt joblib file
    with open(artifact_file, "ab") as f:
        f.write(b"tamper_bytes")

    with pytest.raises(ValueError, match="integrity check failed"):
        load_detector(artifact_file, verify_checksum=True)
