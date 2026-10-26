"""
Unit & Regression Tests for Offline Detection Validation & Accounting Invariants
================================================================================
Validates:
1. Forensic flow scoring and exact score distributions on `sample_traffic.pcap`.
2. True positive anomaly detection and alert persistence on volumetric burst flows.
3. Exact conservation of accounting invariants across ingestion, worker, and database.
"""
from __future__ import annotations

import queue
import time
from pathlib import Path

import pytest

from app import create_app
from app.database.models import SecurityAlert, User
from app.extensions import db
from ingestion.capture.pcap_source import PcapReplaySource
from ingestion.flow.flow_builder import UnidirectionalFlowBuilder
from ml.production_service import ProductionInferenceService
from streaming.inference_worker import StreamingInferenceWorker
from streaming.manager import RealTimeDetectionManager


@pytest.fixture
def test_app(tmp_path):
    """Create Flask test app with file-backed SQLite database."""
    app = create_app("testing")
    db_file = tmp_path / "det_val_test.db"
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_file}"
    app.config["AUTH_ENABLED"] = True
    app.config["SECRET_KEY"] = "test-secret-key-for-detection-validation-32b"

    with app.app_context():
        db.create_all()
        analyst = User(username="analyst_dv", role="analyst", is_active=True)
        analyst.set_password("AnalystPassword123!")
        db.session.add(analyst)
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


class TestSampleTrafficPcapValidation:
    """Verify exact behavior of the sample_traffic.pcap reference fixture."""

    def test_sample_traffic_packet_and_flow_accounting(self):
        pcap_path = Path("data/captures/sample_traffic.pcap")
        assert pcap_path.exists(), "sample_traffic.pcap must exist"

        source = PcapReplaySource(pcap_path, speed_multiplier=0.0)
        builder = UnidirectionalFlowBuilder(idle_timeout_seconds=2.0)
        svc = ProductionInferenceService()

        flows = []
        packet_count = 0
        for pkt in source.packets():
            packet_count += 1
            flushed = builder.process_packet(pkt)
            flows.extend(flushed)

        flows.extend(builder.flush())

        assert packet_count == 29
        assert len(flows) == 24

        scores = []
        for flow in flows:
            pred = svc.predict_single(flow)
            scores.append(pred["anomaly_score"])

        # Score distribution assertions
        assert min(scores) == pytest.approx(0.127333, abs=1e-5)
        assert max(scores) == pytest.approx(0.368135, abs=1e-5)
        # All flows must score strictly below the 0.50 decision threshold
        assert all(s < 0.50 for s in scores)
        assert sum(1 for s in scores if s >= 0.50) == 0

        # Flow 1 (TLS stream, 6 packets) has highest score
        tls_flow = next(f for f in flows if f["src_ip"] == "192.168.1.25" and f["dst_port"] == 443)
        assert tls_flow["fwd_packets"] == 6
        assert tls_flow["fwd_bytes"] == 240
        tls_pred = svc.predict_single(tls_flow)
        assert tls_pred["anomaly_score"] == pytest.approx(0.368135, abs=1e-5)
        assert tls_pred["risk_level"] == "LOW"
        assert tls_pred["is_anomaly"] is False

        # Flow with LAND probe packet correctly has is_sm_ips_ports == 1
        land_flow = next(f for f in flows if f["src_ip"] == "192.168.1.50" and f["dst_ip"] == "192.168.1.50")
        assert land_flow["is_sm_ips_ports"] == 1
        land_pred = svc.predict_single(land_flow)
        assert land_pred["anomaly_score"] == pytest.approx(0.127333, abs=1e-5)
        assert land_pred["is_anomaly"] is False


