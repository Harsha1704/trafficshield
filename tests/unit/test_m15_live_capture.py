"""
TrafficShield Milestone 15: Live Capture Enablement & Operational Validation Tests
==================================================================================
Validates:
1. Native kernel driver inspection (Npcap/wpcap.dll detection on Windows).
2. Dynamic interface discovery across hardware adapters without hardcoded device names.
3. Driver guards and error handling when driver is absent or invalid interface is given.
4. HTTP API status, interface discovery, and live capture start/stop lifecycle.
5. Operational memory bounding: packet queues, flow LRU eviction, and circular event buffer.
6. Zero raw payload retention in packet envelopes and reconstructed flows.
7. Verification of frozen model artifact immutability.
8. Regression validation confirming offline PCAP replay pipeline remains 100% functional.
"""
from __future__ import annotations

import hashlib
import queue
import time
from pathlib import Path

import pytest

from app import create_app
from ingestion.capture.base import CaptureSourceType, PacketEnvelope
from ingestion.capture.live_source import (
    DriverNotFoundError,
    LiveCaptureSource,
    enumerate_network_interfaces,
    is_capture_driver_available,
)
from ingestion.flow.flow_builder import UnidirectionalFlowBuilder
from ml.production_service import (
    EXPECTED_DETECTOR_SHA256,
    EXPECTED_PREPROCESSOR_SHA256,
    ProductionInferenceService,
)
from streaming.inference_worker import StreamingInferenceWorker
from streaming.manager import RealTimeDetectionManager, WorkerState


class TestLiveCaptureDriverAndDiscovery:
    """Validate driver inspection, dynamic interface enumeration, and failure guards."""

    def test_truthful_driver_availability_on_windows_host(self) -> None:
        driver_ok, driver_msg = is_capture_driver_available()
        # When Npcap is installed on the host:
        assert driver_ok is True
        assert "Npcap/WinPcap" in driver_msg or "installed" in driver_msg

    def test_dynamic_interface_enumeration_structure(self) -> None:
        interfaces = enumerate_network_interfaces()
        assert len(interfaces) > 0, "Expected at least one network interface to be discovered"

        for iface in interfaces:
            assert "name" in iface
            assert "description" in iface
            assert "ipv4_addresses" in iface
            assert isinstance(iface["ipv4_addresses"], list)
            assert "is_up" in iface
            assert "is_loopback" in iface
            assert "driver_available" in iface
            assert iface["driver_available"] is True

    def test_live_source_raises_driver_not_found_when_driver_missing(self, monkeypatch) -> None:
        # Simulate missing driver
        monkeypatch.setattr(
            "ingestion.capture.live_source.is_capture_driver_available",
            lambda: (False, "Npcap/WinPcap driver not installed (wpcap.dll missing)."),
        )
        source = LiveCaptureSource(interface="Wi-Fi", packet_queue_size=100)
        assert source.source_type == CaptureSourceType.LIVE_CAPTURE
        assert not source.is_running

        with pytest.raises(DriverNotFoundError) as exc_info:
            source.start()
        assert "wpcap.dll missing" in str(exc_info.value) or "Npcap" in str(exc_info.value)

    def test_manager_rejects_live_capture_when_driver_missing(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "streaming.manager.is_capture_driver_available",
            lambda: (False, "Npcap/WinPcap driver not installed (wpcap.dll missing)."),
        )
        manager = RealTimeDetectionManager.get_instance()
        with pytest.raises(RuntimeError) as exc_info:
            manager.start_live_capture(interface="Wi-Fi")

        assert "Npcap" in str(exc_info.value) or "wpcap.dll" in str(exc_info.value)
        assert manager.state == WorkerState.FAILED
        assert manager.error_message is not None

        manager.stop()


