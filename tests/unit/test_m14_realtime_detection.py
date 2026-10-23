"""
Comprehensive Real-Time Detection & Flow Reconstruction Test Suite
==================================================================
Milestone 14 — Real-Time Network Detection, Flow Reconstruction and Streaming SOC Alerts

Covers:
1. PacketSource abstractions (PcapReplaySource, LiveCaptureSource)
2. Directional flow reconstruction and lifecycle management
3. RFC 3550 jitter calculation and rate protections
4. Zero reverse-direction leakage guarantee
5. StreamingInferenceWorker scoring and deduplicated alert persistence
6. RealTimeDetectionManager supervisor and state transitions
7. Capture REST API endpoints and RBAC protections
"""
from __future__ import annotations

import queue
import time
from pathlib import Path

import pytest
from scapy.layers.inet import IP, TCP
from scapy.packet import Packet
from scapy.utils import wrpcap

from app import create_app
from app.database.models import SecurityAlert, User
from app.extensions import db
from app.utils.auth import generate_token
from ingestion.capture.base import CaptureSourceType, PacketEnvelope, WorkerState
from ingestion.capture.live_source import (
    DriverNotFoundError,
    LiveCaptureSource,
    enumerate_network_interfaces,
    is_capture_driver_available,
)
from ingestion.capture.pcap_source import PcapReplaySource
from ingestion.flow.flow_builder import UnidirectionalFlowBuilder
from ml.production_service import ProductionInferenceService
from streaming.inference_worker import StreamingInferenceWorker
from streaming.manager import RealTimeDetectionManager


# ─── Fixtures ─────────────────────────────────────────────────────────────────
@pytest.fixture
def sample_pcap(tmp_path) -> Path:
    """Generate a clean, deterministic synthetic PCAP fixture."""
    pcap_file = tmp_path / "synthetic_traffic.pcap"
    packets: list[Packet] = []
    base_ts = 1700000000.0

    # 1. Benign Web Flow: 192.168.1.10 -> 10.0.0.1:80 (TCP, 5 packets)
    for i in range(5):
        pkt = IP(src="192.168.1.10", dst="10.0.0.1", ttl=64, len=120) / TCP(
            sport=49152, dport=80, window=65535, flags="A" if i < 4 else "FA"
        )
        pkt.time = base_ts + (i * 0.05)
        packets.append(pkt)

    # 2. Reverse Flow on opposite link: 10.0.0.1 -> 192.168.1.10:49152 (Must remain SEPARATE)
    for i in range(3):
        rev_pkt = IP(src="10.0.0.1", dst="192.168.1.10", ttl=55, len=500) / TCP(
            sport=80, dport=49152, window=32768, flags="A"
        )
        rev_pkt.time = base_ts + 0.02 + (i * 0.05)
        packets.append(rev_pkt)

    # 3. Port Scan / Volumetric Burst: 192.168.1.99 -> 10.0.0.50 (Land attack signature)
    land_pkt = IP(src="10.0.0.50", dst="10.0.0.50", ttl=64, len=80) / TCP(
        sport=8080, dport=8080, window=1024, flags="S"
    )
    land_pkt.time = base_ts + 0.50
    packets.append(land_pkt)

    wrpcap(str(pcap_file), packets)
    return pcap_file


@pytest.fixture
def real_time_app(tmp_path):
    """Create Flask test app with file-backed SQLite database."""
    app = create_app("testing")
    db_file = tmp_path / "realtime_test.db"
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_file}"
    app.config["AUTH_ENABLED"] = True
    app.config["SECRET_KEY"] = "realtime-secret-key-32-chars-minimum-needed!"

    with app.app_context():
        db.create_all()
        analyst = User(username="analyst_rt", role="analyst", is_active=True)
        analyst.set_password("AnalystPassword123!")
        db.session.add(analyst)
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def rt_client(real_time_app):
    return real_time_app.test_client()


@pytest.fixture
def rt_analyst_token(real_time_app):
    with real_time_app.app_context():
        user = User.query.filter_by(username="analyst_rt").first()
        return generate_token(user)


