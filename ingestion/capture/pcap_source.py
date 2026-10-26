"""
Offline PCAP/PCAPNG Packet Replay Source
========================================
Milestone 14 — Real-Time Network Detection & Flow Reconstruction

Safely reads and replays pre-captured packet files with controllable speed.
Exposes pause/resume/stop controls and measures replay latency and packet counts.

Guarantees:
- Validates file existence, format, and magic bytes.
- Strictly labels all output with provenance 'PCAP_REPLAY'.
- Never retains or logs raw application payloads.
- Bounded memory streaming using generator/iterator.
"""
from __future__ import annotations

import collections
import logging
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ingestion.capture.base import CaptureSourceType, PacketEnvelope, PacketSource
from ingestion.capture.packet_validator import (
    IPv4PacketValidator,
    PacketRejectionCategory,
)
from ingestion.flow.fragment_reassembler import BoundedFragmentReassembler

logger = logging.getLogger("pcap_replay_source")

# PCAP / PCAPNG Magic Bytes
VALID_MAGIC_BYTES = (
    b"\xa1\xb2\xc3\xd4",  # Standard pcap (same endian)
    b"\xd4\xc3\xb2\xa1",  # Standard pcap (swapped endian)
    b"\xa1\xb2\x3c\x4d",  # Nanosecond pcap (same endian)
    b"\x4d\x3c\xb2\xa1",  # Nanosecond pcap (swapped endian)
    b"\x0a\x0d\x0d\x0a",  # PCAPNG block header
)

MAX_PCAP_SIZE_BYTES = 500 * 1024 * 1024  # 500 MB limit for safety


