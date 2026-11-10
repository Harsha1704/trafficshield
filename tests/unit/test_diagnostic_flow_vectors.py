"""
Unit tests for Diagnostic Flow Vectors, Feature Parity, and Numerical Edge Cases.
=================================================================================
Milestone 3.2d — Phase 3 Hybrid ML Completion

Validates:
1. Mathematical equivalence between flow builder rate derivations and inference service.
2. Robustness across extreme durations (down to 1 ns), varied TTLs, packet counts, and ports.
3. Strict finite outputs (np.isfinite, no NaN/Inf) across all model evaluations.
4. Input policy enforcement (rejection of forbidden reverse features, missing keys, non-numerics).
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from features.policy import PolicyViolationError
from ingestion.capture.base import PacketEnvelope
from ingestion.flow.flow_builder import ActiveFlowState
from ml.production_service import ProductionInferenceService


@pytest.fixture(scope="module")
def prod_service():
    """Instantiate production inference service once for diagnostic tests."""
    return ProductionInferenceService(verify_checksums=True)


def test_rate_derivation_parity_with_flow_builder():
    """Verify rate calculations in ActiveFlowState.finalize match validate_and_prepare_input."""
    service = ProductionInferenceService(verify_checksums=False)

    test_scenarios = [
        # (dur, pkts, bytes, name)
        (0.0, 1, 140, "zero_duration_single_packet"),
        (0.000002, 2, 280, "two_microseconds_two_packets"),
        (0.05, 10, 5000, "50ms_ten_packets"),
        (1.0, 150, 100000, "one_second_150_packets"),
        (60.0, 1200, 1500000, "one_minute_bulk_flow"),
    ]

    for dur, pkts, total_bytes, _name in test_scenarios:
        # Build flow using ActiveFlowState
        state = ActiveFlowState(
            flow_key=("192.168.1.10", "192.168.1.1", 12345, 80, "TCP"),
            first_timestamp=1000.0,
            last_timestamp=1000.0 + dur,
        )
        for i in range(pkts):
            pkt_ts = 1000.0 + (dur * i / (pkts - 1)) if pkts > 1 else 1000.0
            state.add_packet(
                PacketEnvelope(
                    timestamp=pkt_ts,
                    ip_src="192.168.1.10",
                    ip_dst="192.168.1.1",
                    src_port=12345,
                    dst_port=80,
                    protocol="TCP",
                    byte_length=total_bytes // pkts,
                    ttl=64,
                    tcp_window=255,
                )
            )

        flow_dict = state.finalize()

        # Validate with inference service
        df_input = service.validate_and_prepare_input(flow_dict)

        actual_dur = flow_dict["duration_seconds"]
        actual_bytes = flow_dict["fwd_bytes"]
        # Check rate parity
        expected_pkt_rate = (pkts / actual_dur) if actual_dur > 0 else 0.0
        expected_byte_rate = (actual_bytes / actual_dur) if actual_dur > 0 else 0.0
        expected_bpp = (actual_bytes / pkts) if pkts > 0 else 0.0

        assert math.isclose(flow_dict["packet_rate"], df_input["packet_rate"].iloc[0], rel_tol=1e-4, abs_tol=1e-4)
        assert math.isclose(flow_dict["byte_rate"], df_input["byte_rate"].iloc[0], rel_tol=1e-4, abs_tol=1e-4)
        assert math.isclose(flow_dict["bytes_per_packet"], df_input["bytes_per_packet"].iloc[0], rel_tol=1e-4, abs_tol=1e-4)
        assert math.isclose(df_input["packet_rate"].iloc[0], expected_pkt_rate, rel_tol=1e-4, abs_tol=1e-4)
        assert math.isclose(df_input["byte_rate"].iloc[0], expected_byte_rate, rel_tol=1e-4, abs_tol=1e-4)
        assert math.isclose(df_input["bytes_per_packet"].iloc[0], expected_bpp, rel_tol=1e-4, abs_tol=1e-4)


# 36 structured test combinations covering edge cases
DIAGNOSTIC_CASES = [
    # 7 Durations: 0.0, 1e-9, 1e-6, 2e-6, 1e-3, 1.0, 60.0
    # 4 TTLs: 32, 64, 128, 255
    # 8 Ports: UDP 53, 137, 1900, 5353, 5355, 57621; TCP 80, 443
    # 5 Packet counts: 1, 2, 10, 150, 1200
    # Group 1: Zero duration single-packet flows across various protocols and TTLs
    {"duration": 0.0, "pkts": 1, "bytes": 60, "sttl": 64, "port": 53, "proto": "UDP", "swin": 0},
    {"duration": 0.0, "pkts": 1, "bytes": 78, "sttl": 128, "port": 137, "proto": "UDP", "swin": 0},
    {"duration": 0.0, "pkts": 1, "bytes": 140, "sttl": 255, "port": 5353, "proto": "UDP", "swin": 0},
    {"duration": 0.0, "pkts": 1, "bytes": 84, "sttl": 255, "port": 5355, "proto": "UDP", "swin": 0},
    {"duration": 0.0, "pkts": 1, "bytes": 350, "sttl": 32, "port": 1900, "proto": "UDP", "swin": 0},
    {"duration": 0.0, "pkts": 1, "bytes": 54, "sttl": 64, "port": 80, "proto": "TCP", "swin": 64240},

    # Group 2: Nanosecond duration (1e-9) flows
    {"duration": 1e-9, "pkts": 1, "bytes": 60, "sttl": 64, "port": 53, "proto": "UDP", "swin": 0},
    {"duration": 1e-9, "pkts": 2, "bytes": 120, "sttl": 128, "port": 137, "proto": "UDP", "swin": 0},
    {"duration": 1e-9, "pkts": 1, "bytes": 140, "sttl": 255, "port": 5353, "proto": "UDP", "swin": 0},
    {"duration": 1e-9, "pkts": 2, "bytes": 100, "sttl": 64, "port": 443, "proto": "TCP", "swin": 16384},

    # Group 3: Microsecond duration (1e-6, 2e-6)
    {"duration": 1e-6, "pkts": 1, "bytes": 70, "sttl": 32, "port": 57621, "proto": "UDP", "swin": 0},
    {"duration": 1e-6, "pkts": 2, "bytes": 140, "sttl": 64, "port": 53, "proto": "UDP", "swin": 0},
    {"duration": 1e-6, "pkts": 1, "bytes": 140, "sttl": 255, "port": 5353, "proto": "UDP", "swin": 0},
    {"duration": 2e-6, "pkts": 2, "bytes": 280, "sttl": 255, "port": 5353, "proto": "UDP", "swin": 0},
    {"duration": 2e-6, "pkts": 2, "bytes": 168, "sttl": 128, "port": 5355, "proto": "UDP", "swin": 0},
    {"duration": 2e-6, "pkts": 2, "bytes": 700, "sttl": 32, "port": 1900, "proto": "UDP", "swin": 0},

    # Group 4: Millisecond duration (1e-3)
    {"duration": 1e-3, "pkts": 2, "bytes": 200, "sttl": 64, "port": 53, "proto": "UDP", "swin": 0},
    {"duration": 1e-3, "pkts": 10, "bytes": 1500, "sttl": 128, "port": 137, "proto": "UDP", "swin": 0},
    {"duration": 1e-3, "pkts": 2, "bytes": 280, "sttl": 255, "port": 5353, "proto": "UDP", "swin": 0},
    {"duration": 1e-3, "pkts": 10, "bytes": 8000, "sttl": 64, "port": 80, "proto": "TCP", "swin": 65535},
    {"duration": 1e-3, "pkts": 10, "bytes": 14000, "sttl": 64, "port": 443, "proto": "TCP", "swin": 65535},
    {"duration": 1e-3, "pkts": 2, "bytes": 500, "sttl": 32, "port": 57621, "proto": "UDP", "swin": 0},

    # Group 5: Moderate duration (1.0 second)
    {"duration": 1.0, "pkts": 1, "bytes": 60, "sttl": 64, "port": 53, "proto": "UDP", "swin": 0},
    {"duration": 1.0, "pkts": 2, "bytes": 156, "sttl": 128, "port": 137, "proto": "UDP", "swin": 0},
    {"duration": 1.0, "pkts": 10, "bytes": 1400, "sttl": 255, "port": 5353, "proto": "UDP", "swin": 0},
    {"duration": 1.0, "pkts": 10, "bytes": 840, "sttl": 255, "port": 5355, "proto": "UDP", "swin": 0},
    {"duration": 1.0, "pkts": 150, "bytes": 120000, "sttl": 64, "port": 80, "proto": "TCP", "swin": 29200},
    {"duration": 1.0, "pkts": 150, "bytes": 200000, "sttl": 128, "port": 443, "proto": "TCP", "swin": 64240},
    {"duration": 1.0, "pkts": 10, "bytes": 3500, "sttl": 32, "port": 1900, "proto": "UDP", "swin": 0},
    {"duration": 1.0, "pkts": 2, "bytes": 200, "sttl": 64, "port": 57621, "proto": "UDP", "swin": 0},

    # Group 6: Extended duration (60.0 seconds) high volume
    {"duration": 60.0, "pkts": 10, "bytes": 600, "sttl": 64, "port": 53, "proto": "UDP", "swin": 0},
    {"duration": 60.0, "pkts": 150, "bytes": 22500, "sttl": 128, "port": 137, "proto": "UDP", "swin": 0},
    {"duration": 60.0, "pkts": 1200, "bytes": 1500000, "sttl": 64, "port": 80, "proto": "TCP", "swin": 65535},
    {"duration": 60.0, "pkts": 1200, "bytes": 1800000, "sttl": 128, "port": 443, "proto": "TCP", "swin": 65535},
    {"duration": 60.0, "pkts": 150, "bytes": 45000, "sttl": 255, "port": 5353, "proto": "UDP", "swin": 0},
    {"duration": 60.0, "pkts": 10, "bytes": 3500, "sttl": 32, "port": 1900, "proto": "UDP", "swin": 0},
]


@pytest.mark.parametrize("case", DIAGNOSTIC_CASES)
def test_diagnostic_flow_vector_execution(prod_service, case):
    """Test inference stability, finite outputs, and hybrid classification across diagnostic cases."""
    dur = case["duration"]
    pkts = case["pkts"]
    bytes_ = case["bytes"]
    smeansz = bytes_ / pkts
    sload = ((pkts - 1) * smeansz * 8.0) / dur if (dur > 0 and pkts > 1) else 0.0
    sintpkt = ((dur * 1000.0) / (pkts - 1)) if pkts > 1 else 0.0

    raw_flow = {
        "duration_seconds": dur,
        "fwd_bytes": bytes_,
        "sttl": case["sttl"],
        "sload": sload,
        "fwd_packets": pkts,
        "swin": case["swin"],
        "smeansz": smeansz,
        "sjit": 0.0,
        "sintpkt": sintpkt,
        "is_sm_ips_ports": 0,
    }

    result = prod_service.predict_single(raw_flow)

    # 1. Output existence
    assert "anomaly_score" in result
    assert "decision_threshold" in result
    assert "is_anomaly" in result
    assert "hybrid_classification" in result
    assert "supervised" in result
    assert "unsupervised" in result

    # 2. Strict numerical finiteness (no NaN, no Inf)
    score = result["anomaly_score"]
    thresh = result["decision_threshold"]
    assert np.isfinite(score), f"anomaly_score must be finite, got {score}"
    assert np.isfinite(thresh), f"decision_threshold must be finite, got {thresh}"
    assert 0.0 <= score <= 1.0, f"Supervised anomaly score out of [0, 1]: {score}"

    # 3. Supervised & Unsupervised evidence validation
    sup_prob = result["supervised"]["probability"]
    assert np.isfinite(sup_prob)
    assert 0.0 <= sup_prob <= 1.0

    unsup_score = result["unsupervised"]["anomaly_score"]
    assert np.isfinite(unsup_score), f"unsupervised anomaly_score must be finite, got {unsup_score}"

    # 4. Valid classification taxonomy
    valid_classes = {
        "NORMAL_TRAFFIC",
        "SUPERVISED_ONLY_ALERT",
        "UNSUPERVISED_NOVELTY",
        "DUAL_CONFIRMED",
    }
    assert result["hybrid_classification"] in valid_classes


def test_invalid_input_rejection(prod_service):
    """Test policy rejection of forbidden reverse fields, missing keys, and invalid types."""
    # 1. Forbidden reverse columns
    forbidden_flow = {
        "duration_seconds": 0.05,
        "fwd_bytes": 1000,
        "sttl": 64,
        "sload": 160000.0,
        "fwd_packets": 10,
        "swin": 255,
        "smeansz": 100.0,
        "sjit": 0.0,
        "sintpkt": 5.0,
        "is_sm_ips_ports": 0,
        "dbytes": 500,  # Forbidden reverse feature
    }
    with pytest.raises(PolicyViolationError):
        prod_service.predict_single(forbidden_flow)

    # 2. Missing required base feature
    missing_flow = {
        "duration_seconds": 0.05,
        "fwd_bytes": 1000,
        # missing sttl
        "sload": 160000.0,
        "fwd_packets": 10,
        "swin": 255,
        "smeansz": 100.0,
        "sjit": 0.0,
        "sintpkt": 5.0,
        "is_sm_ips_ports": 0,
    }
    with pytest.raises(ValueError, match="Missing required forward observable features"):
        prod_service.predict_single(missing_flow)

    # 3. Non-numeric value
    non_numeric_flow = {
        "duration_seconds": "invalid_duration",
        "fwd_bytes": 1000,
        "sttl": 64,
        "sload": 160000.0,
        "fwd_packets": 10,
        "swin": 255,
        "smeansz": 100.0,
        "sjit": 0.0,
        "sintpkt": 5.0,
        "is_sm_ips_ports": 0,
    }
    with pytest.raises((ValueError, TypeError)):
        prod_service.predict_single(non_numeric_flow)
