"""
TrafficShield Milestone 14.2.1: Frozen Model Feature Contract Reconciliation Tests
==================================================================================
Validates:
1. Exact authoritative 13-feature input contract of frozen production detector and preprocessor.
2. Strict rejection of forbidden reverse-direction/response features (res_bdy_len, trans_depth, ct_state_ttl).
3. End-to-end data pipeline alignment: FlowBuilder -> ProductionInferenceService -> Preprocessor -> XGBoost.
4. Deterministic feature ordering and data type preservation.
5. Cryptographic hash immutability of frozen model artifacts.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import joblib
import pytest

from features.policy import PolicyViolationError, get_field_spec
from ingestion.capture.base import PacketEnvelope
from ingestion.flow.flow_builder import UnidirectionalFlowBuilder
from ml.production_service import (
    EXPECTED_DETECTOR_SHA256,
    EXPECTED_PREPROCESSOR_SHA256,
    ProductionInferenceService,
)

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
    "is_sm_ips_ports",
    "packet_rate",
    "byte_rate",
    "bytes_per_packet",
]


class TestFrozenModelFeatureContract:
    """Validate authoritative feature contracts directly against joblib artifacts."""

    def test_artifact_hashes_strictly_preserved(self) -> None:
        det_path = Path("artifacts/models/production_detector.joblib")
        prep_path = Path("artifacts/models/production_preprocessor.joblib")

        assert det_path.exists(), "production_detector.joblib missing"
        assert prep_path.exists(), "production_preprocessor.joblib missing"

        with open(det_path, "rb") as f:
            actual_det_sha = hashlib.sha256(f.read()).hexdigest()
        with open(prep_path, "rb") as f:
            actual_prep_sha = hashlib.sha256(f.read()).hexdigest()

        assert actual_det_sha == EXPECTED_DETECTOR_SHA256
        assert actual_prep_sha == EXPECTED_PREPROCESSOR_SHA256

    def test_preprocessor_authoritative_feature_names(self) -> None:
        prep_path = Path("artifacts/models/production_preprocessor.joblib")
        prep = joblib.load(prep_path)

        assert hasattr(prep, "feature_names_in_")
        assert list(prep.feature_names_in_) == EXPECTED_13_FEATURES
        assert hasattr(prep, "numeric_features_")
        assert len(prep.numeric_features_) == 12
        assert hasattr(prep, "boolean_features_")
        assert list(prep.boolean_features_) == ["is_sm_ips_ports"]

    def test_detector_authoritative_feature_names_and_dimension(self) -> None:
        det_path = Path("artifacts/models/production_detector.joblib")
        det = joblib.load(det_path)

        assert det.n_features_in_ == 13
        booster = det.get_booster()
        # Booster features match preprocessor feature_names_out_
        expected_booster_names = [
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
        assert booster.feature_names == expected_booster_names


class TestForbiddenFeatureRejection:
    """Verify response-dependent and bidirectional features are strictly rejected."""

    @pytest.mark.parametrize("forbidden_col", ["res_bdy_len", "trans_depth", "ct_state_ttl"])
    def test_policy_classifies_discrepant_features_as_forbidden(self, forbidden_col: str) -> None:
        spec = get_field_spec(forbidden_col)
        assert spec is not None
        assert spec.role.value == "forbidden", f"{forbidden_col} must be classified as forbidden"

    def test_inference_service_rejects_forbidden_columns(self) -> None:
        service = ProductionInferenceService(verify_checksums=True)
        # Attempt to feed a record containing reverse-dependent features
        flow_with_forbidden = {
            "duration_seconds": 1.0,
            "fwd_bytes": 100,
            "sttl": 64,
            "sload": 800.0,
            "fwd_packets": 2,
            "swin": 1024,
            "smeansz": 50.0,
            "sjit": 1.0,
            "sintpkt": 10.0,
            "is_sm_ips_ports": 0,
            "res_bdy_len": 500,  # Forbidden reverse feature
        }
        with pytest.raises(PolicyViolationError) as exc_info:
            service.predict_single(flow_with_forbidden)
        assert "Forbidden reverse-dependent columns" in str(exc_info.value)


class TestEndToEndPipelineAlignment:
    """Trace flow generation from FlowBuilder to ProductionInferenceService."""

    def test_flow_builder_output_satisfies_inference_service(self) -> None:
        builder = UnidirectionalFlowBuilder()
        service = ProductionInferenceService(verify_checksums=True)

        # Feed 2 valid packets
        p1 = PacketEnvelope(
            timestamp=100.0,
            ip_src="10.0.0.1",
            ip_dst="192.168.1.1",
            src_port=54321,
            dst_port=443,
            protocol="TCP",
            ttl=64,
            byte_length=60,
            tcp_window=64240,
        )
        p2 = PacketEnvelope(
            timestamp=100.1,
            ip_src="10.0.0.1",
            ip_dst="192.168.1.1",
            src_port=54321,
            dst_port=443,
            protocol="TCP",
            ttl=64,
            byte_length=120,
            tcp_window=64240,
        )

        builder.process_packet(p1)
        builder.process_packet(p2)
        flows = builder.flush()

        assert len(flows) == 1
        flow = flows[0]

        # Verify all 13 model input components are present
        for feat in EXPECTED_13_FEATURES:
            assert feat in flow, f"Missing feature {feat} in finalized flow"

        # Predict single using production inference service
        result = service.predict_single(flow)
        assert "anomaly_score" in result
        assert 0.0 <= result["anomaly_score"] <= 1.0
        assert result["model_name"] in ("XGBClassifier", "OptunaTuned_XGBoost")
        assert result["risk_level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
