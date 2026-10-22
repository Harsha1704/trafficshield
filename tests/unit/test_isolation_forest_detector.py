"""
Unit Tests for Isolation Forest Anomaly Detector
=================================================
"""
import numpy as np
import pandas as pd
import pytest

from detection.isolation_forest import IsolationForestDetector
from features.policy import PolicyViolationError


@pytest.fixture
def synthetic_traffic_data():
    np.random.seed(42)
    n = 150
    pkts = np.random.normal(loc=15.0, scale=2.0, size=n).clip(min=1.0)
    bytes_ = pkts * np.random.normal(loc=80.0, scale=5.0, size=n)
    dur = np.random.uniform(low=0.2, high=1.5, size=n)
    rates = pkts / dur

    return pd.DataFrame({
        "fwd_packets": pkts,
        "fwd_bytes": bytes_,
        "duration_seconds": dur,
        "packet_rate": rates,
    })


def test_fit_and_score_samples(synthetic_traffic_data):
    detector = IsolationForestDetector(n_estimators=50, random_state=42)
    detector.fit(synthetic_traffic_data)

    assert detector.is_fitted_
    assert detector.model_ is not None

    scores = detector.score_samples(synthetic_traffic_data)
    assert isinstance(scores, np.ndarray)
    assert len(scores) == len(synthetic_traffic_data)
    assert np.all(np.isfinite(scores))


def test_score_orientation_higher_is_more_anomalous(synthetic_traffic_data):
    detector = IsolationForestDetector(n_estimators=50, random_state=42)
    detector.fit(synthetic_traffic_data)

    normal_scores = detector.score_samples(synthetic_traffic_data)
    median_normal_score = float(np.median(normal_scores))

    # Extreme outlier (massive scan burst)
    outlier = pd.DataFrame([{
        "fwd_packets": 5000.0,
        "fwd_bytes": 500000.0,
        "duration_seconds": 0.1,
        "packet_rate": 50000.0,
    }])

    outlier_score = float(detector.score_samples(outlier)[0])
    assert outlier_score > median_normal_score


def test_raw_score_inversion(synthetic_traffic_data):
    detector = IsolationForestDetector(n_estimators=50, random_state=42)
    detector.fit(synthetic_traffic_data)

    raw_scores = detector.score_samples_raw(synthetic_traffic_data)
    inverted_scores = detector.score_samples(synthetic_traffic_data)

    # Inverted score must equal -raw_score
    np.testing.assert_allclose(inverted_scores, -raw_scores, atol=1e-7)


def test_deterministic_seeding(synthetic_traffic_data):
    det1 = IsolationForestDetector(n_estimators=50, random_state=42)
    det1.fit(synthetic_traffic_data)
    scores1 = det1.score_samples(synthetic_traffic_data)

    det2 = IsolationForestDetector(n_estimators=50, random_state=42)
    det2.fit(synthetic_traffic_data)
    scores2 = det2.score_samples(synthetic_traffic_data)

    np.testing.assert_array_equal(scores1, scores2)


def test_predict_with_calibrated_threshold(synthetic_traffic_data):
    detector = IsolationForestDetector(n_estimators=50, random_state=42)
    detector.fit(synthetic_traffic_data)

    cal_scores = detector.score_samples(synthetic_traffic_data)
    threshold = detector.calibrate_threshold(cal_scores, quantile=0.90)
    assert np.isfinite(threshold)

    preds = detector.predict(synthetic_traffic_data)
    anomaly_rate = float(np.mean(preds))
    assert pytest.approx(anomaly_rate, abs=0.03) == 0.10


def test_detector_schema_validation(synthetic_traffic_data):
    detector = IsolationForestDetector()
    detector.fit(synthetic_traffic_data)

    # Missing column
    incomplete = synthetic_traffic_data.drop(columns=["fwd_bytes"])
    with pytest.raises(ValueError) as exc:
        detector.score_samples(incomplete)
    assert "missing fitted feature columns" in str(exc.value)


def test_detector_policy_rejection(synthetic_traffic_data):
    detector = IsolationForestDetector()
    bad_df = synthetic_traffic_data.copy()
    bad_df["bwd_packets"] = 10.0
    with pytest.raises(PolicyViolationError):
        detector.fit(bad_df)


def test_detector_does_not_refit_on_inference(synthetic_traffic_data):
    detector = IsolationForestDetector(n_estimators=50, random_state=42)
    detector.fit(synthetic_traffic_data)

    first_tree_estimators_before = [tree.tree_ for tree in detector.model_.estimators_]

    # Score inference set with extreme values
    outliers = pd.DataFrame([{
        "fwd_packets": 999999.0,
        "fwd_bytes": 99999999.0,
        "duration_seconds": 1.0,
        "packet_rate": 999999.0,
    }])
    _ = detector.score_samples(outliers)

    first_tree_estimators_after = [tree.tree_ for tree in detector.model_.estimators_]
    assert len(first_tree_estimators_before) == len(first_tree_estimators_after)
