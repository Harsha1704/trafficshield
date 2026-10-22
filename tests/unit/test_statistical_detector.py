"""
Unit Tests for Robust Statistical Anomaly Detector
===================================================
"""
import numpy as np
import pandas as pd
import pytest

from detection.statistical import RobustStatisticalDetector
from features.policy import PolicyViolationError


@pytest.fixture
def synthetic_calibration_data():
    """Synthetic normal baseline traffic (100 flows, 4 features)."""
    np.random.seed(42)
    # 4 features: packets, bytes, duration, packet_rate
    pkts = np.random.normal(loc=20.0, scale=3.0, size=100).clip(min=1.0)
    bytes_ = pkts * np.random.normal(loc=100.0, scale=10.0, size=100)
    dur = np.random.uniform(low=0.5, high=2.0, size=100)
    rates = pkts / dur

    return pd.DataFrame({
        "fwd_packets": pkts,
        "fwd_bytes": bytes_,
        "duration_seconds": dur,
        "packet_rate": rates,
    })


def test_fit_and_score_valid_samples(synthetic_calibration_data):
    detector = RobustStatisticalDetector(aggregation="max")
    detector.fit(synthetic_calibration_data)

    assert detector.is_fitted_
    assert detector.medians_ is not None
    assert detector.mads_ is not None
    assert len(detector.feature_names_in_) == 4

    scores = detector.score_samples(synthetic_calibration_data)
    assert isinstance(scores, np.ndarray)
    assert len(scores) == len(synthetic_calibration_data)
    assert np.all(np.isfinite(scores))
    assert np.all(scores >= 0.0)


def test_outlier_receives_higher_score(synthetic_calibration_data):
    detector = RobustStatisticalDetector(aggregation="max")
    detector.fit(synthetic_calibration_data)

    baseline_scores = detector.score_samples(synthetic_calibration_data)
    median_baseline_score = float(np.median(baseline_scores))

    # Extreme outlier: 100x packet burst
    outlier = pd.DataFrame([{
        "fwd_packets": 2000.0,
        "fwd_bytes": 200000.0,
        "duration_seconds": 1.0,
        "packet_rate": 2000.0,
    }])

    outlier_score = float(detector.score_samples(outlier)[0])
    assert outlier_score > median_baseline_score * 10.0


def test_zero_mad_and_constant_features():
    # Training data where feature_2 is strictly constant
    df = pd.DataFrame({
        "fwd_packets": [10.0, 12.0, 11.0, 10.5, 11.5],
        "duration_seconds": [1.0, 1.0, 1.0, 1.0, 1.0],  # Constant: MAD == 0
    })
    detector = RobustStatisticalDetector()
    detector.fit(df)

    assert bool(detector.is_constant_feature_[1]) is True
    # Test sample with normal constant feature
    scores_normal = detector.score_samples(pd.DataFrame({
        "fwd_packets": [11.0],
        "duration_seconds": [1.0],
    }))
    assert np.isfinite(scores_normal[0])

    # Test sample with deviation on the constant feature
    scores_deviant = detector.score_samples(pd.DataFrame({
        "fwd_packets": [11.0],
        "duration_seconds": [5.0],  # Deviates from constant 1.0
    }))
    assert np.isfinite(scores_deviant[0])
    assert scores_deviant[0] > scores_normal[0]


@pytest.mark.parametrize("agg", ["max", "top_k", "mean", "l2"])
def test_aggregation_strategies(synthetic_calibration_data, agg):
    detector = RobustStatisticalDetector(aggregation=agg, top_k=2)
    detector.fit(synthetic_calibration_data)
    scores = detector.score_samples(synthetic_calibration_data)
    assert np.all(np.isfinite(scores))
    assert np.all(scores >= 0.0)


def test_explain_samples(synthetic_calibration_data):
    detector = RobustStatisticalDetector()
    detector.fit(synthetic_calibration_data)

    outlier = pd.DataFrame([{
        "fwd_packets": 500.0,   # High anomaly
        "fwd_bytes": 1000.0,
        "duration_seconds": 1.0,
        "packet_rate": 500.0,   # High anomaly
    }])

    explanations = detector.explain_samples(outlier, top_n=2)
    assert len(explanations) == 1
    top_features = [item["feature"] for item in explanations[0]]
    assert len(top_features) == 2
    assert "fwd_packets" in top_features or "packet_rate" in top_features
    assert explanations[0][0]["deviation"] >= explanations[0][1]["deviation"]


def test_calibrate_and_predict(synthetic_calibration_data):
    detector = RobustStatisticalDetector()
    detector.fit(synthetic_calibration_data)

    cal_scores = detector.score_samples(synthetic_calibration_data)
    threshold = detector.calibrate_threshold(cal_scores, quantile=0.95)
    assert np.isfinite(threshold)

    preds = detector.predict(synthetic_calibration_data)
    # Exactly ~5% should be flagged as anomalous on calibration data
    anomaly_rate = float(np.mean(preds))
    assert pytest.approx(anomaly_rate, abs=0.03) == 0.05

    # Outlier must be predicted as 1 (anomaly)
    outlier = pd.DataFrame([{
        "fwd_packets": 1000.0,
        "fwd_bytes": 100000.0,
        "duration_seconds": 1.0,
        "packet_rate": 1000.0,
    }])
    assert detector.predict(outlier)[0] == 1


def test_detector_rejects_forbidden_and_labels(synthetic_calibration_data):
    detector = RobustStatisticalDetector()
    bad_df = synthetic_calibration_data.copy()
    bad_df["bwd_packets"] = 5.0
    with pytest.raises(PolicyViolationError):
        detector.fit(bad_df)

    bad_label_df = synthetic_calibration_data.copy()
    bad_label_df["class"] = "dos"
    with pytest.raises(PolicyViolationError):
        detector.fit(bad_label_df)


def test_detector_schema_validation(synthetic_calibration_data):
    detector = RobustStatisticalDetector()
    detector.fit(synthetic_calibration_data)

    # Missing column
    incomplete = synthetic_calibration_data.drop(columns=["packet_rate"])
    with pytest.raises(ValueError) as exc:
        detector.score_samples(incomplete)
    assert "missing fitted feature columns" in str(exc.value)


def test_unfitted_raises():
    detector = RobustStatisticalDetector()
    with pytest.raises(RuntimeError):
        detector.score_samples(pd.DataFrame({"fwd_packets": [1, 2]}))
