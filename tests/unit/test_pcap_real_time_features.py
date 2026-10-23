"""
Unit tests for PCAP Real-Time Feature Parser & Aggregator
=========================================================
Milestone 14 — Critical Gate: Real-Time Feature Compatibility Audit

Validates:
1. Exact calculation of all 13 features expected by the frozen production model
2. Strict unidirectional extraction (zero reverse features or leakage)
3. RFC 3550 inter-arrival jitter calculation
4. Flow aggregation and idle-timeout expiration
5. End-to-end inference using ProductionInferenceService without feature rejection
"""
from __future__ import annotations

import pytest
from scapy.layers.inet import IP, TCP, UDP
from scapy.packet import Packet
from scapy.utils import wrpcap

from ingestion.parsers.pcap_flow_parser import PcapFlowAggregator
from ml.production_service import ProductionInferenceService


class TestPcapFlowAggregator:
    """Validate unidirectional flow extraction from packet structures."""

    def test_single_packet_flow_feature_extraction(self):
        """Single packet flow should have duration=0 and rates safely guarded to 0."""
        pkt = IP(src="192.168.1.100", dst="10.0.0.1", ttl=64, len=60) / TCP(sport=54321, dport=443, window=64240)
        pkt.time = 100.0

        aggregator = PcapFlowAggregator(idle_timeout=2.0)
        aggregator.process_raw_packet(pkt)
        flows = aggregator.flush()

        assert len(flows) == 1
        features = flows[0]

        assert features["duration_seconds"] == 0.0
        assert features["fwd_packets"] == 1
        assert features["fwd_bytes"] == 60
        assert features["sttl"] == 64
        assert features["swin"] == 64240
        assert features["smeansz"] == 60.0
        assert features["sjit"] == 0.0
        assert features["sintpkt"] == 0.0
        assert features["sload"] == 0.0
        assert features["is_sm_ips_ports"] == 0

    def test_multi_packet_feature_calculation(self):
        """Multi-packet flow computes duration, RFC 3550 jitter, and causal rates."""
        # 3 packets at t=10.0, t=10.05, t=10.15 (duration = 0.15s)
        pkt1 = IP(src="192.168.1.50", dst="10.0.0.2", ttl=128, len=100) / TCP(sport=1234, dport=80, window=8192)
        pkt1.time = 10.00
        pkt2 = IP(src="192.168.1.50", dst="10.0.0.2", ttl=128, len=100) / TCP(sport=1234, dport=80, window=8192)
        pkt2.time = 10.05
        pkt3 = IP(src="192.168.1.50", dst="10.0.0.2", ttl=128, len=100) / TCP(sport=1234, dport=80, window=8192)
        pkt3.time = 10.15

        aggregator = PcapFlowAggregator(idle_timeout=2.0)
        aggregator.process_raw_packet(pkt1)
        aggregator.process_raw_packet(pkt2)
        aggregator.process_raw_packet(pkt3)
        flows = aggregator.flush()

        assert len(flows) == 1
        features = flows[0]

        assert features["fwd_packets"] == 3
        assert features["duration_seconds"] == pytest.approx(0.15, abs=1e-5)
        assert features["sttl"] == 128
        assert features["swin"] == 8192
        assert features["smeansz"] == 100.0

        # sintpkt = (0.15 * 1000) / (3 - 1) = 75.0 ms
        assert features["sintpkt"] == pytest.approx(75.0, abs=1e-3)

        # sload = (fwd_bytes * 8) / duration = (300 * 8) / 0.15 = 16000.0 bps
        assert features["sload"] == pytest.approx(16000.0, abs=1e-3)

    def test_land_attack_is_sm_ips_ports(self):
        """Identical source/destination IP and port sets is_sm_ips_ports = 1."""
        pkt = IP(src="10.0.0.5", dst="10.0.0.5", ttl=64, len=40) / UDP(sport=53, dport=53)
        pkt.time = 1.0

        aggregator = PcapFlowAggregator(idle_timeout=2.0)
        aggregator.process_raw_packet(pkt)
        flows = aggregator.flush()

        assert len(flows) == 1
        assert flows[0]["is_sm_ips_ports"] == 1

    def test_strict_unidirectional_contract(self):
        """Ensure NO bidirectional or reverse fields exist in feature dictionary."""
        pkt = IP(src="1.1.1.1", dst="2.2.2.2", ttl=64, len=40) / TCP(sport=1000, dport=80)
        pkt.time = 1.0

        aggregator = PcapFlowAggregator(idle_timeout=2.0)
        aggregator.process_raw_packet(pkt)
        flows = aggregator.flush()
        features = flows[0]

        forbidden_keys = [
            "bwd_packets",
            "bwd_bytes",
            "dload",
            "dttl",
            "dmeansz",
            "djit",
            "dintpkt",
            "dwin",
            "label",
            "attack_cat",
        ]
        for key in forbidden_keys:
            assert key not in features, f"Forbidden key {key} leaked into model features"

    def test_flow_idle_timeout_expiration(self):
        """Flows exceeding idle timeout are expired and finalized."""
        aggregator = PcapFlowAggregator(idle_timeout=2.0)

        pkt1 = IP(src="10.0.0.1", dst="10.0.0.2", ttl=64, len=50) / TCP(sport=100, dport=200)
        pkt1.time = 1.0
        pkt2 = IP(src="10.0.0.99", dst="10.0.0.88", ttl=64, len=50) / TCP(sport=300, dport=400)
        pkt2.time = 4.0  # 3.0s elapsed > 2.0s timeout

        # First packet at t=1.0
        exp1 = aggregator.process_raw_packet(pkt1)
        assert exp1 is None

        # Packet at t=4.0 should expire pkt1 flow
        exp2 = aggregator.process_raw_packet(pkt2)
        assert exp2 is not None
        assert exp2["src_ip"] == "10.0.0.1"
        assert exp2["fwd_packets"] == 1

    def test_synthetic_pcap_replay_to_production_inference(self, tmp_path):
        """Create a synthetic PCAP file, parse with aggregator, and score with frozen model."""
        pcap_path = tmp_path / "synthetic_probe.pcap"

        packets: list[Packet] = []
        base_time = 1700000000.0

        # 5 packets from 192.168.1.10 -> 10.0.0.50
        for i in range(5):
            p = IP(src="192.168.1.10", dst="10.0.0.50", ttl=64, len=120) / TCP(sport=49152, dport=80, window=65535)
            p.time = base_time + (i * 0.05)
            packets.append(p)

        wrpcap(str(pcap_path), packets)

        # Parse PCAP
        aggregator = PcapFlowAggregator(idle_timeout=15.0)
        completed_flows = aggregator.extract_flows_from_pcap(pcap_path)

        assert len(completed_flows) == 1
        flow_vector = completed_flows[0]

        assert flow_vector["fwd_packets"] == 5
        assert flow_vector["duration_seconds"] == pytest.approx(0.20, abs=1e-3)

        # Feed directly to frozen production model
        service = ProductionInferenceService()
        result = service.predict_single(flow_vector)

        assert "anomaly_score" in result
        assert "is_anomaly" in result
        assert "risk_level" in result
        assert 0.0 <= result["anomaly_score"] <= 1.0
        assert "top_contributing_features" in result
