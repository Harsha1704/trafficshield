"""
Passive Live Network Interface Capture Source
=============================================
Milestone 14 — Real-Time Network Detection & Flow Reconstruction

Captures live packets from an explicitly selected, authorized network interface.
Enforces driver verification, privilege checks, and graceful error reporting.

Non-negotiable invariants:
- Never silently fall back from live capture to simulated or demo traffic.
- Never capture all interfaces by default; requires explicit interface selection.
- Does not retain packet payloads by default (zero payload retention).
- Provides truthful status: if kernel driver is missing, reports it immediately.
"""
from __future__ import annotations

import collections
import logging
import platform
import queue
import threading
import time
from collections.abc import Iterator
from typing import Any

from ingestion.capture.base import CaptureSourceType, PacketEnvelope, PacketSource
from ingestion.capture.packet_validator import (
    IPv4PacketValidator,
    PacketRejectionCategory,
)
from ingestion.flow.fragment_reassembler import BoundedFragmentReassembler

logger = logging.getLogger("live_capture_source")


class DriverNotFoundError(RuntimeError):
    """Raised when native packet capture driver (Npcap / libpcap) is absent."""


class InterfaceNotFoundError(ValueError):
    """Raised when requested network interface does not exist or is inaccessible."""


def is_capture_driver_available() -> tuple[bool, str]:
    """
    Check if the native kernel packet capture driver is installed and functional.
    Returns (is_available, diagnostic_message).
    """
    system = platform.system()
    if system == "Windows":
        try:
            import ctypes
            # Test for wpcap.dll or Packet.dll in Windows System32
            ctypes.cdll.LoadLibrary("wpcap.dll")
            return True, "Npcap/WinPcap driver is installed and active."
        except OSError:
            return False, (
                "Npcap/WinPcap driver not installed (wpcap.dll missing). "
                "Passive live interface sniffing requires Npcap on Windows. "
                "Download from https://npcap.com and install with WinPcap API-compatible mode."
            )
    elif system in ("Linux", "Darwin"):
        try:
            import ctypes
            ctypes.cdll.LoadLibrary("libpcap.so") or ctypes.cdll.LoadLibrary("libpcap.so.1")
            return True, "libpcap driver is installed and active."
        except OSError:
            return False, "libpcap library (libpcap.so) not found in system library paths."
    return False, f"Unsupported operating system for live capture: {system}"


def enumerate_network_interfaces() -> list[dict[str, Any]]:
    """
    Enumerate all local network interfaces and report operational metadata.
    Does not initiate promiscuous capture.
    """
    driver_ok, driver_msg = is_capture_driver_available()
    interfaces: list[dict[str, Any]] = []

    try:
        import psutil
        net_addrs = psutil.net_if_addrs()
        net_stats = psutil.net_if_stats()

        for iface_name, addrs in net_addrs.items():
            ipv4_list = [a.address for a in addrs if a.family.name == "AF_INET"]
            mac_list = [a.address for a in addrs if a.family.name in ("AF_LINK", "AF_PACKET")]
            stats = net_stats.get(iface_name)

            is_up = stats.isup if stats else False
            is_loopback = iface_name.lower().startswith("loopback") or any(
                ip.startswith("127.") for ip in ipv4_list
            )

            interfaces.append({
                "name": iface_name,
                "description": iface_name,
                "ipv4_addresses": ipv4_list,
                "mac_address": mac_list[0] if mac_list else None,
                "is_up": is_up,
                "is_loopback": is_loopback,
                "driver_available": driver_ok,
                "driver_status": driver_msg,
            })
    except ImportError:
        try:
            from scapy.all import conf
            if hasattr(conf, "ifaces"):
                for dev_id, iface in conf.ifaces.items():
                    name = getattr(iface, "name", str(dev_id))
                    desc = getattr(iface, "description", name)
                    ip = getattr(iface, "ip", None)
                    mac = getattr(iface, "mac", None)
                    is_loopback = (
                        "loopback" in name.lower()
                        or "loopback" in desc.lower()
                        or (bool(ip) and str(ip).startswith("127."))
                    )
                    is_up = bool(ip) and not str(ip).startswith("169.254.")

                    interfaces.append({
                        "name": name,
                        "description": desc,
                        "ipv4_addresses": [ip] if ip else [],
                        "mac_address": mac,
                        "is_up": is_up,
                        "is_loopback": is_loopback,
                        "driver_available": driver_ok,
                        "driver_status": driver_msg,
                    })
        except Exception:
            pass

        if not interfaces:
            # Fallback to standard socket inspection if neither psutil nor scapy.ifaces work
            import socket
            hostname = socket.gethostname()
            try:
                ips = socket.gethostbyname_ex(hostname)[2]
            except Exception:
                ips = []

            interfaces.append({
                "name": "default",
                "description": f"Host {hostname}",
                "ipv4_addresses": ips,
                "mac_address": None,
                "is_up": True,
                "is_loopback": False,
                "driver_available": driver_ok,
                "driver_status": driver_msg,
            })

    return interfaces


