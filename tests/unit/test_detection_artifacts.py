"""
Unit Tests for Detection Artifacts & Serialization
===================================================
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from detection.artifacts import load_detector, save_detector
from detection.isolation_forest import IsolationForestDetector
from detection.statistical import RobustStatisticalDetector


@pytest.fixture
def sample_features():
    np.random.seed(42)
    return pd.DataFrame({
        "fwd_packets": [10.0, 15.0, 12.0, 14.0, 20.0],
        "fwd_bytes": [1000.0, 1500.0, 1200.0, 1400.0, 2000.0],
        "duration_seconds": [1.0, 1.5, 1.2, 1.4, 2.0],
        "packet_rate": [10.0, 10.0, 10.0, 10.0, 10.0],
    })


def test_statistical_detector_artifact_roundtrip(sample_features, tmp_path: Path):
    det = RobustStatisticalDetector(aggregation="max")
    det.fit(sample_features)
    det.set_threshold(2.5)

    art_path = tmp_path / "stat_model.joblib"
    joblib_p, json_p = save_detector(
        det,
        art_path,
        preprocessor_artifact_ref="prep_v1.joblib",
        metadata={"model_name": "baseline_statistical"},
    )

    assert joblib_p.exists()
    assert json_p.exists()

    loaded_det, manifest = load_detector(joblib_p, verify_checksum=True)
    assert manifest["detector_type"] == "RobustStatisticalDetector"
    assert manifest["threshold"] == 2.5
    assert manifest["preprocessor_artifact_ref"] == "prep_v1.joblib"

    orig_scores = det.score_samples(sample_features)
    loaded_scores = loaded_det.score_samples(sample_features)
    np.testing.assert_allclose(orig_scores, loaded_scores, atol=1e-7)


def test_isolation_forest_artifact_roundtrip(sample_features, tmp_path: Path):
    det = IsolationForestDetector(n_estimators=30, random_state=42)
    det.fit(sample_features)
    det.set_threshold(-0.1)

    art_path = tmp_path / "iforest_model.joblib"
    joblib_p, json_p = save_detector(det, art_path)

    loaded_det, manifest = load_detector(joblib_p, verify_checksum=True)
    assert manifest["detector_type"] == "IsolationForestDetector"

    orig_scores = det.score_samples(sample_features)
    loaded_scores = loaded_det.score_samples(sample_features)
    np.testing.assert_allclose(orig_scores, loaded_scores, atol=1e-7)


def test_tampered_detector_detected(sample_features, tmp_path: Path):
    det = RobustStatisticalDetector()
    det.fit(sample_features)
    art_path = tmp_path / "detector.joblib"
    save_detector(det, art_path)

    # Tamper with the binary
    with open(art_path, "ab") as f:
        f.write(b"CORRUPTED_BYTES")

    with pytest.raises(ValueError) as exc:
        load_detector(art_path, verify_checksum=True)
    assert "integrity check failed" in str(exc.value)


def test_save_unfitted_detector_raises(tmp_path: Path):
    det = RobustStatisticalDetector()
    with pytest.raises(ValueError) as exc:
        save_detector(det, tmp_path / "unfitted.joblib")
    assert "Cannot save an unfitted" in str(exc.value)
