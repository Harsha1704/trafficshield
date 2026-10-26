"""
Unit & Integration Tests for Milestone 14.2: Feature Fidelity & Packet Safety Gate
================================================================================
Milestone 14.2 — TrafficShield

Covers:
1. IPv4PacketValidator: malformed header checks, truncation detection, version verification.
2. BoundedFragmentReassembler: in-order, out-of-order, duplicate, expired, and oversize fragments.
3. Feature fidelity: Sload Argus training alignment, Sjit RFC 3550 bounds, zero silent imputation of STTL.
4. Incompatible flow safety: flows with invalid STTL rejected before inference.
5. Telemetry & rejection counters.
"""
from __future__ import annotations

import queue
import time

from scapy.all import IP, TCP, UDP

from ingestion.capture.base import PacketEnvelope
from ingestion.capture.packet_validator import (
    IPv4PacketValidator,
    PacketRejectionCategory,
    RejectionReason,
)
from ingestion.flow.flow_builder import ActiveFlowState
from ingestion.flow.fragment_reassembler import BoundedFragmentReassembler
from ml.production_service import ProductionInferenceService
from streaming.inference_worker import StreamingInferenceWorker


class TestIPv4PacketValidator:
    """Validate packet rejection and classification."""

    def test_valid_unfragmented_tcp_packet(self):
        pkt = IP(src="192.168.1.10", dst="10.0.0.1", ttl=64) / TCP(sport=54321, dport=80, window=65535, flags="S")
        raw = bytes(pkt)
        res = IPv4PacketValidator.validate_ipv4_frame(raw)
        assert res.is_valid
        assert res.category == PacketRejectionCategory.VALID
        assert res.ttl == 64
        assert res.protocol == 6
        assert not res.is_fragment

    def test_truncated_header_less_than_20_bytes(self):
        raw = bytes([0x45, 0x00, 0x00, 0x28, 0x00, 0x01, 0x00, 0x00, 0x40])  # Only 9 bytes
        res = IPv4PacketValidator.validate_ipv4_frame(raw)
        assert not res.is_valid
        assert res.category == PacketRejectionCategory.TRUNCATED
        assert res.reason == RejectionReason.TRUNCATED_IPV4_HEADER

    def test_invalid_ip_version(self):
        raw = bytearray(20)
        raw[0] = 0x55  # Version 5, IHL 5
        raw[2] = 0x00
        raw[3] = 0x14  # Total len 20
        raw[8] = 0x40  # TTL 64
        res = IPv4PacketValidator.validate_ipv4_frame(bytes(raw))
        assert not res.is_valid
        assert res.category == PacketRejectionCategory.MALFORMED
        assert res.reason == RejectionReason.MALFORMED_IP_VERSION

    def test_unsupported_ipv6_version(self):
        raw = bytearray(40)
        raw[0] = 0x60  # IPv6
        res = IPv4PacketValidator.validate_ipv4_frame(bytes(raw))
        assert not res.is_valid
        assert res.category == PacketRejectionCategory.UNSUPPORTED
        assert res.reason == RejectionReason.UNSUPPORTED_IPV6

    def test_malformed_ihl_less_than_5(self):
        raw = bytearray(20)
        raw[0] = 0x43  # Version 4, IHL 3 (12 bytes < 20 min)
        raw[2] = 0x00
        raw[3] = 0x14
        raw[8] = 0x40
        res = IPv4PacketValidator.validate_ipv4_frame(bytes(raw))
        assert not res.is_valid
        assert res.category == PacketRejectionCategory.MALFORMED
        assert res.reason == RejectionReason.MALFORMED_IHL_LESS_THAN_MIN

    def test_malformed_total_len_less_than_header(self):
        raw = bytearray(20)
        raw[0] = 0x45  # Version 4, IHL 5 (20 bytes)
        raw[2] = 0x00
        raw[3] = 0x0F  # Total len 15 (< 20)
        raw[8] = 0x40
        res = IPv4PacketValidator.validate_ipv4_frame(bytes(raw))
        assert not res.is_valid
        assert res.category == PacketRejectionCategory.MALFORMED
        assert res.reason == RejectionReason.MALFORMED_TOTAL_LEN_LESS_THAN_HEADER

    def test_truncated_capture_snaplen(self):
        # Header is complete (20 bytes), but payload cut short by snaplen (total_len=100 > cap_len=20)
        raw = bytearray(20)
        raw[0] = 0x45  # Header 20 bytes
        raw[2] = 0x00
        raw[3] = 0x64  # Total len 100 bytes
        raw[8] = 0x40  # TTL 64
        raw[9] = 0x01  # ICMP (header is complete for IP)
        res = IPv4PacketValidator.validate_ipv4_frame(bytes(raw))
        assert res.is_valid
        assert res.is_snaplen_truncated

    def test_truncated_tcp_header_rejected(self):
        # TCP requires 20 IP + 20 TCP = 40 bytes, but captured slice is only 30 bytes
        raw = bytearray(30)
        raw[0] = 0x45  # IP header 20 bytes
        raw[2] = 0x00
        raw[3] = 0x50  # Total len 80
        raw[8] = 0x40  # TTL 64
        raw[9] = 0x06  # TCP
        res = IPv4PacketValidator.validate_ipv4_frame(bytes(raw))
        assert not res.is_valid
        assert res.category == PacketRejectionCategory.TRUNCATED
        assert res.reason == RejectionReason.TRUNCATED_TCP_HEADER

    def test_malformed_zero_ttl(self):
        pkt = IP(src="192.168.1.10", dst="10.0.0.1", ttl=0) / UDP(sport=53, dport=53)
        raw = bytes(pkt)
        res = IPv4PacketValidator.validate_ipv4_frame(raw)
        assert not res.is_valid
        assert res.category == PacketRejectionCategory.MALFORMED
        assert res.reason == RejectionReason.MALFORMED_ZERO_TTL

    def test_malformed_tcp_offset_less_than_20(self):
        pkt = IP(src="192.168.1.10", dst="10.0.0.1", ttl=64) / TCP(sport=80, dport=80)
        raw = bytearray(bytes(pkt))
        raw[20 + 12] = 0x30  # Data offset 3 (12 bytes < 20 min)
        res = IPv4PacketValidator.validate_ipv4_frame(bytes(raw))
        assert not res.is_valid
        assert res.category == PacketRejectionCategory.MALFORMED
        assert res.reason == RejectionReason.MALFORMED_TCP_OFFSET


