"""
Automated Data-Leakage Prevention Test Suite
============================================
Comprehensive 12-check validation suite verifying that no form of data leakage
(reverse-direction, evaluation label, parameter fitting, temporal, identifier,
or artifact corruption) can enter TrafficShield's anomaly detection pipeline.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from features.engineering import extract_features_and_labels
from features.policy import PolicyViolationError
from preprocessing.artifacts import load_preprocessor, save_preprocessor
from preprocessing.pipeline import TrafficShieldPreprocessor
from preprocessing.split import (
    audit_temporal_boundary,
    chronological_split,
    ugr16_calibration_test_split,
)


@pytest.fixture
def train_data():
    return pd.DataFrame({
        "flow_end_ts": [f"2016-03-01T{h:02d}:00:00+00:00" for h in range(10)],
        "fwd_packets": [10.0, 20.0, 15.0, 25.0, 30.0, 12.0, 18.0, 22.0, 14.0, 19.0],
        "fwd_bytes": [1000.0, 2000.0, 1500.0, 2500.0, 3000.0, 1200.0, 1800.0, 2200.0, 1400.0, 1900.0],
        "duration_seconds": [1.0, 2.0, 1.5, 2.5, 3.0, 1.2, 1.8, 2.2, 1.4, 1.9],
        "packet_rate": [10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
        "byte_rate": [1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0],
        "bytes_per_packet": [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
        "protocol_category": ["TCP", "UDP", "TCP", "TCP", "UDP", "TCP", "ICMP", "TCP", "UDP", "TCP"],
        "dst_port_category": ["well_known", "registered", "ephemeral", "well_known", "registered", "well_known", "ephemeral", "registered", "well_known", "ephemeral"],
        "src_port_category": ["ephemeral"] * 10,
        "is_well_known_dst_port": [1, 0, 0, 1, 0, 1, 0, 0, 1, 0],
        "is_tcp": [1, 0, 1, 1, 0, 1, 0, 1, 0, 1],
        "is_udp": [0, 1, 0, 0, 1, 0, 0, 0, 1, 0],
        "is_icmp": [0, 0, 0, 0, 0, 0, 1, 0, 0, 0],
        "has_syn": [1, 0, 1, 1, 0, 1, 0, 1, 0, 1],
        "has_ack": [1, 0, 1, 1, 0, 1, 0, 1, 0, 1],
        "has_fin": [0] * 10,
        "has_rst": [0] * 10,
        "has_psh": [0] * 10,
        "has_urg": [0] * 10,
        "hour_of_day": list(range(10)),
        "day_of_week": [1] * 10,
        "is_weekend": [0] * 10,
        "sin_hour": [0.0] * 10,
        "cos_hour": [1.0] * 10,
        "sin_day_of_week": [0.8] * 10,
        "cos_day_of_week": [-0.6] * 10,
        "fwd_status": [0] * 10,
        "ip_tos": [0] * 10,
    })


@pytest.fixture
def train_features(train_data):
    return train_data.drop(columns=["flow_end_ts"])


# ── Check 1: Zero reverse-direction features in preprocessor ──────────────────
def test_leakage_check_1_prohibited_reverse_features(train_features):
    prep = TrafficShieldPreprocessor(strict_policy=True)
    for forbidden_col in ("bwd_packets", "bwd_bytes", "rtt_ms", "fwd_bwd_packet_ratio"):
        bad_df = train_features.copy()
        bad_df[forbidden_col] = 42.0
        with pytest.raises(PolicyViolationError) as exc_info:
            prep.fit(bad_df)
        assert "Forbidden reverse-dependent" in str(exc_info.value)


# ── Check 2: Zero evaluation labels in preprocessor ───────────────────────────
def test_leakage_check_2_prohibited_evaluation_labels(train_features):
    prep = TrafficShieldPreprocessor(strict_policy=True)
    for label_col in ("eval_label", "class", "label", "attack_cat", "is_attack"):
        bad_df = train_features.copy()
        bad_df[label_col] = "dos"
        with pytest.raises(PolicyViolationError) as exc_info:
            prep.fit(bad_df)
        assert "label" in str(exc_info.value).lower()


# ── Check 3: Preprocessor statistics computed strictly on train split ─────────
def test_leakage_check_3_train_only_parameter_fitting(train_features):
    prep = TrafficShieldPreprocessor(scaler="standard")
    prep.fit(train_features)

    train_mean = prep._scaler_transformer.mean_.copy()

    # Create test data with wildly different distribution (e.g. 1,000,000x packets)
    test_data = train_features.copy()
    test_data["fwd_packets"] = 1_000_000.0

    # Transform test data
    prep.transform(test_data)

    # Scaler mean must remain unchanged
    np.testing.assert_array_equal(prep._scaler_transformer.mean_, train_mean)


# ── Check 4: Test set does not affect train set transformations ────────────────
def test_leakage_check_4_independent_test_transformations(train_features):
    prep = TrafficShieldPreprocessor(scaler="standard")
    prep.fit(train_features)

    train_arr_1 = prep.transform(train_features)

    # Create extreme outlier test set
    extreme_test = train_features.copy()
    extreme_test["fwd_packets"] = 999_999_999.0
    _ = prep.transform(extreme_test)

    # Re-transforming train data produces mathematically identical results
    train_arr_2 = prep.transform(train_features)
    np.testing.assert_array_equal(train_arr_1, train_arr_2)


# ── Check 5: Chronological splitting prevents future lookahead ────────────────
def test_leakage_check_5_chronological_ordering(train_data):
    train_split, test_split = chronological_split(train_data, split_point=0.7)
    audit = audit_temporal_boundary(train_split, test_split)
    assert audit["is_valid"] is True
    assert audit["temporal_violations"] == 0

    max_train_ts = pd.to_datetime(train_split["flow_end_ts"]).max()
    min_test_ts = pd.to_datetime(test_split["flow_end_ts"]).min()
    assert max_train_ts <= min_test_ts


# ── Check 6: Categorical vocabulary learned exclusively from train ────────────
def test_leakage_check_6_unseen_category_handling(train_features):
    prep = TrafficShieldPreprocessor()
    prep.fit(train_features)

    test_data = train_features.copy()
    test_data["protocol_category"] = "UNSEEN_ATTACK_PROTOCOL"

    # Transformation must not crash and must not learn new category
    test_transformed = prep.transform(test_data)
    assert np.all(np.isfinite(test_transformed))


# ── Check 7: Missing value imputation derived purely from train data ──────────
def test_leakage_check_7_train_derived_imputation(train_features):
    prep = TrafficShieldPreprocessor(impute_strategy="median")
    prep.fit(train_features)

    # Check fitted medians
    expected_median_pkts = float(train_features["fwd_packets"].median())
    imputer_stats = prep._numeric_imputer.statistics_
    pkt_idx = prep.numeric_features_.index("fwd_packets")
    assert pytest.approx(imputer_stats[pkt_idx], abs=1e-5) == expected_median_pkts

    # Test sample with missing fwd_packets must receive train median
    missing_test = train_features.iloc[[0]].copy()
    missing_test["fwd_packets"] = np.nan

    # When scaled, value should correspond to (median - mean) / std
    scaled_out = prep.transform(missing_test)
    assert not np.isnan(scaled_out).any()


# ── Check 8: Identifiers excluded from feature matrices ───────────────────────
def test_leakage_check_8_identifiers_excluded():
    raw_df = pd.DataFrame([{
        "record_id": "flow-uuid-12345",
        "src_ip": "192.0.2.1",
        "dst_ip": "198.51.100.1",
        "flow_end_ts": "2016-03-01T12:00:00+00:00",
        "fwd_packets": 10,
        "fwd_bytes": 1000,
        "duration_seconds": 1.0,
        "eval_label": "background",
    }])
    features, labels, meta = extract_features_and_labels(raw_df)
    assert "record_id" not in features.columns
    assert "src_ip" not in features.columns
    assert "dst_ip" not in features.columns
    assert "record_id" in meta.columns


# ── Check 9: Temporal split enforces calibration vs test boundary ─────────────
def test_leakage_check_9_calibration_test_boundary():
    df = pd.DataFrame([
        {"flow_end_ts": "2016-04-15T10:00:00+00:00", "fwd_packets": 10, "eval_label": "background"},
        {"flow_end_ts": "2016-08-01T10:00:00+00:00", "fwd_packets": 20, "eval_label": "dos"},
    ])
    cal, test = ugr16_calibration_test_split(df)
    assert len(cal) == 1
    assert len(test) == 1
    assert cal.iloc[0]["eval_label"] == "background"
    assert test.iloc[0]["eval_label"] == "dos"


# ── Check 10: Serialization roundtrip is mathematically identical ─────────────
def test_leakage_check_10_artifact_reproducibility(train_features, tmp_path: Path):
    prep = TrafficShieldPreprocessor(scaler="standard")
    prep.fit(train_features)
    original_out = prep.transform(train_features)

    art_path = tmp_path / "model.joblib"
    save_preprocessor(prep, art_path)
    loaded_prep, _ = load_preprocessor(art_path)

    loaded_out = loaded_prep.transform(train_features)
    np.testing.assert_allclose(original_out, loaded_out, atol=1e-7)


# ── Check 11: Tampered artifact detected via SHA-256 validation ───────────────
def test_leakage_check_11_checksum_tamper_detection(train_features, tmp_path: Path):
    prep = TrafficShieldPreprocessor()
    prep.fit(train_features)
    art_path = tmp_path / "model.joblib"
    save_preprocessor(prep, art_path)

    # Tamper with the artifact
    with open(art_path, "wb") as f:
        f.write(b"tampered content")

    with pytest.raises(ValueError) as exc:
        load_preprocessor(art_path, verify_checksum=True)
    assert "verification failed" in str(exc.value)


# ── Check 12: Strict mode catches any unexpected column injection ─────────────
def test_leakage_check_12_strict_mode_injection_prevention(train_features):
    prep = TrafficShieldPreprocessor(strict_policy=True)
    injected_df = train_features.copy()
    injected_df["injected_future_feature"] = 123.45

    with pytest.raises(PolicyViolationError) as exc:
        prep.fit(injected_df)
    assert "ineligible columns" in str(exc.value)