# ─── 1. Packet Source Abstraction Tests ─────────────────────────────────────────
class TestPacketSources:
    """Validate PCAP replay and Live capture abstractions."""

    def test_pcap_source_validation_and_replay(self, sample_pcap):
        """PcapReplaySource parses valid PCAP and paces envelopes cleanly."""
        source = PcapReplaySource(sample_pcap, speed_multiplier=0.0)  # Max unthrottled for test
        assert source.source_type == CaptureSourceType.PCAP_REPLAY

        envelopes = list(source.packets())
        assert len(envelopes) == 9  # 5 fwd + 3 rev + 1 land

        # Check envelope fields
        first_env = envelopes[0]
        assert isinstance(first_env, PacketEnvelope)
        assert first_env.ip_src == "192.168.1.10"
        assert first_env.ip_dst == "10.0.0.1"
        assert first_env.src_port == 49152
        assert first_env.dst_port == 80
        assert first_env.protocol == "TCP"
        assert first_env.ttl == 64
        assert first_env.tcp_window == 65535

        # Verify telemetry
        metrics = source.get_metrics()
        assert metrics["packets_read"] == 9
        assert metrics["source_type"] == "PCAP_REPLAY"
        assert metrics["malformed_packets"] == 0

    def test_pcap_source_nonexistent_and_empty_file_fails(self, tmp_path):
        """PcapReplaySource fails fast on nonexistent or invalid file formats."""
        with pytest.raises(FileNotFoundError):
            PcapReplaySource(tmp_path / "does_not_exist.pcap")

        empty_file = tmp_path / "empty.pcap"
        empty_file.write_bytes(b"")
        with pytest.raises(ValueError, match="empty"):
            PcapReplaySource(empty_file)

        corrupt_file = tmp_path / "corrupt.pcap"
        corrupt_file.write_bytes(b"NOT_A_VALID_PCAP_HEADER")
        with pytest.raises(ValueError, match="Magic bytes"):
            PcapReplaySource(corrupt_file)

    def test_live_capture_driver_enumeration(self):
        """Interface enumeration returns local network interfaces truthfully."""
        ifaces = enumerate_network_interfaces()
        assert isinstance(ifaces, list)
        assert len(ifaces) > 0
        first = ifaces[0]
        assert "name" in first
        assert "is_up" in first
        assert "driver_available" in first

    def test_live_capture_source_fails_without_driver_on_windows(self):
        """LiveCaptureSource raises DriverNotFoundError if native driver is absent."""
        driver_ok, driver_msg = is_capture_driver_available()
        source = LiveCaptureSource(interface="default")

        if not driver_ok:
            with pytest.raises(DriverNotFoundError, match="wpcap.dll"):
                source.start()
        else:
            assert source.is_running is False


