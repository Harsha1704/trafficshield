"""
Unit Tests for Local Outlier Factor (LOF) Anomaly Detector
===========================================================
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from detection.artifacts import load_detector, save_detector
from detection.lof import LOFDetector
from features.policy import PolicyViolationError


@pytest.fixture
def dense_cluster_data():
    """Synthetic dense 2D cluster with low variance."""
    np.random.seed(42)
    n = 60
    # Dense cluster around (10, 100)
    feat1 = np.random.normal(loc=10.0, scale=0.5, size=n)
    feat2 = np.random.normal(loc=100.0, scale=5.0, size=n)

    return pd.DataFrame({
        "fwd_packets": feat1,
        "fwd_bytes": feat2,
    })


def test_lof_fit_and_score(dense_cluster_data):
    det = LOFDetector(n_neighbors=10)
    det.fit(dense_cluster_data)

    assert det.is_fitted_
    assert det.model_ is not None

    scores = det.score_samples(dense_cluster_data)
    assert len(scores) == len(dense_cluster_data)
    assert np.all(np.isfinite(scores))


def test_lof_score_orientation(dense_cluster_data):
    det = LOFDetector(n_neighbors=10)
    det.fit(dense_cluster_data)

    normal_scores = det.score_samples(dense_cluster_data)
    median_normal = float(np.median(normal_scores))

    # Isolated point far from dense cluster
    outlier = pd.DataFrame([{
        "fwd_packets": 500.0,
        "fwd_bytes": 50000.0,
    }])
    outlier_score = float(det.score_samples(outlier)[0])

    # Universal convention: higher score = more anomalous
    assert outlier_score > median_normal


def test_lof_insufficient_samples_raises():
    df = pd.DataFrame({"fwd_packets": [1.0, 2.0], "fwd_bytes": [10.0, 20.0]})
    # 2 samples but n_neighbors=5 -> impossible to compute 5-NN
    det = LOFDetector(n_neighbors=5)
    with pytest.raises(ValueError) as exc:
        det.fit(df)
    assert "strictly greater than n_neighbors" in str(exc.value)


def test_lof_policy_rejection(dense_cluster_data):
    det = LOFDetector()
    bad_df = dense_cluster_data.copy()
    bad_df["bwd_packets"] = 10.0
    with pytest.raises(PolicyViolationError):
        det.fit(bad_df)


def test_lof_artifact_roundtrip(dense_cluster_data, tmp_path: Path):
    det = LOFDetector(n_neighbors=10)
    det.fit(dense_cluster_data)
    det.set_threshold(1.5)

    art_path = tmp_path / "lof_model.joblib"
    save_detector(det, art_path)

    loaded_det, manifest = load_detector(art_path, verify_checksum=True)
    assert manifest["detector_type"] == "LOFDetector"
    assert manifest["threshold"] == 1.5

    orig_scores = det.score_samples(dense_cluster_data)
    loaded_scores = loaded_det.score_samples(dense_cluster_data)
    np.testing.assert_allclose(orig_scores, loaded_scores, atol=1e-7)