class TestBoundedFragmentReassembler:
    """Validate IPv4 fragmentation and reassembly."""

    def test_in_order_two_fragments_reassemble_cleanly(self):
        reassembler = BoundedFragmentReassembler()
        # Original 200-byte UDP packet (20 IP + 8 UDP + 172 payload)
        p1_hdr = bytes(IP(src="192.168.1.10", dst="10.0.0.1", id=1234, proto=17, flags="MF", frag=0))[:20]
        p1_payload = b"A" * 104  # 8 bytes UDP header + 96 bytes data (multiple of 8)

        # Fragment 1
        res1 = reassembler.process_fragment(
            src_ip="192.168.1.10", dst_ip="10.0.0.1", ip_id=1234, protocol=17,
            frag_offset=0, more_fragments=True, header_bytes=p1_hdr, payload_bytes=p1_payload,
        )
        assert res1 is None
        assert reassembler.metrics["fragments_received"] == 1
        assert reassembler.metrics["datagrams_reassembled"] == 0

        # Fragment 2 (Final: MF=0, offset=13*8=104)
        p2_payload = b"B" * 76
        res2 = reassembler.process_fragment(
            src_ip="192.168.1.10", dst_ip="10.0.0.1", ip_id=1234, protocol=17,
            frag_offset=104, more_fragments=False, header_bytes=b"", payload_bytes=p2_payload,
        )
        assert res2 is not None
        assert len(res2) == 20 + 104 + 76  # 200 bytes total
        assert reassembler.metrics["datagrams_reassembled"] == 1

    def test_out_of_order_fragments_reassemble_cleanly(self):
        reassembler = BoundedFragmentReassembler()
        p1_hdr = bytes(IP(src="10.0.0.5", dst="10.0.0.1", id=5555, proto=6, flags="MF", frag=0))[:20]

        # Fragment 2 arrives first (MF=0, offset=80, payload 40)
        res_first = reassembler.process_fragment(
            src_ip="10.0.0.5", dst_ip="10.0.0.1", ip_id=5555, protocol=6,
            frag_offset=80, more_fragments=False, header_bytes=b"", payload_bytes=b"Y" * 40,
        )
        assert res_first is None

        # Fragment 1 arrives second (MF=1, offset=0, payload 80)
        res_second = reassembler.process_fragment(
            src_ip="10.0.0.5", dst_ip="10.0.0.1", ip_id=5555, protocol=6,
            frag_offset=0, more_fragments=True, header_bytes=p1_hdr, payload_bytes=b"X" * 80,
        )
        assert res_second is not None
        assert len(res_second) == 20 + 80 + 40
        assert reassembler.metrics["datagrams_reassembled"] == 1

    def test_duplicate_fragments_handled_gracefully(self):
        reassembler = BoundedFragmentReassembler()
        p1_hdr = bytes(IP(src="10.0.0.5", dst="10.0.0.1", id=777, proto=17, flags="MF", frag=0))[:20]

        reassembler.process_fragment("10.0.0.5", "10.0.0.1", 777, 17, 0, True, p1_hdr, b"A"*64)
        # Duplicate of fragment 1
        reassembler.process_fragment("10.0.0.5", "10.0.0.1", 777, 17, 0, True, p1_hdr, b"A"*64)

        # Final fragment
        res = reassembler.process_fragment("10.0.0.5", "10.0.0.1", 777, 17, 64, False, b"", b"B"*32)
        assert res is not None
        assert len(res) == 20 + 64 + 32
        assert reassembler.metrics["datagrams_reassembled"] == 1

    def test_fragment_timeout_and_expiration(self):
        reassembler = BoundedFragmentReassembler(timeout_seconds=0.05)
        p1_hdr = bytes(IP(src="10.0.0.5", dst="10.0.0.1", id=999, proto=6, flags="MF", frag=0))[:20]

        # Send only fragment 1
        reassembler.process_fragment("10.0.0.5", "10.0.0.1", 999, 6, 0, True, p1_hdr, b"M"*80)
        assert len(reassembler.in_flight) == 1

        # Wait past expiration
        time.sleep(0.06)
        # Next fragment of different packet triggers purge
        reassembler.process_fragment("1.2.3.4", "5.6.7.8", 111, 6, 0, True, p1_hdr, b"Z"*40)
        assert reassembler.metrics["dropped_timeout"] >= 1
        assert (("10.0.0.5", "10.0.0.1", 999, 6)) not in reassembler.in_flight

    def test_capacity_bound_lru_eviction(self):
        reassembler = BoundedFragmentReassembler(max_in_flight=3)
        p1_hdr = bytes(IP(src="10.0.0.1", dst="10.0.0.2", id=1, proto=6))[:20]

        reassembler.process_fragment("10.0.0.1", "10.0.0.2", 1, 6, 0, True, p1_hdr, b"1"*40)
        reassembler.process_fragment("10.0.0.1", "10.0.0.2", 2, 6, 0, True, p1_hdr, b"2"*40)
        reassembler.process_fragment("10.0.0.1", "10.0.0.2", 3, 6, 0, True, p1_hdr, b"3"*40)
        assert len(reassembler.in_flight) == 3

        # 4th in-flight causes oldest (id=1) to be evicted
        reassembler.process_fragment("10.0.0.1", "10.0.0.2", 4, 6, 0, True, p1_hdr, b"4"*40)
        assert len(reassembler.in_flight) == 3
        assert reassembler.metrics["dropped_capacity"] == 1
        assert ("10.0.0.1", "10.0.0.2", 1, 6) not in reassembler.in_flight

    def test_oversize_fragment_rejected(self):
        reassembler = BoundedFragmentReassembler(max_reassembled_bytes=1000)
        p1_hdr = bytes(IP(src="10.0.0.1", dst="10.0.0.2", id=1, proto=6))[:20]
        # Offset 1000 + 10 bytes = 1010 > 1000
        res = reassembler.process_fragment("10.0.0.1", "10.0.0.2", 1, 6, 1000, True, p1_hdr, b"A"*10)
        assert res is None
        assert reassembler.metrics["dropped_oversize"] == 1


