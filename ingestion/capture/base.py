"""
Packet Source Abstraction Interface
===================================
Milestone 14 — Real-Time Network Detection & Flow Reconstruction

Defines the contract for packet input sources (offline PCAP replay, passive live capture).
Decouples raw packet ingestion from unidirectional flow reconstruction and ML inference.

Invariants:
- Never retains packet payloads by default (zero payload retention).
- Strictly preserves source provenance: 'PCAP_REPLAY', 'LIVE_CAPTURE', or 'TEST_FIXTURE'.
- Provides bounded buffering and backpressure signals.
"""
from __future__ import annotations

import abc
import enum
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any


class CaptureSourceType(enum.StrEnum):
    """Authoritative source provenance for network packet stream."""
    PCAP_REPLAY = "PCAP_REPLAY"
    LIVE_CAPTURE = "LIVE_CAPTURE"
    TEST_FIXTURE = "TEST_FIXTURE"


class WorkerState(enum.StrEnum):
    """Lifecycle state of capture and processing workers."""
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True)
class PacketEnvelope:
    """
    Lightweight, sanitized packet header envelope.
    Contains strictly the network and transport layer headers needed for
    unidirectional flow reconstruction. RAW PAYLOAD IS EXCLUDED.
    """
    timestamp: float          # Epoch seconds with microsecond resolution
    ip_src: str               # IPv4 source address
    ip_dst: str               # IPv4 destination address
    src_port: int             # Transport source port (0 for ICMP/raw)
    dst_port: int             # Transport destination port (0 for ICMP/raw)
    protocol: str             # "TCP", "UDP", "ICMP", "OTHER"
    ttl: int                  # IPv4 Time-to-Live
    byte_length: int          # Total IPv4 packet length in bytes
    tcp_window: int = 0       # TCP advertised window (0 for non-TCP)
    tcp_flags: str = ""       # TCP flags as seen (e.g. "S", "FA", "PA")
    is_fin_or_rst: bool = False # Immediate flow termination hint


class PacketSource(abc.ABC):
    """Abstract packet source providing standardized envelope streaming."""

    @property
    @abc.abstractmethod
    def source_type(self) -> CaptureSourceType:
        """Return the authoritative source provenance."""

    @property
    @abc.abstractmethod
    def is_running(self) -> bool:
        """Check if source is actively capturing/replaying."""

    @abc.abstractmethod
    def start(self) -> None:
        """Initialize and start the packet stream."""

    @abc.abstractmethod
    def stop(self) -> None:
        """Stop packet acquisition and release resources."""

    @abc.abstractmethod
    def pause(self) -> None:
        """Temporarily pause packet emission."""

    @abc.abstractmethod
    def resume(self) -> None:
        """Resume paused packet emission."""

    @abc.abstractmethod
    def packets(self) -> Iterator[PacketEnvelope]:
        """Stream parsed packet envelopes."""

    @abc.abstractmethod
    def get_metrics(self) -> dict[str, Any]:
        """Retrieve operational metrics (packets read, dropped, errors)."""

    def get_native_stats(self) -> dict[str, Any]:
        """Retrieve native driver kernel capture statistics where supported."""
        return {
            "native_kernel_drops_available": False,
            "native_kernel_drops": None,
            "native_kernel_drops_delta": None,
            "native_packets_received": None,
            "native_interface_drops": None,
            "kernel_drop_status": "UNAVAILABLE (Unsupported capture source)",
        }