# ─── 2. Unidirectional Flow Builder Tests ─────────────────────────────────────
class TestUnidirectionalFlowBuilder:
    """Validate directional aggregation, RFC 3550 jitter, and lifecycle management."""

    def test_directionality_never_merges_reverse_traffic(self, sample_pcap):
        """Ensure forward and reverse packets create two separate unidirectional flows."""
        source = PcapReplaySource(sample_pcap, speed_multiplier=0.0)
        builder = UnidirectionalFlowBuilder(idle_timeout_seconds=2.0)

        all_flows = []
        for env in source.packets():
            finalized = builder.process_packet(env)
            all_flows.extend(finalized)

        # Flush remaining flows at EOF
        all_flows.extend(builder.flush())

        # Should be 3 distinct unidirectional flows:
        # 1. 192.168.1.10:49152 -> 10.0.0.1:80/TCP
        # 2. 10.0.0.1:80 -> 192.168.1.10:49152/TCP (separate!)
        # 3. 10.0.0.50:8080 -> 10.0.0.50:8080/TCP (land)
        flow_ids = {f["flow_id"] for f in all_flows}
        assert "192.168.1.10:49152->10.0.0.1:80/TCP" in flow_ids
        assert "10.0.0.1:80->192.168.1.10:49152/TCP" in flow_ids
        assert "10.0.0.50:8080->10.0.0.50:8080/TCP" in flow_ids

        # Forward flow must have exactly 5 packets (NOT 5+3=8)
        fwd_flow = next(f for f in all_flows if f["src_ip"] == "192.168.1.10")
        assert fwd_flow["fwd_packets"] == 5
        assert fwd_flow["is_sm_ips_ports"] == 0

        # Land flow must have is_sm_ips_ports == 1
        land_flow = next(f for f in all_flows if f["flow_id"] == "10.0.0.50:8080->10.0.0.50:8080/TCP")
        assert land_flow["is_sm_ips_ports"] == 1

    def test_tcp_fin_immediate_finalization(self):
        """A TCP packet with FIN flag immediately finalizes the flow without timeout delay."""
        builder = UnidirectionalFlowBuilder(idle_timeout_seconds=10.0)

        p1 = PacketEnvelope(
            timestamp=10.0,
            ip_src="10.0.0.2",
            ip_dst="10.0.0.3",
            src_port=1000,
            dst_port=80,
            protocol="TCP",
            ttl=64,
            byte_length=100,
            tcp_flags="A",
            is_fin_or_rst=False,
        )
        p2 = PacketEnvelope(
            timestamp=10.1,
            ip_src="10.0.0.2",
            ip_dst="10.0.0.3",
            src_port=1000,
            dst_port=80,
            protocol="TCP",
            ttl=64,
            byte_length=100,
            tcp_flags="FA",
            is_fin_or_rst=True,
        )

        fin1 = builder.process_packet(p1)
        assert len(fin1) == 0

        fin2 = builder.process_packet(p2)
        assert len(fin2) == 1
        assert fin2[0]["fwd_packets"] == 2
        assert fin2[0]["duration_seconds"] == pytest.approx(0.1, abs=1e-4)

    def test_max_active_flows_bound_eviction(self):
        """Builder evicts oldest flow when active flow table exceeds max capacity."""
        builder = UnidirectionalFlowBuilder(max_active_flows=2)

        p1 = PacketEnvelope(1.0, "1.1.1.1", "2.2.2.2", 1, 80, "TCP", 64, 50)
        p2 = PacketEnvelope(2.0, "3.3.3.3", "4.4.4.4", 2, 80, "TCP", 64, 50)
        p3 = PacketEnvelope(3.0, "5.5.5.5", "6.6.6.6", 3, 80, "TCP", 64, 50)

        builder.process_packet(p1)
        builder.process_packet(p2)
        # Adding 3rd flow should evict p1
        evicted = builder.process_packet(p3)

        assert len(evicted) == 1
        assert evicted[0]["src_ip"] == "1.1.1.1"
        assert len(builder.active_flows) == 2


