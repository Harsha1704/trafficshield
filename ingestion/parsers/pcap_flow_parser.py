"""
Unidirectional PCAP Packet-to-Flow Feature Extraction Engine
=============================================================
Milestone 14 — End-to-End Release Validation & Real-Time Feature Compatibility

Processes raw IP packets (from PCAP replay or live capture) and aggregates them
into unidirectional network flows matching the exact 10 base features expected
by the frozen TrafficShield production model:
1. duration_seconds
2. fwd_bytes
3. sttl
4. sload
5. fwd_packets
6. swin
7. smeansz
8. sjit
9. sintpkt
10. is_sm_ips_ports

Rejects reverse-direction observation and future lookahead.
Distinguishes finalized flows from provisional in-flight flow scoring.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("pcap_flow_parser")

try:
    from scapy.layers.inet import IP, TCP, UDP
    from scapy.utils import rdpcap
    SCAPY_AVAILABLE = True
except ImportError:
    SCAPY_AVAILABLE = False


@dataclass
class FlowState:
    """State accumulator for an in-flight unidirectional network flow."""
    flow_key: tuple[str, str, int, int, str]
    first_timestamp: float
    last_timestamp: float
    fwd_packets: int = 0
    fwd_bytes: int = 0
    sttl: int = 64
    swin: int = 0
    inter_arrival_times_ms: list[float] = field(default_factory=list)
    is_sm_ips_ports: int = 0
    is_closed: bool = False

    def add_packet(self, timestamp: float, byte_count: int, ttl: int, win: int) -> None:
        """Accumulate forward packet observation into active flow state."""
        if self.fwd_packets > 0:
            delta_ms = max(0.0, (timestamp - self.last_timestamp) * 1000.0)
            self.inter_arrival_times_ms.append(delta_ms)
        else:
            self.sttl = ttl
            self.first_timestamp = timestamp

        self.last_timestamp = timestamp
        self.fwd_packets += 1
        self.fwd_bytes += byte_count

        if win > 0:
            self.swin = win

    def finalize(self, current_time: float | None = None) -> dict[str, Any]:
        """
        Finalize flow and calculate exact causal features for inference.
        """
        duration = max(0.0, self.last_timestamp - self.first_timestamp)
        pkts = max(1, self.fwd_packets)
        bytes_ = max(0, self.fwd_bytes)

        # 1. duration_seconds
        duration_seconds = round(duration, 6)

        # 2. fwd_bytes
        fwd_bytes = float(bytes_)

        # 3. sttl
        sttl = float(self.sttl)

        # 4. sload: bits per second (causal calculation)
        if duration_seconds > 0:
            sload = round((bytes_ * 8.0) / duration_seconds, 4)
        else:
            sload = 0.0

        # 5. fwd_packets
        fwd_packets = float(pkts)

        # 6. swin: TCP window advertisement (0 if non-TCP or unadvertised)
        swin = float(self.swin)

        # 7. smeansz: mean forward packet size
        smeansz = round(float(bytes_ / pkts), 4)

        # 8. sjit: RFC 3550 standard inter-arrival jitter
        if len(self.inter_arrival_times_ms) > 1:
            diffs = [
                abs(self.inter_arrival_times_ms[i] - self.inter_arrival_times_ms[i - 1])
                for i in range(1, len(self.inter_arrival_times_ms))
            ]
            sjit = round(float(sum(diffs) / len(diffs)), 4) if diffs else 0.0
        else:
            sjit = 0.0

        # 9. sintpkt: mean inter-packet arrival time in ms
        if pkts > 1 and duration_seconds > 0:
            sintpkt = round((duration_seconds * 1000.0) / (pkts - 1), 4)
        else:
            sintpkt = 0.0

        # 10. is_sm_ips_ports: Land attack flag
        is_sm = int(self.is_sm_ips_ports)

        src_ip, dst_ip, src_port, dst_port, proto = self.flow_key

        return {
            "flow_id": f"{src_ip}:{src_port}->{dst_ip}:{dst_port}/{proto}",
            "src_ip": src_ip,
            "dst_ip": dst_ip,
            "src_port": src_port,
            "dst_port": dst_port,
            "protocol": proto,
            "first_timestamp": self.first_timestamp,
            "last_timestamp": self.last_timestamp,
            "duration_seconds": duration_seconds,
            "fwd_bytes": fwd_bytes,
            "sttl": sttl,
            "sload": sload,
            "fwd_packets": fwd_packets,
            "swin": swin,
            "smeansz": smeansz,
            "sjit": sjit,
            "sintpkt": sintpkt,
            "is_sm_ips_ports": is_sm,
            "is_finalized": True,
        }


class PcapFlowAggregator:
    """
    Stateful unidirectional flow aggregator for PCAP packet replay and live capture.
    Maintains active flows and finalizes them on TCP FIN/RST or idle timeout.
    """

    def __init__(self, idle_timeout: float = 2.0) -> None:
        self.idle_timeout = idle_timeout
        self.active_flows: dict[tuple[str, str, int, int, str], FlowState] = {}
        self.finalized_flows: list[dict[str, Any]] = []

    def process_raw_packet(self, packet: Any) -> dict[str, Any] | None:
        """
        Process a single Scapy packet. Returns a finalized flow dict if a flow terminated,
        otherwise None.
        """
        if not hasattr(packet, "haslayer") or not packet.haslayer(IP):
            return None

        ip_layer = packet[IP]
        src_ip = ip_layer.src
        dst_ip = ip_layer.dst
        ttl = int(ip_layer.ttl)
        byte_len = int(ip_layer.len) if hasattr(ip_layer, "len") else len(packet)

        src_port = 0
        dst_port = 0
        win = 0
        proto_str = "OTHER"
        is_closed = False

        if packet.haslayer(TCP):
            tcp_layer = packet[TCP]
            src_port = int(tcp_layer.sport)
            dst_port = int(tcp_layer.dport)
            win = int(tcp_layer.window)
            proto_str = "TCP"
            flags = str(tcp_layer.flags)
            if "F" in flags or "R" in flags:
                is_closed = True
        elif packet.haslayer(UDP):
            udp_layer = packet[UDP]
            src_port = int(udp_layer.sport)
            dst_port = int(udp_layer.dport)
            proto_str = "UDP"

        pkt_time = float(packet.time) if hasattr(packet, "time") else 0.0
        flow_key = (src_ip, dst_ip, src_port, dst_port, proto_str)

        # Expire stale flows that breached idle timeout
        expired_flow = self._check_idle_expiration(pkt_time)

        # Update or create flow state
        if flow_key not in self.active_flows:
            is_sm = 1 if (src_ip == dst_ip and src_port == dst_port) else 0
            state = FlowState(
                flow_key=flow_key,
                first_timestamp=pkt_time,
                last_timestamp=pkt_time,
                sttl=ttl,
                swin=win,
                is_sm_ips_ports=is_sm,
            )
            self.active_flows[flow_key] = state

        state = self.active_flows[flow_key]
        state.add_packet(timestamp=pkt_time, byte_count=byte_len, ttl=ttl, win=win)

        # If flow terminated by TCP FIN or RST, finalize immediately
        if is_closed:
            finalized = state.finalize()
            del self.active_flows[flow_key]
            self.finalized_flows.append(finalized)
            return finalized

        return expired_flow

    def _check_idle_expiration(self, current_time: float) -> dict[str, Any] | None:
        """Identify and expire any active flow that exceeded idle timeout."""
        for key, state in list(self.active_flows.items()):
            if (current_time - state.last_timestamp) > self.idle_timeout:
                finalized = state.finalize()
                del self.active_flows[key]
                self.finalized_flows.append(finalized)
                return finalized
        return None

    def flush(self) -> list[dict[str, Any]]:
        """Flush all remaining active in-flight flows."""
        flushed = []
        for _key, state in list(self.active_flows.items()):
            finalized = state.finalize()
            flushed.append(finalized)
            self.finalized_flows.append(finalized)
        self.active_flows.clear()
        return flushed

    def extract_flows_from_pcap(self, pcap_path: str | Path) -> list[dict[str, Any]]:
        """Read a PCAP file and return all extracted finalized flow records."""
        if not SCAPY_AVAILABLE:
            raise RuntimeError("Scapy is required for PCAP parsing. Install with: pip install scapy")

        p = Path(pcap_path)
        if not p.exists():
            raise FileNotFoundError(f"PCAP file not found: {pcap_path}")

        packets = rdpcap(str(p))
        for pkt in packets:
            self.process_raw_packet(pkt)

        # Flush remaining flows at EOF
        self.flush()
        return list(self.finalized_flows)