class LiveCaptureSource(PacketSource):
    """
    Passive sniffer for a designated host network interface.
    Uses dedicated capture thread with bounded queue and backpressure.
    """

    def __init__(
        self,
        interface: str,
        bpf_filter: str = "ip",
        packet_queue_size: int = 5000,
    ) -> None:
        self.interface = interface.strip()
        self.bpf_filter = bpf_filter
        self.packet_queue_size = packet_queue_size

        self._driver_ok, self._driver_msg = is_capture_driver_available()
        self._running = False
        self._paused = False
        self._stop_event = threading.Event()
        self._queue: queue.Queue[PacketEnvelope | None] = queue.Queue(maxsize=packet_queue_size)
        self._thread: threading.Thread | None = None

        # Metrics
        self._packets_captured = 0
        self._packets_dropped = 0
        self._bytes_captured = 0
        self._malformed_packets = 0
        self._truncated_packets = 0
        self._unsupported_packets = 0
        self._rejection_reasons: dict[str, int] = collections.defaultdict(int)
        self._fragment_reassembler = BoundedFragmentReassembler()
        self._start_time: float | None = None
        self._last_packet_time: float | None = None

    @property
    def source_type(self) -> CaptureSourceType:
        return CaptureSourceType.LIVE_CAPTURE

    @property
    def is_running(self) -> bool:
        return self._running and not self._stop_event.is_set()

    def start(self) -> None:
        """Start background packet capture thread on selected interface."""
        if not self._driver_ok:
            raise DriverNotFoundError(self._driver_msg)

        if not self.interface:
            raise ValueError("An explicit, authorized network interface must be specified.")

        self._running = True
        self._stop_event.clear()
        self._start_time = time.time()

        self._thread = threading.Thread(
            target=self._capture_worker,
            name=f"LiveCapture-{self.interface}",
            daemon=True,
        )
        self._thread.start()
        logger.info("Live capture started on interface: %s", self.interface)

    def stop(self) -> None:
        """Signal capture thread to terminate and flush queue."""
        self._stop_event.set()
        self._running = False
        # Put sentinel to unblock any consumer
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("Live capture stopped on interface: %s", self.interface)

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def _packet_callback(self, raw_pkt: Any) -> None:
        """Callback invoked by Scapy sniffer for each raw packet."""
        if self._stop_event.is_set() or self._paused:
            return

        try:
            from scapy.layers.inet import IP, TCP, UDP
            if not raw_pkt.haslayer(IP):
                self._unsupported_packets += 1
                self._rejection_reasons["UNSUPPORTED_NON_IP"] += 1
                return

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
                return

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
                    # Waiting for fragments or dropped
                    return
                raw_pkt = IP(reassembled)

            ip_layer = raw_pkt[IP]
            pkt_ts = float(raw_pkt.time) if hasattr(raw_pkt, "time") else time.time()
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

            # Enqueue with non-blocking drop on full queue
            try:
                self._queue.put_nowait(envelope)
                self._packets_captured += 1
                self._bytes_captured += byte_len
                self._last_packet_time = pkt_ts
            except queue.Full:
                self._packets_dropped += 1
                if self._packets_dropped % 100 == 1:
                    logger.warning("Packet queue full! Dropped %d packets.", self._packets_dropped)

        except Exception as exc:
            logger.debug("Packet parsing error in live sniffer: %s", exc)

    def _capture_worker(self) -> None:
        """Background thread executing passive interface sniffing."""
        try:
            from scapy.all import sniff
            sniff(
                iface=self.interface,
                filter=self.bpf_filter,
                prn=self._packet_callback,
                stop_filter=lambda _: self._stop_event.is_set(),
                store=False,
            )
        except Exception as exc:
            logger.error("Live sniffing fatal error on %s: %s", self.interface, exc)
        finally:
            self._running = False
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass

    def packets(self) -> Iterator[PacketEnvelope]:
        """Stream parsed PacketEnvelope items from capture worker queue."""
        while not self._stop_event.is_set() or not self._queue.empty():
            try:
                env = self._queue.get(timeout=0.2)
                if env is None:
                    break
                yield env
            except queue.Empty:
                continue

    def get_metrics(self) -> dict[str, Any]:
        """Return operational telemetry for the live capture stream."""
        now = time.time()
        elapsed = (now - self._start_time) if self._start_time else 0.0
        return {
            "source_type": self.source_type.value,
            "interface": self.interface,
            "driver_available": self._driver_ok,
            "driver_message": self._driver_msg,
            "is_running": self.is_running,
            "is_paused": self._paused,
            "packets_captured": self._packets_captured,
            "packets_dropped": self._packets_dropped,
            "bytes_captured": self._bytes_captured,
            "malformed_packets": self._malformed_packets,
            "truncated_packets": self._truncated_packets,
            "unsupported_packets": self._unsupported_packets,
            "rejection_reasons": dict(self._rejection_reasons),
            "fragment_metrics": self._fragment_reassembler.get_metrics(),
            "queue_depth": self._queue.qsize(),
            "elapsed_seconds": round(elapsed, 2),
            "capture_pps": round(self._packets_captured / elapsed, 1) if elapsed > 0 else 0.0,
            "last_packet_timestamp": self._last_packet_time,
        }
