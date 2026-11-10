"""
Milestone 15.2: Live-Capture Adapter & Pipeline Validation Tests
================================================================
Validates:
1. Npcap driver availability and 5 model/preprocessor artifact digests.
2. Unidirectional flow builder 13-feature reconstruction contract (TCP & UDP).
3. Strict directional isolation (forward vs reverse packets never merge).
4. Edge-case safety: single-packet flows (duration=0.0), RFC 3550 jitter, rate derivation.
5. Incompatible packets (missing/invalid STTL) rejected safely without crash.
6. Clean stop and queue drain lifecycle for capture sources.
7. End-to-end synthetic packet flow to hybrid ML inference and database alert persistence.
"""
from __future__ import annotations

import queue
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from app.database.models import SecurityAlert
from detection.artifacts import compute_sha256
from ingestion.capture.base import PacketEnvelope
from ingestion.capture.live_source import (
    is_capture_driver_available,
)
from ingestion.flow.flow_builder import UnidirectionalFlowBuilder
from ml.production_service import (
    EXPECTED_DETECTOR_SHA256,
    EXPECTED_IFOREST_SHA256,
    EXPECTED_PREPROCESSOR_SHA256,
    ProductionInferenceService,
)
from streaming.inference_worker import StreamingInferenceWorker


@pytest.fixture(scope="module")
def inference_service() -> ProductionInferenceService:
    return ProductionInferenceService(verify_checksums=True)


def test_driver_availability_and_artifact_hashes() -> None:
    """Verifies Npcap driver is active and all 5 model artifacts match baseline digests."""
    driver_ok, driver_msg = is_capture_driver_available()
    assert driver_ok is True
    assert "Npcap/WinPcap" in driver_msg

    files = {
        "artifacts/models/production_detector.joblib": EXPECTED_DETECTOR_SHA256,
        "artifacts/models/production_detector.json": "3553f1a47c1c2fd67b031cadb42400246997778f8dcf42026e2ebfb882ba73b1",
        "artifacts/models/production_preprocessor.joblib": EXPECTED_PREPROCESSOR_SHA256,
        "artifacts/models/production_iforest.joblib": EXPECTED_IFOREST_SHA256,
        "artifacts/models/production_iforest.json": "5daf8b0dab1c4c3a66e4cb2c38b10c406f6c1861572d27a08155c8541bf4cb94",
    }
    for rel_path, exp_hash in files.items():
        p = Path(rel_path)
        assert p.exists(), f"Artifact missing: {rel_path}"
        assert compute_sha256(p) == exp_hash, f"Hash mismatch for {rel_path}"


def test_unidirectional_tcp_udp_feature_construction(
    inference_service: ProductionInferenceService,
) -> None:
    """Verifies that TCP and UDP packet streams build valid 13-feature production vectors."""
    builder = UnidirectionalFlowBuilder(idle_timeout_seconds=2.0)
    base_ts = 1700000000.0

    # Feed 3 TCP packets
    for i in range(3):
        builder.process_packet(
            PacketEnvelope(
                timestamp=base_ts + (i * 0.1),
                ip_src="192.168.1.50",
                ip_dst="10.0.0.1",
                src_port=49200,
                dst_port=443,
                protocol="TCP",
                ttl=64,
                byte_length=1200,
                tcp_window=64240,
                tcp_flags="A",
            )
        )

    # Feed 2 UDP packets
    for i in range(2):
        builder.process_packet(
            PacketEnvelope(
                timestamp=base_ts + 0.5 + (i * 0.05),
                ip_src="192.168.1.50",
                ip_dst="8.8.8.8",
                src_port=53000,
                dst_port=53,
                protocol="UDP",
                ttl=128,
                byte_length=150,
                tcp_window=0,
                tcp_flags="",
            )
        )

    flushed = builder.flush()
    assert len(flushed) == 2

    tcp_flow = next(f for f in flushed if f["protocol"] == "TCP")
    udp_flow = next(f for f in flushed if f["protocol"] == "UDP")

    # TCP validation
    assert tcp_flow["fwd_packets"] == 3
    assert tcp_flow["fwd_bytes"] == 3600
    assert tcp_flow["sttl"] == 64
    assert tcp_flow["swin"] == 64240
    assert np.isclose(tcp_flow["duration_seconds"], 0.2, atol=1e-3)
    assert tcp_flow["packet_rate"] > 0.0
    assert tcp_flow["byte_rate"] > 0.0
    assert "dbytes" not in tcp_flow

    res_tcp = inference_service.predict_single(tcp_flow)
    assert "hybrid_classification" in res_tcp
    assert "supervised" in res_tcp
    assert "unsupervised" in res_tcp

    # UDP validation
    assert udp_flow["fwd_packets"] == 2
    assert udp_flow["fwd_bytes"] == 300
    assert udp_flow["sttl"] == 128
    assert udp_flow["swin"] == 0
    res_udp = inference_service.predict_single(udp_flow)
    assert "hybrid_classification" in res_udp


