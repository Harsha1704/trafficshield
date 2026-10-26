"""
Unidirectional Flow Builder & Stateful Aggregator
=================================================
Milestone 14 — Real-Time Network Detection & Flow Reconstruction

Aggregates forward-observable packet streams into directional flow records.
Strictly conforms to TrafficShield's One-Way Feature Policy.

Non-negotiable invariants:
- Directional flow key: (src_ip, dst_ip, src_port, dst_port, protocol).
- ZERO reverse traffic integration: never merges reverse-direction packets.
- ZERO future leakage: all features computed causally from packet arrival sequence.
- RFC 3550 exponential moving average jitter calculation.
- Bounded memory: enforces idle timeouts, maximum flow lifetimes, and table size caps.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

from ingestion.capture.base import PacketEnvelope

logger = logging.getLogger("flow_builder")


@dataclass
class ActiveFlowState:
    """State accumulator for an in-flight unidirectional flow."""
    flow_key: tuple[str, str, int, int, str]
    first_timestamp: float
    last_timestamp: float
    fwd_packets: int = 0
    fwd_bytes: int = 0
    sttl: int | None = None
    swin: int = 0
    is_sm_ips_ports: int = 0
    rfc3550_jitter_ms: float = 0.0
    prev_transit_ms: float | None = None
    is_closed: bool = False

    def add_packet(self, envelope: PacketEnvelope) -> None:
        """Incorporate a forward packet into the flow state."""
        ts = envelope.timestamp

        if self.fwd_packets == 0:
            self.first_timestamp = ts
            self.sttl = envelope.ttl
        else:
            # Calculate RFC 3550 jitter
            delta_arrival_ms = max(0.0, (ts - self.last_timestamp) * 1000.0)
            if self.prev_transit_ms is not None:
                d = abs(delta_arrival_ms - self.prev_transit_ms)
                self.rfc3550_jitter_ms += (d - self.rfc3550_jitter_ms) / 16.0
            self.prev_transit_ms = delta_arrival_ms

        self.last_timestamp = ts
        self.fwd_packets += 1
        self.fwd_bytes += envelope.byte_length

        if envelope.tcp_window > 0:
            self.swin = envelope.tcp_window

        if envelope.is_fin_or_rst:
            self.is_closed = True

    def finalize(self) -> dict[str, Any]:
        """Produce the 13-feature model input vector and audit metadata."""
        src_ip, dst_ip, src_port, dst_port, proto = self.flow_key
        duration = max(0.0, self.last_timestamp - self.first_timestamp)
        pkts = self.fwd_packets
        bytes_ = self.fwd_bytes

        # Strict validation of required fields: zero silent imputation of sttl
        is_compatible = True
        compatibility_reason: str | None = None
        if self.sttl is None or self.sttl <= 0:
            is_compatible = False
            compatibility_reason = "INVALID_OR_MISSING_STTL"
            resolved_sttl = 0
        else:
            resolved_sttl = self.sttl

        # Mean size and inter-packet interval
        smeansz = (bytes_ / pkts) if pkts > 0 else 0.0
        sintpkt = ((duration * 1000.0) / (pkts - 1)) if pkts > 1 else 0.0
        bytes_per_packet = smeansz

        # Calculate time-dependent rates guarded against zero division
        # Training-time definition: Sload = ((pkts - 1) * smeansz * 8.0) / duration
        if duration > 0.0 and pkts > 1:
            sload = ((pkts - 1) * smeansz * 8.0) / duration
            packet_rate = pkts / duration
            byte_rate = bytes_ / duration
        elif duration > 0.0 and pkts == 1:
            sload = 0.0
            packet_rate = pkts / duration
            byte_rate = bytes_ / duration
        else:
            sload = 0.0
            packet_rate = 0.0
            byte_rate = 0.0

        return {
            # Metadata & network coordinates
            "flow_id": f"{src_ip}:{src_port}->{dst_ip}:{dst_port}/{proto}",
            "src_ip": src_ip,
            "dst_ip": dst_ip,
            "src_port": src_port,
            "dst_port": dst_port,
            "protocol": proto,
            "first_timestamp": self.first_timestamp,
            "last_timestamp": self.last_timestamp,
            "is_finalized": True,
            "is_compatible": is_compatible,
            "compatibility_reason": compatibility_reason,
            # 10 Base Features
            "duration_seconds": round(duration, 6),
            "fwd_bytes": bytes_,
            "sttl": resolved_sttl,
            "sload": round(sload, 4),
            "fwd_packets": pkts,
            "swin": self.swin,
            "smeansz": round(smeansz, 4),
            "sjit": round(self.rfc3550_jitter_ms, 4),
            "sintpkt": round(sintpkt, 4),
            "is_sm_ips_ports": self.is_sm_ips_ports,
            # 3 Causal Derived Rates
            "packet_rate": round(packet_rate, 4),
            "byte_rate": round(byte_rate, 4),
            "bytes_per_packet": round(bytes_per_packet, 4),
        }


class UnidirectionalFlowBuilder:
    """
    Stateful unidirectional flow constructor.
    Tracks active flows with memory bounding, idle expiration, and TCP lifecycle awareness.
    """

    def __init__(
        self,
        idle_timeout_seconds: float = 2.0,
        max_flow_lifetime_seconds: float = 60.0,
        max_active_flows: int = 10000,
    ) -> None:
        self.idle_timeout_seconds = idle_timeout_seconds
        self.max_flow_lifetime_seconds = max_flow_lifetime_seconds
        self.max_active_flows = max_active_flows

        self.active_flows: dict[tuple[str, str, int, int, str], ActiveFlowState] = {}
        self._lock = threading.Lock()
        self._is_closed = False

        # Operational metrics
        self.packets_processed = 0
        self.flows_created = 0
        self.flows_completed = 0
        self.flows_expired_timeout = 0
        self.flows_evicted_overflow = 0
        self.flows_closed_tcp = 0
        self.flows_flushed = 0

    def process_packet(self, envelope: PacketEnvelope) -> list[dict[str, Any]]:
        """
        Process a single packet envelope. Returns any flows finalized as a result of:
        1. Idle timeout expiration of existing flows.
        2. Lifetime expiration of long-running flows.
        3. TCP FIN or RST in the current packet.
        """
        with self._lock:
            if self._is_closed:
                logger.warning("Attempted to process packet on closed FlowBuilder; dropping packet.")
                return []

            self.packets_processed += 1
            current_time = envelope.timestamp
            finalized_flows: list[dict[str, Any]] = []

            # 1. Check expiration of existing active flows
            finalized_flows.extend(self._expire_stale_flows(current_time))

            # 2. Extract unidirectional 5-tuple
            flow_key = (
                envelope.ip_src,
                envelope.ip_dst,
                envelope.src_port,
                envelope.dst_port,
                envelope.protocol,
            )

            # 3. Create or update flow state
            if flow_key not in self.active_flows:
                # Enforce max active flow table size bound
                if len(self.active_flows) >= self.max_active_flows:
                    oldest_flow = self._evict_oldest_flow()
                    if oldest_flow:
                        finalized_flows.append(oldest_flow)

                is_sm = 1 if (envelope.ip_src == envelope.ip_dst and envelope.src_port == envelope.dst_port) else 0
                state = ActiveFlowState(
                    flow_key=flow_key,
                    first_timestamp=current_time,
                    last_timestamp=current_time,
                    is_sm_ips_ports=is_sm,
                )
                self.active_flows[flow_key] = state
                self.flows_created += 1

            state = self.active_flows[flow_key]
            state.add_packet(envelope)

            # 4. Immediate finalization on TCP FIN/RST or lifetime expiration
            is_lifetime_exceeded = (current_time - state.first_timestamp) >= self.max_flow_lifetime_seconds
            if state.is_closed or is_lifetime_exceeded:
                finalized = state.finalize()
                del self.active_flows[flow_key]
                self.flows_completed += 1
                self.flows_closed_tcp += 1
                finalized_flows.append(finalized)

            return finalized_flows

    def _expire_stale_flows(self, current_time: float) -> list[dict[str, Any]]:
        """Identify and finalize flows that breached the idle timeout."""
        expired: list[dict[str, Any]] = []
        for key, state in list(self.active_flows.items()):
            if (current_time - state.last_timestamp) > self.idle_timeout_seconds:
                finalized = state.finalize()
                del self.active_flows[key]
                self.flows_completed += 1
                self.flows_expired_timeout += 1
                expired.append(finalized)
        return expired

    def _evict_oldest_flow(self) -> dict[str, Any] | None:
        """Evict the least recently updated flow when state table reaches capacity."""
        if not self.active_flows:
            return None
        oldest_key = min(self.active_flows.keys(), key=lambda k: self.active_flows[k].last_timestamp)
        state = self.active_flows.pop(oldest_key)
        self.flows_completed += 1
        self.flows_evicted_overflow += 1
        return state.finalize()

    def flush(self) -> list[dict[str, Any]]:
        """Flush and finalize all remaining active in-flight flows and close the builder."""
        with self._lock:
            self._is_closed = True
            flushed: list[dict[str, Any]] = []
            for _key, state in list(self.active_flows.items()):
                finalized = state.finalize()
                flushed.append(finalized)
                self.flows_completed += 1
                self.flows_flushed += 1
            self.active_flows.clear()
            return flushed

    def get_metrics(self) -> dict[str, Any]:
        """Operational metrics for the flow reconstruction engine."""
        return {
            "active_flows_count": len(self.active_flows),
            "packets_processed": self.packets_processed,
            "flows_created": self.flows_created,
            "flows_completed": self.flows_completed,
            "flows_flushed": self.flows_flushed,
            "flows_expired_timeout": self.flows_expired_timeout,
            "flows_evicted_overflow": self.flows_evicted_overflow,
            "flows_closed_tcp": self.flows_closed_tcp,
            "is_closed": self._is_closed,
            "idle_timeout_seconds": self.idle_timeout_seconds,
            "max_flow_lifetime_seconds": self.max_flow_lifetime_seconds,
            "max_active_flows_cap": self.max_active_flows,
        }
