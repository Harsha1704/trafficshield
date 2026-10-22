"""
Unit Tests for Preprocessing Pipeline
======================================
"""
import numpy as np
import pandas as pd
import pytest

from features.policy import PolicyViolationError
from preprocessing.pipeline import TrafficShieldPreprocessor


@pytest.fixture
def sample_feature_df():
    return pd.DataFrame({
        "fwd_packets": [10.0, 50.0, 100.0, 20.0],
        "fwd_bytes": [1000.0, 5000.0, 10000.0, 2000.0],
        "duration_seconds": [1.0, 5.0, 10.0, 2.0],
        "packet_rate": [10.0, 10.0, 10.0, 10.0],
        "byte_rate": [1000.0, 1000.0, 1000.0, 1000.0],
        "bytes_per_packet": [100.0, 100.0, 100.0, 100.0],
        "log_fwd_packets": np.log1p([10.0, 50.0, 100.0, 20.0]),
        "log_fwd_bytes": np.log1p([1000.0, 5000.0, 10000.0, 2000.0]),
        "log_duration": np.log1p([1.0, 5.0, 10.0, 2.0]),
        "log_packet_rate": np.log1p([10.0, 10.0, 10.0, 10.0]),
        "log_byte_rate": np.log1p([1000.0, 1000.0, 1000.0, 1000.0]),
        "log_bytes_per_packet": np.log1p([100.0, 100.0, 100.0, 100.0]),
        "protocol_category": ["TCP", "UDP", "TCP", "ICMP"],
        "dst_port_category": ["well_known", "registered", "well_known", "ephemeral"],
        "src_port_category": ["ephemeral", "ephemeral", "registered", "well_known"],
        "is_well_known_dst_port": [1, 0, 1, 0],
        "is_tcp": [1, 0, 1, 0],
        "is_udp": [0, 1, 0, 0],
        "is_icmp": [0, 0, 0, 1],
        "has_syn": [1, 0, 1, 0],
        "has_ack": [1, 0, 1, 0],
        "has_fin": [0, 0, 1, 0],
        "has_rst": [0, 0, 0, 0],
        "has_psh": [1, 0, 0, 0],
        "has_urg": [0, 0, 0, 0],
        "hour_of_day": [8, 12, 16, 20],
        "day_of_week": [0, 1, 2, 3],
        "is_weekend": [0, 0, 0, 0],
        "sin_hour": [0.5, 0.0, -0.5, -0.8],
        "cos_hour": [0.8, -1.0, -0.8, 0.5],
        "sin_day_of_week": [0.0, 0.7, 0.9, 0.4],
        "cos_day_of_week": [1.0, 0.6, -0.2, -0.9],
        "fwd_status": [0, 0, 0, 0],
        "ip_tos": [0, 0, 0, 0],
    })


def test_fit_transform_basic(sample_feature_df):
    prep = TrafficShieldPreprocessor(scaler="standard")
    prep.fit(sample_feature_df)

    assert prep.is_fitted_
    assert len(prep.feature_names_in_) > 0
    assert len(prep.feature_names_out_) > 0

    arr = prep.transform(sample_feature_df)
    assert isinstance(arr, np.ndarray)
    assert arr.shape[0] == len(sample_feature_df)
    assert arr.shape[1] == len(prep.feature_names_out_)
    assert np.all(np.isfinite(arr))


def test_transform_df_preserves_structure(sample_feature_df):
    prep = TrafficShieldPreprocessor(scaler="standard")
    prep.fit(sample_feature_df)
    df_out = prep.transform_df(sample_feature_df)

    assert isinstance(df_out, pd.DataFrame)
    assert list(df_out.columns) == prep.feature_names_out_
    assert list(df_out.index) == list(sample_feature_df.index)


@pytest.mark.parametrize("scaler_type", ["standard", "robust", "minmax", "none", None])
def test_scaler_options(sample_feature_df, scaler_type):
    prep = TrafficShieldPreprocessor(scaler=scaler_type)
    prep.fit(sample_feature_df)
    arr = prep.transform(sample_feature_df)
    assert np.all(np.isfinite(arr))
    if scaler_type == "minmax":
        # Check numeric columns are in [0, 1] approximately
        num_cols_idx = [i for i, c in enumerate(prep.feature_names_out_) if c in prep.numeric_features_]
        assert (arr[:, num_cols_idx] >= -1e-6).all()
        assert (arr[:, num_cols_idx] <= 1.0 + 1e-6).all()


def test_unseen_categories_inference(sample_feature_df):
    prep = TrafficShieldPreprocessor(handle_unknown_categories="ignore")
    prep.fit(sample_feature_df)

    # Test set containing previously unobserved protocol category
    test_df = sample_feature_df.copy()
    test_df.loc[0, "protocol_category"] = "UNSEEN_CUSTOM_PROTOCOL"
    test_df.loc[0, "dst_port_category"] = "UNKNOWN_NEW_PORT"

    arr = prep.transform(test_df)
    assert np.all(np.isfinite(arr))
    assert arr.shape[0] == len(test_df)


def test_missing_values_imputation(sample_feature_df):
    prep = TrafficShieldPreprocessor(impute_strategy="median")
    prep.fit(sample_feature_df)

    test_df = sample_feature_df.copy()
    test_df.loc[0, "fwd_packets"] = np.nan
    test_df.loc[1, "duration_seconds"] = np.nan

    arr = prep.transform(test_df)
    assert np.all(np.isfinite(arr))
    assert not np.isnan(arr).any()


def test_column_reordering_stability(sample_feature_df):
    prep = TrafficShieldPreprocessor()
    prep.fit(sample_feature_df)

    arr_original = prep.transform(sample_feature_df)

    # Permute columns in test DataFrame
    shuffled_cols = list(sample_feature_df.columns)[::-1]
    shuffled_df = sample_feature_df[shuffled_cols]

    arr_shuffled = prep.transform(shuffled_df)
    np.testing.assert_allclose(arr_original, arr_shuffled, atol=1e-7)


def test_unfitted_transform_raises():
    prep = TrafficShieldPreprocessor()
    with pytest.raises(RuntimeError) as exc:
        prep.transform(pd.DataFrame({"fwd_packets": [1, 2]}))
    assert "must be fit before" in str(exc.value)


def test_fit_empty_raises():
    prep = TrafficShieldPreprocessor()
    with pytest.raises(ValueError):
        prep.fit(pd.DataFrame())


def test_strict_mode_rejects_ineligible_columns(sample_feature_df):
    prep = TrafficShieldPreprocessor(strict_policy=True)
    bad_df = sample_feature_df.copy()
    bad_df["bwd_packets"] = 100.0

    with pytest.raises(PolicyViolationError) as exc:
        prep.fit(bad_df)
    assert "Forbidden reverse-dependent" in str(exc.value)


def test_sklearn_compatibility(sample_feature_df):
    prep = TrafficShieldPreprocessor(scaler="robust", impute_strategy="mean")
    params = prep.get_params()
    assert params["scaler"] == "robust"
    assert params["impute_strategy"] == "mean"

    prep.set_params(scaler="standard")
    assert prep.scaler == "standard"
