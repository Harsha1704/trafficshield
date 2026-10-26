"""
TrafficShield Milestone 14.2.2: Preprocessor Output Consistency & Feature Ordering Tests
========================================================================================
Validates:
1. Exact transformer configuration, feature_names_in_ vs feature_names_out_.
2. Verification that boolean feature is_sm_ips_ports maps strictly to identity (0 -> 0.0, 1 -> 1.0) at index 12.
3. 1-to-1 alignment between preprocessor.feature_names_out_ and detector.get_booster().feature_names.
4. Exact mathematical formula verification of RobustScaler center and scale parameters.
5. Deterministic scoring through ProductionInferenceService.
6. Bit-identical artifact hash integrity.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from features.policy import PolicyViolationError
from ml.production_service import (
    EXPECTED_DETECTOR_SHA256,
    EXPECTED_PREPROCESSOR_SHA256,
    ProductionInferenceService,
)


class TestPreprocessorConsistency:
    """Validate preprocessor transformer ordering, scaling math, and output naming."""

    def test_artifact_hashes_unmodified(self) -> None:
        det_path = Path("artifacts/models/production_detector.joblib")
        prep_path = Path("artifacts/models/production_preprocessor.joblib")

        assert det_path.exists()
        assert prep_path.exists()

        with open(det_path, "rb") as f:
            assert hashlib.sha256(f.read()).hexdigest() == EXPECTED_DETECTOR_SHA256
        with open(prep_path, "rb") as f:
            assert hashlib.sha256(f.read()).hexdigest() == EXPECTED_PREPROCESSOR_SHA256

    def test_feature_order_alignment_with_detector_booster(self) -> None:
        service = ProductionInferenceService(verify_checksums=True)
        prep = service.preprocessor
        det = service.model

        # Booster feature names must match preprocessor feature_names_out_ exactly
        booster_names = det.get_booster().feature_names
        assert prep.feature_names_out_ == booster_names

        # Verify is_sm_ips_ports is located at index 12 in output, not index 9
        assert prep.feature_names_out_[12] == "is_sm_ips_ports"
        assert booster_names[12] == "is_sm_ips_ports"

        # Verify index 9 in feature_names_out_ is packet_rate
        assert prep.feature_names_out_[9] == "packet_rate"
        assert booster_names[9] == "packet_rate"

    def test_is_sm_ips_ports_transforms_strictly_to_unscaled_binary(self) -> None:
        service = ProductionInferenceService(verify_checksums=True)
        prep = service.preprocessor

        # Test both 0 and 1
        for expected_val in [0.0, 1.0]:
            raw_flow: dict[str, Any] = {
                "duration_seconds": 1.0,
                "fwd_bytes": 100.0,
                "sttl": 64.0,
                "sload": 800.0,
                "fwd_packets": 2.0,
                "swin": 1024.0,
                "smeansz": 50.0,
                "sjit": 1.0,
                "sintpkt": 10.0,
                "is_sm_ips_ports": expected_val,
            }
            df = service.validate_and_prepare_input(raw_flow)
            transformed_arr = prep.transform(df)
            transformed_df = prep.transform_df(df)

            # Check index 12 in array
            assert transformed_arr[0][12] == expected_val
            # Check named column in transformed DataFrame
            assert transformed_df["is_sm_ips_ports"].iloc[0] == expected_val

    def test_robust_scaler_mathematical_precision(self) -> None:
        service = ProductionInferenceService(verify_checksums=True)
        prep = service.preprocessor
        scaler = prep._scaler_transformer

        raw_flow: dict[str, Any] = {
            "duration_seconds": 0.2,
            "fwd_bytes": 240.0,
            "sttl": 64.0,
            "sload": 7999.9981,
            "fwd_packets": 6.0,
            "swin": 65535.0,
            "smeansz": 40.0,
            "sjit": 0.0,
            "sintpkt": 40.0,
            "is_sm_ips_ports": 0.0,
        }
        df = service.validate_and_prepare_input(raw_flow)
        transformed_df = prep.transform_df(df)

        for col, center, scale in zip(prep.numeric_features_, scaler.center_, scaler.scale_, strict=False):
            raw_val = df[col].iloc[0]
            expected_scaled = (raw_val - center) / scale
            actual_scaled = transformed_df[col].iloc[0]
            assert np.isclose(actual_scaled, expected_scaled, atol=1e-5), (
                f"Mismatch for {col}: expected {expected_scaled}, got {actual_scaled}"
            )

    def test_deterministic_scoring_reproducibility(self) -> None:
        service = ProductionInferenceService(verify_checksums=True)
        raw_flow: dict[str, Any] = {
            "duration_seconds": 0.2,
            "fwd_bytes": 240.0,
            "sttl": 64.0,
            "sload": 7999.9981,
            "fwd_packets": 6.0,
            "swin": 65535.0,
            "smeansz": 40.0,
            "sjit": 0.0,
            "sintpkt": 40.0,
            "is_sm_ips_ports": 0.0,
        }
        res1 = service.predict_single(raw_flow)
        res2 = service.predict_single(raw_flow)

        assert res1["anomaly_score"] == res2["anomaly_score"]
        assert res1["is_anomaly"] == res2["is_anomaly"]
        assert res1["risk_level"] == res2["risk_level"]
        assert res1["top_contributing_features"] == res2["top_contributing_features"]

    def test_forbidden_columns_rejected_before_preprocessor(self) -> None:
        service = ProductionInferenceService(verify_checksums=True)
        invalid_flow: dict[str, Any] = {
            "duration_seconds": 1.0,
            "fwd_bytes": 100.0,
            "sttl": 64.0,
            "sload": 800.0,
            "fwd_packets": 2.0,
            "swin": 1024.0,
            "smeansz": 50.0,
            "sjit": 1.0,
            "sintpkt": 10.0,
            "is_sm_ips_ports": 0.0,
            "res_bdy_len": 100.0,
        }
        with pytest.raises(PolicyViolationError):
            service.predict_single(invalid_flow)
