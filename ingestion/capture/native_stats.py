"""
Native Npcap / libpcap Kernel-Drop & Packet Statistics Adapter
=============================================================
Milestone 18 — Memory Policy Review, Native Npcap Statistics & Git Push

Queries low-level kernel driver packet capture statistics via `pcap_stats()`:
- `ps_recv`: Total packets received by the packet capture filter/driver since capture start.
- `ps_drop`: Packets dropped by the kernel driver due to buffer exhaustion.
- `ps_ifdrop`: Packets dropped by the network interface adapter before reaching the driver.

Non-negotiable invariants:
1. Never substitute zero for an unavailable counter. If stats cannot be obtained,
   `is_available` is False and values remain `None`.
2. Clearly distinguish cumulative counters from interval deltas.
3. Keep native driver kernel drops completely separate from application queue drops
   (`packets_dropped` in ingestion queue, `flows_queue_dropped` in flow queue).
4. Do not leak raw memory pointers, device descriptors, or unmanaged ctypes handles.
"""
from __future__ import annotations

import ctypes
import logging
import platform
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger("native_stats")


@dataclass(frozen=True)
class NativeCaptureStats:
    """
    Structured snapshot of native kernel driver packet capture statistics.
    """
    is_available: bool
    status: str  # "AVAILABLE", "UNAVAILABLE", "UNSUPPORTED_SOURCE", "DRIVER_ERROR", "HANDLE_CLOSED"
    ps_recv_cumulative: int | None = None
    ps_drop_cumulative: int | None = None
    ps_ifdrop_cumulative: int | None = None
    ps_ifdrop_supported: bool = True
    ps_ifdrop_status: str = "AVAILABLE"
    ps_recv_delta: int | None = None
    ps_drop_delta: int | None = None
    ps_ifdrop_delta: int | None = None
    poll_timestamp: float | None = None
    poll_interval_seconds: float | None = None
    driver_name: str = "Npcap"
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert snapshot to dictionary for telemetry reporting."""
        return asdict(self)


# Type definition for raw stat query provider: (handle) -> (ps_recv, ps_drop, ps_ifdrop)
StatProviderCallable = Callable[[Any], tuple[int, int, int]]


class NativeStatsAdapter:
    """
    Thread-safe adapter for polling native kernel driver statistics.
    Tracks previous polling state to compute accurate interval deltas.
    """

    def __init__(
        self,
        driver_name: str = "Npcap",
        custom_provider: StatProviderCallable | None = None,
    ) -> None:
        self.driver_name = driver_name
        self._custom_provider = custom_provider
        self._lock = threading.Lock()

        # Cumulative state from last successful poll
        self._last_poll_time: float | None = None
        self._last_recv: int | None = None
        self._last_drop: int | None = None
        self._last_ifdrop: int | None = None

        # Detect native C library function if no custom provider is injected
        self._native_pcap_stats: Any = None
        self._pcap_stat_cls: Any = None
        if custom_provider is None:
            self._init_native_bindings()

    def _init_native_bindings(self) -> None:
        """Attempt to bind pcap_stats from Scapy's winpcapy or system library."""
        system = platform.system()
        try:
            if system == "Windows":
                from scapy.libs.winpcapy import pcap_stat, pcap_stats
                self._native_pcap_stats = pcap_stats
                self._pcap_stat_cls = pcap_stat
                self.driver_name = "Npcap/WinPcap"
            elif system in ("Linux", "Darwin"):
                # Load libpcap dynamically
                libpcap = ctypes.cdll.LoadLibrary("libpcap.so") or ctypes.cdll.LoadLibrary("libpcap.so.1")
                class _PcapStat(ctypes.Structure):
                    _fields_ = [
                        ("ps_recv", ctypes.c_uint),
                        ("ps_drop", ctypes.c_uint),
                        ("ps_ifdrop", ctypes.c_uint),
                    ]
                self._native_pcap_stats = libpcap.pcap_stats
                self._native_pcap_stats.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PcapStat)]
                self._native_pcap_stats.restype = ctypes.c_int
                self._pcap_stat_cls = _PcapStat
                self.driver_name = "libpcap"
        except Exception as exc:
            logger.debug("Native pcap_stats binding not initialized: %s", exc)
            self._native_pcap_stats = None
            self._pcap_stat_cls = None

    def poll(self, handle: Any = None) -> NativeCaptureStats:
        """
        Poll native kernel statistics for the given pcap handle.

        Args:
            handle: Active native capture handle (`pcap_t` pointer or wrapper object).

        Returns:
            NativeCaptureStats snapshot with cumulative and delta metrics.
        """
        with self._lock:
            now = time.time()

            # Handle missing or closed handle
            if handle is None:
                return NativeCaptureStats(
                    is_available=False,
                    status="UNAVAILABLE (No active capture handle)",
                    driver_name=self.driver_name,
                    error_message="Capture handle is None or uninitialized",
                    ps_ifdrop_supported=False,
                    ps_ifdrop_status="UNAVAILABLE (No active capture handle)",
                )

            ifdrop_supported = True
            ifdrop_status = "AVAILABLE"

            # Query raw counters
            try:
                if self._custom_provider is not None:
                    recv, drop, ifdrop_raw = self._custom_provider(handle)
                    ifdrop = ifdrop_raw
                elif self._native_pcap_stats is not None and self._pcap_stat_cls is not None:
                    stat_struct = self._pcap_stat_cls()
                    # Resolve handle to ctypes void pointer if wrapped in Scapy object
                    native_ptr = handle
                    if hasattr(native_ptr, "pcap_fd"):
                        native_ptr = native_ptr.pcap_fd
                    if hasattr(native_ptr, "pcap"):
                        native_ptr = native_ptr.pcap

                    res = self._native_pcap_stats(native_ptr, ctypes.byref(stat_struct))
                    if res != 0:
                        return NativeCaptureStats(
                            is_available=False,
                            status="DRIVER_QUERY_ERROR",
                            driver_name=self.driver_name,
                            error_message=f"pcap_stats() returned native error code {res}",
                            ps_ifdrop_supported=False,
                            ps_ifdrop_status="DRIVER_QUERY_ERROR",
                        )
                    recv = int(stat_struct.ps_recv)
                    drop = int(stat_struct.ps_drop)
                    if platform.system() == "Windows":
                        # On Windows, Npcap/WinPcap kernel driver does not support NIC/interface drops.
                        # The ps_ifdrop field is always returned as 0 by packet.sys / npcap.sys.
                        # Reporting 0 would falsely imply 0 drops occurred at the NIC level.
                        ifdrop_supported = False
                        ifdrop_status = "UNSUPPORTED (Npcap/WinPcap does not provide NIC drop counters on Windows)"
                        ifdrop = None
                    else:
                        ifdrop = int(stat_struct.ps_ifdrop)
                else:
                    return NativeCaptureStats(
                        is_available=False,
                        status="UNAVAILABLE (Native library not bound)",
                        driver_name=self.driver_name,
                        error_message="libpcap / Npcap C symbols unavailable in runtime environment",
                        ps_ifdrop_supported=False,
                        ps_ifdrop_status="UNAVAILABLE (Native library not bound)",
                    )
            except Exception as exc:
                logger.warning("Error invoking native pcap_stats: %s", exc)
                return NativeCaptureStats(
                    is_available=False,
                    status="DRIVER_EXCEPTION",
                    driver_name=self.driver_name,
                    error_message=str(exc),
                    ps_ifdrop_supported=False,
                    ps_ifdrop_status="DRIVER_EXCEPTION",
                )

            # Calculate interval deltas
            poll_interval: float | None = None
            if self._last_poll_time is not None:
                poll_interval = round(now - self._last_poll_time, 3)

            # Check for counter reset (e.g. driver buffer reinitialization)
            status = "AVAILABLE"
            if self._last_recv is not None and recv < self._last_recv:
                status = "AVAILABLE (Counter Reset Observed)"
                recv_delta = recv
                drop_delta = drop
                ifdrop_delta = ifdrop if ifdrop_supported else None
            elif self._last_recv is not None and self._last_drop is not None:
                recv_delta = max(0, recv - self._last_recv)
                drop_delta = max(0, drop - self._last_drop)
                if ifdrop_supported and ifdrop is not None and self._last_ifdrop is not None:
                    ifdrop_delta = max(0, ifdrop - self._last_ifdrop)
                else:
                    ifdrop_delta = None if not ifdrop_supported else ifdrop
            else:
                # First successful poll: interval delta equals cumulative
                recv_delta = recv
                drop_delta = drop
                ifdrop_delta = ifdrop if ifdrop_supported else None

            self._last_poll_time = now
            self._last_recv = recv
            self._last_drop = drop
            self._last_ifdrop = ifdrop if ifdrop_supported else None

            return NativeCaptureStats(
                is_available=True,
                status=status,
                ps_recv_cumulative=recv,
                ps_drop_cumulative=drop,
                ps_ifdrop_cumulative=ifdrop if ifdrop_supported else None,
                ps_ifdrop_supported=ifdrop_supported,
                ps_ifdrop_status=ifdrop_status,
                ps_recv_delta=recv_delta,
                ps_drop_delta=drop_delta,
                ps_ifdrop_delta=ifdrop_delta,
                poll_timestamp=now,
                poll_interval_seconds=poll_interval,
                driver_name=self.driver_name,
                error_message=None,
            )

    def reset(self) -> None:
        """Reset historical delta state."""
        with self._lock:
            self._last_poll_time = None
            self._last_recv = None
            self._last_drop = None
            self._last_ifdrop = None