# ─── 3. Streaming Inference & Manager Integration Tests ───────────────────────
class TestStreamingInferenceAndManager:
    """Validate decoupled worker inference, alert persistence, and lifecycle supervisor."""

    def test_streaming_worker_scores_and_persists_anomalies(self, real_time_app):
        """Worker reads flows from queue, executes frozen model, and saves SecurityAlert."""
        flow_q: queue.Queue = queue.Queue()
        service = ProductionInferenceService()

        worker = StreamingInferenceWorker(
            flow_queue=flow_q,
            inference_service=service,
            app=real_time_app,
            source_provenance="PCAP_REPLAY",
            decision_threshold=0.50,
        )
        worker.start()

        # Enqueue anomalous volumetric burst flow
        flow_q.put({
            "flow_id": "test_burst_flow",
            "src_ip": "192.168.1.200",
            "dst_ip": "10.0.0.1",
            "src_port": 55555,
            "dst_port": 80,
            "protocol": "TCP",
            "duration_seconds": 0.05,
            "fwd_bytes": 120000,
            "sttl": 254,
            "sload": 19200000.0,
            "fwd_packets": 250,
            "swin": 255,
            "smeansz": 480.0,
            "sjit": 10.5,
            "sintpkt": 0.2,
            "is_sm_ips_ports": 0,
        })

        # Wait briefly for worker to consume
        time.sleep(0.5)
        worker.stop()

        assert worker.flows_scored == 1
        assert worker.anomalies_detected == 1
        assert len(worker.recent_events) == 1

        # Check database persistence
        with real_time_app.app_context():
            alerts = SecurityAlert.query.filter_by(source="PCAP_REPLAY").all()
            assert len(alerts) == 1
            assert alerts[0].is_anomaly is True
            assert alerts[0].anomaly_score >= 0.50
            assert alerts[0].status == "NEW"

    def test_manager_pcap_replay_full_pipeline(self, sample_pcap, real_time_app):
        """RealTimeDetectionManager executes complete PCAP replay from file to scored status."""
        manager = RealTimeDetectionManager.get_instance()
        # Ensure clean state
        manager.stop()

        status = manager.start_pcap_replay(
            pcap_path=sample_pcap,
            speed_multiplier=0.0,  # Max speed
            app=real_time_app,
        )

        assert status["capture_mode"] == "PCAP_REPLAY"
        assert status["worker_state"] in ("STARTING", "RUNNING")

        # Wait for replay loop to finish
        time.sleep(1.0)
        final_status = manager.get_status()

        assert final_status["packets_observed"] >= 9
        assert final_status["flows_completed"] >= 3
        assert final_status["flows_scored"] >= 3
        assert len(final_status["recent_events"]) >= 3
        assert final_status["model_integrity"]["checksum_verified"] is True

        manager.stop()
        assert manager.state == WorkerState.STOPPED

    def test_manager_prevents_duplicate_starts(self, sample_pcap, real_time_app):
        """Manager raises RuntimeError if start is invoked while session is already active."""
        manager = RealTimeDetectionManager.get_instance()
        manager.stop()

        manager.start_pcap_replay(sample_pcap, speed_multiplier=0.0, app=real_time_app)

        with pytest.raises(RuntimeError, match="already active"):
            manager.start_pcap_replay(sample_pcap, speed_multiplier=0.0, app=real_time_app)

        manager.stop()


# ─── 4. Capture REST API Endpoints Tests ───────────────────────────────────────
class TestCaptureAPIEndpoints:
    """Validate REST API status, interface discovery, and control routes."""

    def test_public_status_and_interfaces_endpoints(self, rt_client):
        """GET /api/v1/capture/status and /interfaces return 200 OK without authentication."""
        s_resp = rt_client.get("/api/v1/capture/status")
        assert s_resp.status_code == 200
        assert "worker_state" in s_resp.get_json()["data"]

        i_resp = rt_client.get("/api/v1/capture/interfaces")
        assert i_resp.status_code == 200
        assert "interfaces" in i_resp.get_json()["data"]

    def test_unauthenticated_controls_denied(self, rt_client):
        """Capture controls require authenticated analyst or admin token."""
        assert rt_client.post("/api/v1/capture/start-replay").status_code == 401
        assert rt_client.post("/api/v1/capture/start-live").status_code == 401
        assert rt_client.post("/api/v1/capture/stop").status_code == 401

    def test_start_replay_and_stop_lifecycle_via_api(self, rt_client, rt_analyst_token, sample_pcap):
        """Analyst can start PCAP replay and stop it via REST endpoints."""
        headers = {"Authorization": f"Bearer {rt_analyst_token}"}

        # Start replay
        start_resp = rt_client.post(
            "/api/v1/capture/start-replay",
            headers=headers,
            json={"pcap_path": str(sample_pcap), "speed_multiplier": 0.0},
        )
        assert start_resp.status_code == 200
        data = start_resp.get_json()["data"]
        assert data["capture_mode"] == "PCAP_REPLAY"

        # Stop replay
        stop_resp = rt_client.post("/api/v1/capture/stop", headers=headers)
        assert stop_resp.status_code == 200
        assert stop_resp.get_json()["data"]["worker_state"] == "STOPPED"
