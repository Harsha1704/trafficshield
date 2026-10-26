"""
System & Process Resource Monitor for Soak Qualification
=========================================================
Milestone 17 — Sustained-Soak Qualification & Resource Monitoring

Collects periodic process-level resource telemetry:
- Working Set / RSS Memory (MB)
- Peak Working Set / Peak RSS Memory (MB)
- Private Byte Allocation (MB)
- Process CPU Utilization (%) over the sampling interval
- Active Python Thread Count

Designed for Windows 10/11 using native Windows PSAPI (ctypes) with zero external
dependencies, while maintaining transparent fallback for psutil on POSIX platforms.
"""
from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("resource_monitor")

# Windows API types and structures for psapi.dll
if sys.platform == "win32":
    from ctypes import wintypes

    class _PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):  # noqa: N801
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]


@dataclass(frozen=True)
class ResourceSnapshot:
    """Timestamped snapshot of process hardware resource consumption."""
    timestamp: float
    elapsed_seconds: float
    rss_mb: float | None
    peak_rss_mb: float | None
    private_mb: float | None
    cpu_percent: float | None
    active_threads: int
    measurement_source: str
    is_available: bool = True
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": round(self.timestamp, 3),
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "rss_mb": round(self.rss_mb, 2) if self.rss_mb is not None else None,
            "peak_rss_mb": round(self.peak_rss_mb, 2) if self.peak_rss_mb is not None else None,
            "private_mb": round(self.private_mb, 2) if self.private_mb is not None else None,
            "cpu_percent": round(self.cpu_percent, 1) if self.cpu_percent is not None else None,
            "active_threads": self.active_threads,
            "measurement_source": self.measurement_source,
            "is_available": self.is_available,
            "error_message": self.error_message,
        }


class ResourceMonitor:
    """
    Non-intrusive process telemetry sampler.
    Maintains internal delta state to compute accurate CPU utilization across intervals.
    """

    def __init__(self) -> None:
        self.start_wall_time = time.perf_counter()
        self.prev_wall_time = self.start_wall_time
        self.prev_cpu_time = time.process_time()
        self.initial_rss_mb: float | None = None
        self.peak_observed_rss_mb = 0.0

        # Detect available measurement backend
        self._psutil_proc: Any = None
        self._win_psapi_available = False

        try:
            import os

            import psutil
            self._psutil_proc = psutil.Process(os.getpid())
            self.backend = "psutil"
        except ImportError:
            if sys.platform == "win32":
                try:
                    self._psapi = ctypes.windll.psapi
                    self._psapi.GetProcessMemoryInfo.argtypes = [
                        wintypes.HANDLE,
                        ctypes.c_void_p,
                        wintypes.DWORD,
                    ]
                    self._psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
                    self._kernel32 = ctypes.windll.kernel32
                    self._process_handle = self._kernel32.GetCurrentProcess()
                    self._win_psapi_available = True
                    self.backend = "windows_native_psapi"
                except Exception as exc:
                    logger.warning("Failed to initialize Windows PSAPI: %s", exc)
                    self.backend = "fallback_mock"
            else:
                self.backend = "posix_generic"

        # Prime initial measurement
        initial = self.sample()
        self.initial_rss_mb = initial.rss_mb

    def sample(self) -> ResourceSnapshot:
        """
        Record and return an instantaneous resource consumption snapshot.
        Gracefully handles API errors by returning safe sentinel metrics.
        """
        now_wall = time.perf_counter()
        now_cpu = time.process_time()
        elapsed = now_wall - self.start_wall_time

        # Calculate CPU utilization over the interval: (delta CPU time / delta wall time) * 100
        delta_wall = max(1e-6, now_wall - self.prev_wall_time)
        delta_cpu = max(0.0, now_cpu - self.prev_cpu_time)
        cpu_pct = (delta_cpu / delta_wall) * 100.0

        self.prev_wall_time = now_wall
        self.prev_cpu_time = now_cpu

        rss_mb: float | None = None
        peak_rss_mb: float | None = None
        private_mb: float | None = None
        threads_count = threading.active_count()
        source = self.backend
        is_avail = True
        err_msg: str | None = None

        try:
            if self.backend == "psutil" and self._psutil_proc is not None:
                mem = self._psutil_proc.memory_info()
                rss_mb = mem.rss / (1024 * 1024)
                peak_rss_mb = getattr(mem, "peak_wset", mem.rss) / (1024 * 1024)
                private_mb = getattr(mem, "private", 0) / (1024 * 1024)
            elif self.backend == "windows_native_psapi" and self._win_psapi_available:
                counters = _PROCESS_MEMORY_COUNTERS_EX()
                counters.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS_EX)
                ok = self._psapi.GetProcessMemoryInfo(
                    self._process_handle,
                    ctypes.byref(counters),
                    counters.cb,
                )
                if ok:
                    rss_mb = counters.WorkingSetSize / (1024 * 1024)
                    peak_rss_mb = counters.PeakWorkingSetSize / (1024 * 1024)
                    private_mb = counters.PrivateUsage / (1024 * 1024)
                else:
                    source = "windows_psapi_query_failed"
                    is_avail = False
                    err_msg = "GetProcessMemoryInfo returned non-zero error"
            else:
                source = "standard_library_basic"
                # Standard library without psutil/win32 cannot read working set directly
                is_avail = False
                err_msg = "No direct memory sampling backend available (psutil or psapi required)"
        except Exception as exc:
            logger.warning("Resource sampling error: %s", exc)
            source = f"error: {exc}"
            is_avail = False
            err_msg = str(exc)

        if rss_mb is not None and rss_mb > self.peak_observed_rss_mb:
            self.peak_observed_rss_mb = rss_mb

        final_peak = max(peak_rss_mb, self.peak_observed_rss_mb) if peak_rss_mb is not None else None

        return ResourceSnapshot(
            timestamp=time.time(),
            elapsed_seconds=elapsed,
            rss_mb=rss_mb,
            peak_rss_mb=final_peak,
            private_mb=private_mb,
            cpu_percent=cpu_pct,
            active_threads=threads_count,
            measurement_source=source,
            is_available=is_avail,
            error_message=err_msg,
        )