def test_bidirectional_traffic_strict_separation() -> None:
    """Verifies that reverse connection packets create an independent flow and never mix."""
    builder = UnidirectionalFlowBuilder(idle_timeout_seconds=5.0)
    base_ts = 1700000000.0

    # Forward: Client -> Server
    builder.process_packet(
        PacketEnvelope(
            timestamp=base_ts,
            ip_src="192.168.1.10",
            ip_dst="10.0.0.1",
            src_port=44444,
            dst_port=80,
            protocol="TCP",
            ttl=64,
            byte_length=1000,
            tcp_window=65535,
            tcp_flags="S",
        )
    )

    # Reverse: Server -> Client
    builder.process_packet(
        PacketEnvelope(
            timestamp=base_ts + 0.02,
            ip_src="10.0.0.1",
            ip_dst="192.168.1.10",
            src_port=80,
            dst_port=44444,
            protocol="TCP",
            ttl=56,
            byte_length=80,
            tcp_window=32768,
            tcp_flags="SA",
        )
    )

    flushed = builder.flush()
    assert len(flushed) == 2

    fwd = next(f for f in flushed if f["src_ip"] == "192.168.1.10")
    rev = next(f for f in flushed if f["src_ip"] == "10.0.0.1")

    assert fwd["flow_id"] == "192.168.1.10:44444->10.0.0.1:80/TCP"
    assert rev["flow_id"] == "10.0.0.1:80->192.168.1.10:44444/TCP"
    assert fwd["fwd_bytes"] == 1000
    assert rev["fwd_bytes"] == 80
    assert fwd["sttl"] == 64
    assert rev["sttl"] == 56


def test_single_packet_zero_duration_guard(
    inference_service: ProductionInferenceService,
) -> None:
    """Verifies single-packet flows (duration=0.0) safely calculate rates without NaN or zero division."""
    builder = UnidirectionalFlowBuilder(idle_timeout_seconds=1.0)
    builder.process_packet(
        PacketEnvelope(
            timestamp=1700000000.0,
            ip_src="192.168.1.100",
            ip_dst="1.1.1.1",
            src_port=55555,
            dst_port=53,
            protocol="UDP",
            ttl=64,
            byte_length=120,
            tcp_window=0,
            tcp_flags="",
        )
    )
    flushed = builder.flush()
    assert len(flushed) == 1
    flow = flushed[0]

    assert flow["duration_seconds"] == 0.0
    assert flow["sload"] == 0.0
    assert flow["packet_rate"] == 0.0
    assert flow["byte_rate"] == 0.0
    assert flow["bytes_per_packet"] == 120.0

    res = inference_service.predict_single(flow)
    assert not np.isnan(res["anomaly_score"])
    assert "hybrid_classification" in res


def test_incompatible_packet_and_missing_ttl_handling() -> None:
    """Verifies that flows with missing/invalid STTL are rejected as incompatible."""
    builder = UnidirectionalFlowBuilder(idle_timeout_seconds=1.0)
    builder.process_packet(
        PacketEnvelope(
            timestamp=1700000000.0,
            ip_src="192.168.1.200",
            ip_dst="10.0.0.5",
            src_port=50000,
            dst_port=8080,
            protocol="TCP",
            ttl=0,  # Invalid STTL
            byte_length=200,
            tcp_window=1000,
            tcp_flags="S",
        )
    )
    flushed = builder.flush()
    assert len(flushed) == 1
    flow = flushed[0]

    assert flow["is_compatible"] is False
    assert flow["compatibility_reason"] == "INVALID_OR_MISSING_STTL"


def test_streaming_worker_persists_hybrid_evidence(
    app: Any,
    inference_service: ProductionInferenceService,
) -> None:
    """Verifies that live capture alerts written by StreamingInferenceWorker unpack hybrid evidence."""
    flow_q: queue.Queue[dict[str, Any] | None] = queue.Queue()
    worker = StreamingInferenceWorker(
        flow_queue=flow_q,
        inference_service=inference_service,
        app=app,
        source_provenance="LIVE_CAPTURE",
        recent_buffer_size=50,
        decision_threshold=0.50,
    )
    worker.start()

    # Create anomalous flow
    anom_flow = {
        "flow_id": "test_live_alert_flow",
        "src_ip": "192.168.1.10",
        "dst_ip": "10.0.0.1",
        "src_port": 54321,
        "dst_port": 443,
        "protocol": "TCP",
        "duration_seconds": 0.001,
        "fwd_bytes": 1_500_000.0,
        "sttl": 254.0,
        "sload": 9_600_000_000.0,
        "fwd_packets": 1500.0,
        "swin": 255.0,
        "smeansz": 1000.0,
        "sjit": 0.0,
        "sintpkt": 0.001,
        "is_sm_ips_ports": 0.0,
        "packet_rate": 1_500_000.0,
        "byte_rate": 1_500_000_000.0,
        "bytes_per_packet": 1000.0,
        "is_compatible": True,
    }
    flow_q.put(anom_flow)

    time.sleep(0.3)
    worker.stop(drain_timeout=3.0)

    assert worker.flows_scored == 1
    assert worker.anomalies_detected == 1

    with app.app_context():
        alert = SecurityAlert.query.filter_by(source="LIVE_CAPTURE", is_anomaly=True).first()
        assert alert is not None
        d = alert.to_dict()
        assert "hybrid_classification" in d
        assert d["hybrid_classification"] in ("DUAL_CONFIRMED", "SUPERVISED_ONLY_ALERT", "UNSUPERVISED_NOVELTY")
        assert "supervised" in d
        assert "unsupervised" in d