class TestCaptureApiEndpoints:
    """Validate capture REST endpoints for interface enumeration, status, and live capture."""

    @pytest.fixture
    def client(self):
        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c

    def test_get_interfaces_endpoint(self, client) -> None:
        res = client.get("/api/v1/capture/interfaces")
        assert res.status_code == 200
        payload = res.get_json()
        assert payload["success"] is True
        data = payload["data"]
        assert data["driver_available"] is True
        assert "interfaces" in data
        assert len(data["interfaces"]) > 0

    def test_get_capture_status_endpoint(self, client) -> None:
        res = client.get("/api/v1/capture/status")
        assert res.status_code == 200
        payload = res.get_json()
        assert payload["success"] is True
        data = payload["data"]
        assert "worker_state" in data
        assert "capture_mode" in data
        assert data["driver_available"] is True

    def test_start_live_endpoint_missing_driver_error(self, client, monkeypatch) -> None:
        monkeypatch.setattr(
            "streaming.manager.is_capture_driver_available",
            lambda: (False, "Npcap/WinPcap driver not installed (wpcap.dll missing)."),
        )
        from app.database.models import User
        from app.utils.auth import generate_token

        with client.application.app_context():
            user = User.query.filter_by(username="analyst").first()
            if not user:
                user = User(username="analyst", role="analyst")
            token = generate_token(user)

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        res = client.post(
            "/api/v1/capture/start-live",
            json={"interface": "Wi-Fi"},
            headers=headers,
        )
        assert res.status_code == 400
        payload = res.get_json()
        assert payload["success"] is False
        assert payload["error"]["code"] == "DRIVER_OR_SESSION_ERROR"
        assert "Npcap" in payload["error"]["message"] or "wpcap.dll" in payload["error"]["message"]

    def test_start_and_stop_live_endpoint_with_driver(self, client) -> None:
        from app.database.models import User
        from app.utils.auth import generate_token

        with client.application.app_context():
            user = User.query.filter_by(username="analyst").first()
            if not user:
                user = User(username="analyst", role="analyst")
            token = generate_token(user)

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        # 1. Start live capture
        start_res = client.post(
            "/api/v1/capture/start-live",
            json={"interface": "Wi-Fi"},
            headers=headers,
        )
        assert start_res.status_code == 200
        start_payload = start_res.get_json()
        assert start_payload["success"] is True
        assert start_payload["data"]["worker_state"] in ("STARTING", "RUNNING")
        assert start_payload["data"]["capture_mode"] == "LIVE_CAPTURE"

        # 2. Wait 1 second to observe running state
        time.sleep(1.0)
        status_res = client.get("/api/v1/capture/status", headers=headers)
        assert status_res.status_code == 200
        status_payload = status_res.get_json()
        assert status_payload["data"]["capture_mode"] == "LIVE_CAPTURE"

        # 3. Stop live capture
        stop_res = client.post("/api/v1/capture/stop", headers=headers)
        assert stop_res.status_code == 200
        stop_payload = stop_res.get_json()
        assert stop_payload["success"] is True
        assert stop_payload["data"]["worker_state"] == "STOPPED"


class TestOperationalBoundsAndZeroPayload:
    """Validate bounded resource memory and strict zero payload retention."""

    def test_packet_envelope_retains_no_payload_bytes(self) -> None:
        env = PacketEnvelope(
            timestamp=100.0,
            ip_src="10.0.0.1",
            ip_dst="192.168.1.1",
            src_port=12345,
            dst_port=80,
            protocol="TCP",
            ttl=64,
            byte_length=1500,
            tcp_window=64240,
            tcp_flags="S",
        )
        assert not hasattr(env, "payload")
        assert not hasattr(env, "raw_bytes")
        assert env.byte_length == 1500
        assert env.protocol == "TCP"

    def test_flow_builder_memory_bounding_lru_eviction(self) -> None:
        builder = UnidirectionalFlowBuilder(max_active_flows=5, idle_timeout_seconds=100.0)
        # Create 10 distinct flows simultaneously within 0.1s
        for i in range(10):
            p = PacketEnvelope(
                timestamp=100.0 + (i * 0.01),
                ip_src="10.0.0.1",
                ip_dst=f"10.0.0.{i+2}",
                src_port=1000 + i,
                dst_port=80,
                protocol="TCP",
                ttl=64,
                byte_length=60,
            )
            builder.process_packet(p)

        assert len(builder.active_flows) <= 5
        metrics = builder.get_metrics()
        assert metrics["flows_evicted_overflow"] >= 5

    def test_streaming_worker_buffer_bounded(self) -> None:
        q: queue.Queue = queue.Queue()
        service = ProductionInferenceService(verify_checksums=True)
        worker = StreamingInferenceWorker(
            flow_queue=q,
            inference_service=service,
            recent_buffer_size=10,
        )

        for i in range(15):
            worker.recent_events.append({"event_id": f"evt-{i}", "score": 0.1})

        assert len(worker.recent_events) == 10
        assert worker.recent_events[-1]["event_id"] == "evt-14"


class TestArtifactIntegrityAndReplayRegression:
    """Verify bit-identical artifact preservation and PCAP replay operational integrity."""

    def test_frozen_artifacts_strictly_preserved(self) -> None:
        det_path = Path("artifacts/models/production_detector.joblib")
        prep_path = Path("artifacts/models/production_preprocessor.joblib")

        with open(det_path, "rb") as f:
            assert hashlib.sha256(f.read()).hexdigest() == EXPECTED_DETECTOR_SHA256
        with open(prep_path, "rb") as f:
            assert hashlib.sha256(f.read()).hexdigest() == EXPECTED_PREPROCESSOR_SHA256

    def test_pcap_replay_pipeline_remains_fully_functional(self) -> None:
        manager = RealTimeDetectionManager.get_instance()
        pcap_path = Path("data/captures/sample_traffic.pcap")
        assert pcap_path.exists(), "Sample traffic PCAP must exist"

        status = manager.start_pcap_replay(
            pcap_path=str(pcap_path),
            speed_multiplier=0.0,
        )
        assert status["worker_state"] in ("STARTING", "RUNNING")
        assert status["capture_mode"] == "PCAP_REPLAY"

        for _ in range(30):
            time.sleep(0.1)
            st = manager.get_status()
            if st["worker_state"] == "COMPLETED":
                break

        final_st = manager.get_status()
        assert final_st["packets_observed"] > 0
        assert final_st["flows_completed"] > 0
        assert final_st["flows_scored"] > 0
        assert final_st["model_integrity"]["checksum_verified"] is True

        manager.stop()
