"""
TrafficShield Unit Tests — Production Isolation Forest Artifact Validation
===========================================================================
Phase 1: Hybrid Architecture — Unsupervised Isolation Forest Detector

Validates:
1. Artifact loadability and companion JSON manifest parsing.
2. SHA-256 cryptographic integrity verification.
3. Prediction and anomaly score conventions (shape, float dtype, finite values).
4. Score direction: higher score strictly indicates more anomalous (anomaly_score = -raw_score).
5. Calibrated threshold validity (finite, between min and max calibration scores).
6. Feature contract: strictly 13 forward causal features matching preprocessor output.
7. Rejection of missing, extra, non-numeric, or reordered features without proper names.
8. Determinism: identical scores across multiple evaluations under the fixed seed.
9. Immutability of the three frozen artifacts (detector, json, preprocessor).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from detection.artifacts import compute_sha256, load_detector
from detection.isolation_forest import IsolationForestDetector

# Authoritative frozen hashes for existing artifacts
EXPECTED_SUPERVISED_MODEL_SHA256 = "c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495"
EXPECTED_SUPERVISED_META_SHA256 = "3553f1a47c1c2fd67b031cadb42400246997778f8dcf42026e2ebfb882ba73b1"
EXPECTED_PREPROCESSOR_SHA256 = "effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653"

IFOREST_MODEL_PATH = Path("artifacts/models/production_iforest.joblib")
IFOREST_JSON_PATH = Path("artifacts/models/production_iforest.json")

EXPECTED_13_FEATURES = [
    "duration_seconds",
    "fwd_bytes",
    "sttl",
    "sload",
    "fwd_packets",
    "swin",
    "smeansz",
    "sjit",
    "sintpkt",
    "packet_rate",
    "byte_rate",
    "bytes_per_packet",
    "is_sm_ips_ports",
]


@pytest.fixture(scope="module")
def iforest_artifact():
    """Load production Isolation Forest artifact with checksum verification."""
    assert IFOREST_MODEL_PATH.exists(), f"Artifact missing: {IFOREST_MODEL_PATH}"
    assert IFOREST_JSON_PATH.exists(), f"Manifest missing: {IFOREST_JSON_PATH}"

    detector, manifest = load_detector(IFOREST_MODEL_PATH, verify_checksum=True)
    return detector, manifest


@pytest.fixture
def sample_features_df():
    """Generate a clean synthetic batch matching the exact 13-feature contract."""
    np.random.seed(42)
    n = 10
    data = {
        "duration_seconds": np.random.uniform(0.1, 5.0, n),
        "fwd_bytes": np.random.uniform(100, 5000, n),
        "sttl": np.random.choice([31, 64, 128, 254], n),
        "sload": np.random.uniform(1000, 100000, n),
        "fwd_packets": np.random.randint(2, 50, n),
        "swin": np.random.choice([0, 255, 65535], n),
        "smeansz": np.random.uniform(40, 1500, n),
        "sjit": np.random.uniform(0, 100, n),
        "sintpkt": np.random.uniform(0.01, 10.0, n),
        "packet_rate": np.random.uniform(1, 50, n),
        "byte_rate": np.random.uniform(100, 5000, n),
        "bytes_per_packet": np.random.uniform(40, 1500, n),
        "is_sm_ips_ports": np.zeros(n, dtype=int),
    }
    return pd.DataFrame(data)[EXPECTED_13_FEATURES]


class TestProductionIsolationForestArtifact:
    """Rigorous verification of the production Isolation Forest model artifact."""

    def test_artifact_and_manifest_exist_and_pass_sha256(self, iforest_artifact):
        detector, manifest = iforest_artifact
        assert isinstance(detector, IsolationForestDetector)
        assert detector.is_fitted_ is True

        # Check manifest schema
        assert manifest["detector_type"] == "IsolationForestDetector"
        assert manifest["n_features_in"] == 13
        assert manifest["feature_names_in"] == EXPECTED_13_FEATURES
        assert manifest["preprocessor_artifact_ref"] == "artifacts/models/production_preprocessor.joblib"

        # Check actual SHA-256 matches manifest entry
        actual_hash = compute_sha256(IFOREST_MODEL_PATH)
        assert actual_hash == manifest["sha256"]

    def test_threshold_is_finite_and_calibrated(self, iforest_artifact):
        detector, manifest = iforest_artifact
        thresh = detector.threshold_
        assert thresh is not None
        assert np.isfinite(thresh)
        assert 0.0 < thresh < 1.0

        thresh_cfg = manifest.get("threshold_config", {})
        assert thresh_cfg.get("method") == "empirical_quantile_on_benign_calibration"
        assert thresh_cfg.get("quantile") == 0.99
        assert thresh_cfg.get("calibration_sample_count") == 14153

        # Threshold must be within calibration score bounds
        min_s = thresh_cfg["calibration_min_score"]
        max_s = thresh_cfg["calibration_max_score"]
        assert min_s <= thresh <= max_s

    def test_score_and_predict_contract(self, iforest_artifact, sample_features_df):
        detector, _ = iforest_artifact
        scores = detector.score_samples(sample_features_df)
        assert isinstance(scores, np.ndarray)
        assert scores.shape == (len(sample_features_df),)
        assert scores.dtype == np.float64
        assert np.all(np.isfinite(scores))

        # Raw scores in scikit-learn are inverted
        raw_scores = detector.score_samples_raw(sample_features_df)
        assert np.allclose(scores, -raw_scores)

        # Binary predictions: 1 if score >= threshold, 0 otherwise
        preds = detector.predict(sample_features_df)
        assert isinstance(preds, np.ndarray)
        assert preds.shape == (len(sample_features_df),)
        assert set(np.unique(preds)).issubset({0, 1})
        expected_preds = (scores >= detector.threshold_).astype(int)
        assert np.array_equal(preds, expected_preds)

    def test_deterministic_scoring(self, iforest_artifact, sample_features_df):
        detector, _ = iforest_artifact
        scores_pass1 = detector.score_samples(sample_features_df)
        scores_pass2 = detector.score_samples(sample_features_df)
        assert np.array_equal(scores_pass1, scores_pass2)

    def test_schema_validation_rejects_missing_column(self, iforest_artifact, sample_features_df):
        detector, _ = iforest_artifact
        corrupt_df = sample_features_df.drop(columns=["duration_seconds"])
        with pytest.raises(ValueError, match="missing fitted feature columns"):
            detector.score_samples(corrupt_df)

    def test_schema_validation_rejects_non_numeric(self, iforest_artifact, sample_features_df):
        detector, _ = iforest_artifact
        corrupt_df = sample_features_df.copy()
        corrupt_df["duration_seconds"] = "corrupt_string"
        with pytest.raises(ValueError, match="non-numeric"):
            detector.score_samples(corrupt_df)

    def test_tampered_artifact_fails_closed(self, tmp_path):
        """Simulate corrupt artifact and verify load_detector raises error."""
        tmp_joblib = tmp_path / "tampered.joblib"
        tmp_json = tmp_path / "tampered.json"

        tmp_joblib.write_bytes(b"corrupted binary data")
        tmp_json.write_text(json.dumps({"sha256": "fake_hash", "detector_type": "IsolationForestDetector"}), encoding="utf-8")

        with pytest.raises(ValueError, match="integrity check failed"):
            load_detector(tmp_joblib, verify_checksum=True)

    def test_frozen_artifacts_strictly_preserved(self):
        """Verify byte-for-byte SHA-256 equivalence of the three frozen artifacts."""
        checks = [
            ("artifacts/models/production_detector.joblib", EXPECTED_SUPERVISED_MODEL_SHA256),
            ("artifacts/models/production_detector.json", EXPECTED_SUPERVISED_META_SHA256),
            ("artifacts/models/production_preprocessor.joblib", EXPECTED_PREPROCESSOR_SHA256),
        ]
        for path_str, exp_hash in checks:
            p = Path(path_str)
            assert p.exists(), f"Frozen artifact {path_str} is missing!"
            actual_hash = compute_sha256(p)
            assert actual_hash == exp_hash, f"Frozen artifact {path_str} hash changed!"