class PcapReplaySource(PacketSource):
    """
    Controlled replay source for offline packet captures (.pcap / .pcapng).
    Features precision rate pacing, pause/resume, and operational telemetry.
    """

    def __init__(
        self,
        filepath: str | Path,
        speed_multiplier: float = 1.0,
        max_packets: int | None = None,
    ) -> None:
        self.filepath = Path(filepath)
        self.speed_multiplier = max(0.0, float(speed_multiplier))
        self.max_packets = max_packets

        self._validate_file()

        self._running = False
        self._paused = False
        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused initially
        self._stop_event = threading.Event()

        # Telemetry metrics
        self._packets_read = 0
        self._bytes_read = 0
        self._malformed_packets = 0
        self._truncated_packets = 0
        self._unsupported_packets = 0
        self._rejection_reasons: dict[str, int] = collections.defaultdict(int)
        self._fragment_reassembler = BoundedFragmentReassembler()
        self._start_time: float | None = None
        self._last_packet_time: float | None = None

    def _validate_file(self) -> None:
        """Validate capture file existence, size, and header magic bytes."""
        if not self.filepath.exists():
            raise FileNotFoundError(f"Capture file not found: {self.filepath}")

        if not self.filepath.is_file():
            raise ValueError(f"Path is not a regular file: {self.filepath}")

        size = self.filepath.stat().st_size
        if size == 0:
            raise ValueError(f"Capture file is empty: {self.filepath}")

        if size > MAX_PCAP_SIZE_BYTES:
            raise ValueError(
                f"Capture file size ({size / (1024*1024):.1f} MB) exceeds maximum allowed limit "
                f"of {MAX_PCAP_SIZE_BYTES / (1024*1024):.0f} MB"
            )

        # Check magic bytes
        with open(self.filepath, "rb") as f:
            header = f.read(4)
            if not any(header.startswith(m) for m in VALID_MAGIC_BYTES):
                raise ValueError(
                    f"Invalid PCAP/PCAPNG header format. Magic bytes {header.hex()} not recognized."
                )

    @property
    def source_type(self) -> CaptureSourceType:
        return CaptureSourceType.PCAP_REPLAY

    @property
    def is_running(self) -> bool:
        return self._running and not self._stop_event.is_set()

    def start(self) -> None:
        """Initialize replay stream."""
        self._running = True
        self._stop_event.clear()
        self._pause_event.set()
        self._start_time = time.time()
        logger.info(
            "PCAP replay started: %s (speed: %sx)",
            self.filepath.name,
            "max" if self.speed_multiplier == 0.0 else f"{self.speed_multiplier:.1f}",
        )

    def stop(self) -> None:
        """Halt replay stream and release resources."""
        self._stop_event.set()
        self._pause_event.set()
        self._running = False
        logger.info("PCAP replay stopped: %s (packets: %d)", self.filepath.name, self._packets_read)

    def pause(self) -> None:
        """Pause packet pacing."""
        self._paused = True
        self._pause_event.clear()
        logger.info("PCAP replay paused: %s", self.filepath.name)

    def resume(self) -> None:
        """Resume packet pacing."""
        self._paused = False
        self._pause_event.set()
        logger.info("PCAP replay resumed: %s", self.filepath.name)

    def packets(self) -> Iterator[PacketEnvelope]:
        """
        Yield parsed PacketEnvelope items paced according to recorded timestamps
        and the configured speed multiplier.
        """
        try:
            from scapy.layers.inet import IP, TCP, UDP
            from scapy.utils import PcapReader
        except ImportError as exc:
            raise RuntimeError("Scapy is required for PCAP reading. Run: pip install scapy") from exc

        self.start()

        prev_pkt_ts: float | None = None
        reader = PcapReader(str(self.filepath))

        try:
            for raw_pkt in reader:
                if self._stop_event.is_set():
                    break

                # Handle pause
                if not self._pause_event.is_set():
                    self._pause_event.wait()
                    if self._stop_event.is_set():
                        break

                if not raw_pkt.haslayer(IP):
                    self._unsupported_packets += 1
                    self._rejection_reasons["UNSUPPORTED_NON_IP"] += 1
                    continue

                raw_ip_bytes = bytes(raw_pkt[IP])
                val = IPv4PacketValidator.validate_ipv4_frame(raw_ip_bytes)
                if not val.is_valid:
                    if val.category == PacketRejectionCategory.MALFORMED:
                        self._malformed_packets += 1
                    elif val.category == PacketRejectionCategory.TRUNCATED:
                        self._truncated_packets += 1
                    elif val.category == PacketRejectionCategory.UNSUPPORTED:
                        self._unsupported_packets += 1
                    if val.reason:
                        self._rejection_reasons[val.reason.value] += 1
                    continue

                if val.is_snaplen_truncated:
                    self._truncated_packets += 1
                    self._rejection_reasons["TRUNCATED_CAPTURE_SNAPLEN"] += 1

                if val.is_fragment:
                    header_len = val.ip_header_len
                    hdr = raw_ip_bytes[:header_len]
                    payload = raw_ip_bytes[header_len:val.ip_total_len]
                    reassembled = self._fragment_reassembler.process_fragment(
                        src_ip=str(raw_pkt[IP].src),
                        dst_ip=str(raw_pkt[IP].dst),
                        ip_id=val.ip_id,
                        protocol=val.protocol,
                        frag_offset=val.frag_offset,
                        more_fragments=val.more_fragments,
                        header_bytes=hdr,
                        payload_bytes=payload,
                    )
                    if reassembled is None:
                        # Incomplete / in-flight fragment - safely held or dropped
                        continue
                    # Datagram successfully reassembled! Parse complete datagram
                    raw_pkt = IP(reassembled)

                ip_layer = raw_pkt[IP]
                pkt_ts = float(raw_pkt.time) if hasattr(raw_pkt, "time") else time.time()

                # Pacing calculation if speed multiplier > 0
                if self.speed_multiplier > 0.0 and prev_pkt_ts is not None:
                    delta_recorded = pkt_ts - prev_pkt_ts
                    if 0.0 < delta_recorded < 10.0:  # Cap sleep at 10s for long idle gaps
                        delay = delta_recorded / self.speed_multiplier
                        # Sleep in small slices to remain responsive to stop/pause
                        deadline = time.time() + delay
                        while time.time() < deadline:
                            if self._stop_event.is_set() or not self._pause_event.is_set():
                                break
                            time.sleep(min(0.02, max(0.0, deadline - time.time())))

                prev_pkt_ts = pkt_ts

                # Extract protocol and ports
                src_ip = str(ip_layer.src)
                dst_ip = str(ip_layer.dst)
                ttl = val.ttl if not val.is_fragment else int(ip_layer.ttl)
                byte_len = val.ip_total_len if not val.is_fragment else len(raw_pkt)

                src_port = 0
                dst_port = 0
                win = 0
                proto_str = "OTHER"
                flags_str = ""
                is_fin_rst = False

                if raw_pkt.haslayer(TCP):
                    tcp_layer = raw_pkt[TCP]
                    src_port = int(tcp_layer.sport)
                    dst_port = int(tcp_layer.dport)
                    win = int(tcp_layer.window)
                    proto_str = "TCP"
                    flags_str = str(tcp_layer.flags)
                    if "F" in flags_str or "R" in flags_str:
                        is_fin_rst = True
                elif raw_pkt.haslayer(UDP):
                    udp_layer = raw_pkt[UDP]
                    src_port = int(udp_layer.sport)
                    dst_port = int(udp_layer.dport)
                    proto_str = "UDP"

                envelope = PacketEnvelope(
                    timestamp=pkt_ts,
                    ip_src=src_ip,
                    ip_dst=dst_ip,
                    src_port=src_port,
                    dst_port=dst_port,
                    protocol=proto_str,
                    ttl=ttl,
                    byte_length=byte_len,
                    tcp_window=win,
                    tcp_flags=flags_str,
                    is_fin_or_rst=is_fin_rst,
                )

                self._packets_read += 1
                self._bytes_read += byte_len
                self._last_packet_time = pkt_ts

                yield envelope

                if self.max_packets and self._packets_read >= self.max_packets:
                    logger.info("Reached maximum requested packets (%d)", self.max_packets)
                    break

        except Exception as exc:
            self._malformed_packets += 1
            logger.error("Error reading PCAP packet: %s", exc)
            raise
        finally:
            reader.close()
            self._running = False

    def get_metrics(self) -> dict[str, Any]:
        """Return operational telemetry for the replay stream."""
        now = time.time()
        elapsed = (now - self._start_time) if self._start_time else 0.0
        return {
            "source_type": self.source_type.value,
            "filename": self.filepath.name,
            "file_size_bytes": self.filepath.stat().st_size if self.filepath.exists() else 0,
            "is_running": self.is_running,
            "is_paused": self._paused,
            "speed_multiplier": self.speed_multiplier,
            "packets_read": self._packets_read,
            "bytes_read": self._bytes_read,
            "malformed_packets": self._malformed_packets,
            "truncated_packets": self._truncated_packets,
            "unsupported_packets": self._unsupported_packets,
            "rejection_reasons": dict(self._rejection_reasons),
            "fragment_metrics": self._fragment_reassembler.get_metrics(),
            "elapsed_seconds": round(elapsed, 2),
            "replay_pps": round(self._packets_read / elapsed, 1) if elapsed > 0 else 0.0,
            "last_packet_timestamp": self._last_packet_time,
            "native_kernel_drops_available": False,
            "native_kernel_drops": None,
            "native_kernel_drops_delta": None,
            "native_packets_received": None,
            "native_interface_drops": None,
            "kernel_drop_status": "UNAVAILABLE (PCAP replay is an offline file source)",
        }
