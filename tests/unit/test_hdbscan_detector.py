"""
Unit Tests for HDBSCAN Density-Based Anomaly Detector
======================================================
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from detection.artifacts import load_detector, save_detector
from detection.hdbscan_detector import HDBSCANDetector
from features.policy import PolicyViolationError


@pytest.fixture
def two_cluster_data():
    """Synthetic dataset with two distinct dense clusters."""
    np.random.seed(42)
    # Cluster 1: 30 points near (10, 100)
    c1_x = np.random.normal(loc=10.0, scale=0.5, size=30)
    c1_y = np.random.normal(loc=100.0, scale=5.0, size=30)

    # Cluster 2: 30 points near (50, 500)
    c2_x = np.random.normal(loc=50.0, scale=1.0, size=30)
    c2_y = np.random.normal(loc=500.0, scale=10.0, size=30)

    return pd.DataFrame({
        "fwd_packets": np.concatenate([c1_x, c2_x]),
        "fwd_bytes": np.concatenate([c1_y, c2_y]),
    })


def test_hdbscan_fit_and_clustering(two_cluster_data):
    det = HDBSCANDetector(min_cluster_size=5)
    det.fit(two_cluster_data)

    assert det.is_fitted_
    assert det.n_clusters_ >= 1
    assert det.labels_ is not None
    assert len(det.labels_) == len(two_cluster_data)


def test_hdbscan_score_orientation(two_cluster_data):
    det = HDBSCANDetector(min_cluster_size=5)
    det.fit(two_cluster_data)

    normal_scores = det.score_samples(two_cluster_data)
    median_normal = float(np.median(normal_scores))

    # Point far away from both clusters
    outlier = pd.DataFrame([{
        "fwd_packets": 200.0,
        "fwd_bytes": 2000.0,
    }])
    outlier_score = float(det.score_samples(outlier)[0])

    # Higher score = more anomalous
    assert outlier_score > median_normal


def test_hdbscan_insufficient_samples():
    df = pd.DataFrame({"fwd_packets": [1.0, 2.0], "fwd_bytes": [10.0, 20.0]})
    det = HDBSCANDetector(min_cluster_size=10)
    with pytest.raises(ValueError) as exc:
        det.fit(df)
    assert "must be >= min_cluster_size" in str(exc.value)


def test_hdbscan_policy_rejection(two_cluster_data):
    det = HDBSCANDetector()
    bad_df = two_cluster_data.copy()
    bad_df["class"] = "dos"
    with pytest.raises(PolicyViolationError):
        det.fit(bad_df)


def test_hdbscan_artifact_roundtrip(two_cluster_data, tmp_path: Path):
    det = HDBSCANDetector(min_cluster_size=5)
    det.fit(two_cluster_data)
    det.set_threshold(2.0)

    art_path = tmp_path / "hdbscan_model.joblib"
    save_detector(det, art_path)

    loaded_det, manifest = load_detector(art_path, verify_checksum=True)
    assert manifest["detector_type"] == "HDBSCANDetector"

    orig_scores = det.score_samples(two_cluster_data)
    loaded_scores = loaded_det.score_samples(two_cluster_data)
    np.testing.assert_allclose(orig_scores, loaded_scores, atol=1e-7)