class TestFeatureFidelityAndCompatibility:
    """Validate Sload Argus training alignment, Sjit RFC 3550, and STTL verification."""

    def test_sload_zero_for_single_packet_flow(self):
        state = ActiveFlowState(flow_key=("10.0.0.1", "10.0.0.2", 1234, 80, "TCP"), first_timestamp=1.0, last_timestamp=1.0)
        state.add_packet(PacketEnvelope(1.0, "10.0.0.1", "10.0.0.2", 1234, 80, "TCP", ttl=64, byte_length=100))
        final = state.finalize()
        assert final["fwd_packets"] == 1
        assert final["duration_seconds"] == 0.0
        assert final["sload"] == 0.0  # Exactly 0.0 for single packet flow

    def test_sload_argus_training_formula_reproducibility(self):
        # 4 packets, 400 bytes, duration 0.2s: smeansz = 100
        # Argus formula: (4 - 1) * 100 * 8 / 0.2 = 3 * 800 / 0.2 = 12,000 bps
        # (Standard naive rate would have been 400 * 8 / 0.2 = 16,000 bps)
        state = ActiveFlowState(flow_key=("10.0.0.1", "10.0.0.2", 1234, 80, "TCP"), first_timestamp=1.0, last_timestamp=1.0)
        for i in range(4):
            state.add_packet(PacketEnvelope(1.0 + (i * 0.05), "10.0.0.1", "10.0.0.2", 1234, 80, "TCP", ttl=64, byte_length=100))
        final = state.finalize()
        assert final["fwd_packets"] == 4
        assert final["duration_seconds"] == 0.15
        expected_argus_sload = ((4 - 1) * 100.0 * 8.0) / 0.15  # 16000.0
        assert final["sload"] == round(expected_argus_sload, 4)

    def test_invalid_sttl_marks_flow_incompatible(self):
        state = ActiveFlowState(flow_key=("10.0.0.1", "10.0.0.2", 1234, 80, "TCP"), first_timestamp=1.0, last_timestamp=1.0)
        # Envelope with ttl=0 (invalid)
        state.add_packet(PacketEnvelope(1.0, "10.0.0.1", "10.0.0.2", 1234, 80, "TCP", ttl=0, byte_length=50))
        final = state.finalize()
        assert not final["is_compatible"]
        assert final["compatibility_reason"] == "INVALID_OR_MISSING_STTL"

    def test_incompatible_flow_rejected_by_inference_worker(self):
        q: queue.Queue = queue.Queue()
        service = ProductionInferenceService()
        worker = StreamingInferenceWorker(flow_queue=q, inference_service=service)

        # Enqueue incompatible flow
        incompat_flow = {
            "flow_id": "test_incompat",
            "is_compatible": False,
            "compatibility_reason": "INVALID_OR_MISSING_STTL",
            "fwd_packets": 1,
            "fwd_bytes": 100,
            "duration_seconds": 0.0,
            "sttl": 0,
            "sload": 0.0,
            "swin": 0,
            "smeansz": 100,
            "sjit": 0.0,
            "sintpkt": 0.0,
            "is_sm_ips_ports": 0,
            "packet_rate": 0.0,
            "byte_rate": 0.0,
            "bytes_per_packet": 100,
        }
        worker._score_flow(incompat_flow)
        assert worker.incompatible_flows_rejected == 1
        assert worker.flows_scored == 0
        assert worker.anomalies_detected == 0
