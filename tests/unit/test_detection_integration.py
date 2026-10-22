"""
Integration & End-to-End Tests for Detection Pipeline
======================================================
"""
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from detection.isolation_forest import IsolationForestDetector
from detection.statistical import RobustStatisticalDetector
from features.engineering import FeatureEngineer, extract_features_and_labels
from ingestion.schema.canonical_flow import CanonicalFlow
from preprocessing.pipeline import TrafficShieldPreprocessor
from preprocessing.split import chronological_split


def generate_synthetic_flow_records(n: int, start_hour: int = 0) -> list[CanonicalFlow]:
    """Generate synthetic unidirectional CanonicalFlow objects."""
    np.random.seed(42)
    flows: list[CanonicalFlow] = []
    for i in range(n):
        flows.append(CanonicalFlow(
            record_id=f"flow-{start_hour}-{i:04d}",
            flow_end_ts=datetime(2016, 3, 1, (start_hour + i // 60) % 24, i % 60, tzinfo=UTC),
            src_ip=f"10.0.{(i // 256) % 256}.{i % 256}",
            dst_ip="192.168.1.100",
            src_port=40000 + (i % 20000),
            dst_port=80 if i % 2 == 0 else 443,
            protocol_name="TCP",
            fwd_packets=int(np.random.normal(loc=15.0, scale=3.0)),
            fwd_bytes=int(np.random.normal(loc=1200.0, scale=100.0)),
            duration_seconds=float(np.random.uniform(0.5, 2.0)),
            tcp_flags_raw=".A..S.",
            eval_label="background",
        ))
    return flows


def test_end_to_end_detection_pipeline():
    # 1. Ingest Canonical Flows
    flows = generate_synthetic_flow_records(100, start_hour=0)
    train_flows, test_flows = chronological_split(flows, split_point=0.7)

    assert len(train_flows) == 70
    assert len(test_flows) == 30

    # Convert to DataFrames
    train_raw = pd.DataFrame([f.model_dump() for f in train_flows])
    test_raw = pd.DataFrame([f.model_dump() for f in test_flows])

    # 2. Extract Features, Labels, and Metadata
    train_feat, train_labels, train_meta = extract_features_and_labels(train_raw)
    test_feat, test_labels, test_meta = extract_features_and_labels(test_raw)

    assert "eval_label" not in train_feat.columns
    assert "src_ip" not in train_feat.columns
    assert "record_id" not in train_feat.columns
    assert "record_id" in train_meta.columns

    # 3. Fit Preprocessing Pipeline Strictly on Train
    preprocessor = TrafficShieldPreprocessor(scaler="standard")
    preprocessor.fit(train_feat)

    train_X = preprocessor.transform_df(train_feat)
    test_X = preprocessor.transform_df(test_feat)

    # 4. Fit Detectors Strictly on Preprocessed Training Data
    stat_detector = RobustStatisticalDetector(aggregation="max")
    stat_detector.fit(train_X)
    stat_cal_scores = stat_detector.score_samples(train_X)
    stat_threshold = stat_detector.calibrate_threshold(stat_cal_scores, quantile=0.95)
    assert np.isfinite(stat_threshold)

    iforest_detector = IsolationForestDetector(n_estimators=50, random_state=42)
    iforest_detector.fit(train_X)
    iforest_cal_scores = iforest_detector.score_samples(train_X)
    iforest_threshold = iforest_detector.calibrate_threshold(iforest_cal_scores, quantile=0.95)
    assert np.isfinite(iforest_threshold)

    # 5. Score Test Data with Frozen Parameters and Frozen Thresholds
    test_stat_scores = stat_detector.score_samples(test_X)
    test_stat_preds = stat_detector.predict(test_X)

    test_iforest_scores = iforest_detector.score_samples(test_X)
    test_iforest_preds = iforest_detector.predict(test_X)

    assert len(test_stat_scores) == 30
    assert len(test_iforest_scores) == 30
    assert np.all(np.isfinite(test_stat_scores))
    assert np.all(np.isfinite(test_iforest_scores))

    # 6. Re-associate Scored Output with Provenance Metadata
    scored_results = test_meta[["record_id", "src_ip", "dst_ip", "flow_end_ts"]].copy()
    scored_results["stat_anomaly_score"] = test_stat_scores
    scored_results["stat_is_anomaly"] = test_stat_preds
    scored_results["iforest_anomaly_score"] = test_iforest_scores
    scored_results["iforest_is_anomaly"] = test_iforest_preds

    assert "record_id" in scored_results.columns
    assert len(scored_results) == 30


def test_label_mutation_has_zero_influence_on_detector():
    """Modifying ground-truth labels has 0 impact on feature matrices or detector scores."""
    flows = generate_synthetic_flow_records(50)
    raw_df = pd.DataFrame([f.model_dump() for f in flows])

    fe = FeatureEngineer()
    X1 = fe.transform_dataframe(raw_df)

    # Change all labels to 'attack'
    raw_df_mutated = raw_df.copy()
    raw_df_mutated["eval_label"] = "attack"
    X2 = fe.transform_dataframe(raw_df_mutated)

    # Feature matrices must be strictly identical
    pd.testing.assert_frame_equal(X1, X2)

    # Preprocess into numeric feature matrices
    prep = TrafficShieldPreprocessor(scaler="standard")
    prep.fit(X1)
    X1_proc = prep.transform_df(X1)
    X2_proc = prep.transform_df(X2)

    # Detector scores must be identical
    det = RobustStatisticalDetector()
    det.fit(X1_proc)
    scores1 = det.score_samples(X1_proc)
    scores2 = det.score_samples(X2_proc)
    np.testing.assert_array_equal(scores1, scores2)


def test_detector_rejects_unencoded_categorical():
    """Verify detector raises clear ValueError when non-numeric columns are passed directly."""
    df = pd.DataFrame({
        "fwd_packets": [10.0, 20.0],
        "protocol_category": ["TCP", "UDP"],
    })
    det = RobustStatisticalDetector()
    with pytest.raises(ValueError) as exc:
        det.fit(df)
    assert "Detector received non-numeric columns" in str(exc.value)