class TestAnomalyDetectionAndAccountingInvariants:
    """Verify anomaly triggering, alert persistence, and flow accounting invariants."""

    def test_volumetric_burst_anomaly_detection_and_persistence(self, test_app):
        flow_q: queue.Queue = queue.Queue()
        service = ProductionInferenceService()

        worker = StreamingInferenceWorker(
            flow_queue=flow_q,
            inference_service=service,
            app=test_app,
            source_provenance="PCAP_REPLAY",
            decision_threshold=0.50,
        )
        worker.start()

        # Enqueue high-sload volumetric burst
        anom_flow = {
            "flow_id": "flow-anomaly-volumetric-01",
            "src_ip": "10.99.99.1",
            "dst_ip": "192.168.1.100",
            "src_port": 44444,
            "dst_port": 80,
            "protocol": "TCP",
            "duration_seconds": 1.0,
            "fwd_bytes": 50000000,
            "sttl": 64,
            "sload": 400000000.0,
            "fwd_packets": 35000,
            "swin": 65535,
            "smeansz": 1428.0,
            "sjit": 0.5,
            "sintpkt": 0.00003,
            "is_sm_ips_ports": 0,
        }

        # Enqueue benign flow
        benign_flow = {
            "flow_id": "flow-benign-dns-01",
            "src_ip": "192.168.1.15",
            "dst_ip": "8.8.8.8",
            "src_port": 53530,
            "dst_port": 53,
            "protocol": "UDP",
            "duration_seconds": 0.0,
            "fwd_bytes": 34,
            "sttl": 64,
            "sload": 0.0,
            "fwd_packets": 1,
            "swin": 0,
            "smeansz": 34.0,
            "sjit": 0.0,
            "sintpkt": 0.0,
            "is_sm_ips_ports": 0,
        }

        flow_q.put(anom_flow)
        flow_q.put(benign_flow)

        # Allow worker to process
        time.sleep(0.5)
        worker.stop()

        # Verification
        assert worker.flows_scored == 2
        assert worker.anomalies_detected == 1
        assert worker.alerts_persisted == 1
        assert worker.alerts_deduplicated == 0
        assert worker.persistence_failures == 0
        assert worker.unprocessed_flows == 0

        # Accounting invariants
        assert worker.anomalies_detected == (
            worker.alerts_persisted
            + worker.persistence_failures
            + worker.alerts_deduplicated
            + worker.alerts_unpersisted_no_app
        )

        with test_app.app_context():
            alerts = SecurityAlert.query.all()
            assert len(alerts) == 1
            alert = alerts[0]
            assert alert.is_anomaly is True
            assert alert.anomaly_score >= 0.85  # CRITICAL risk
            assert alert.source == "PCAP_REPLAY"
            assert alert.src_port == 44444
            assert alert.dst_port == 80

    def test_manager_full_replay_accounting_invariants(self, test_app):
        manager = RealTimeDetectionManager.get_instance()
        manager.stop()

        pcap_path = Path("data/captures/sample_traffic.pcap")
        manager.start_pcap_replay(pcap_path=pcap_path, speed_multiplier=0.0, app=test_app)

        for _ in range(30):
            time.sleep(0.1)
            st = manager.get_status()
            if st["worker_state"] == "COMPLETED":
                break

        manager.stop()
        final_st = manager.get_status()

        # Invariant checks
        flows_completed = final_st["flows_completed"]
        flows_queued = final_st["flows_queued"]
        flows_scored = final_st["flows_scored"]
        anomalies_detected = final_st["anomalies_detected"]
        alerts_persisted = final_st["alerts_persisted"]
        unprocessed = final_st["unprocessed_flows"]

        assert flows_completed == 24
        assert flows_queued == 24
        assert flows_scored == 24
        assert unprocessed == 0
        assert anomalies_detected == 0
        assert alerts_persisted == 0

        # Flow conservation
        assert flows_completed == flows_queued + final_st.get("flows_queue_dropped", 0)
        assert flows_queued == (
            flows_scored
            + final_st.get("incompatible_flows_rejected", 0)
            + final_st.get("validation_errors", 0)
            + final_st.get("inference_failures", 0)
            + unprocessed
        )
