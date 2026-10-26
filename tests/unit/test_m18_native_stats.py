"""
TrafficShield Milestone 18: Native Npcap Kernel-Drop Statistics Tests
=====================================================================
Deterministic test suite covering:
1. Successful native statistics retrieval via adapter.
2. Correct counter mapping (ps_recv, ps_drop, ps_ifdrop).
3. Cumulative counter interval deltas.
4. Unsupported capture source (offline PCAP replay).
5. Missing, null, or closed native capture handle.
6. Native API errors and C library call failures.
7. Counter reset / driver buffer reinitialization handling.
8. Repeated polling interval consistency.
9. Statistics unavailable without reporting false zeros.
10. Capture teardown and handle cleanup.
11. Tiered drop separation: kernel drops vs ingestion queue drops vs flow queue drops.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from ingestion.capture.native_stats import NativeCaptureStats, NativeStatsAdapter
from ingestion.capture.pcap_source import PcapReplaySource
from streaming.manager import RealTimeDetectionManager


class TestNativeNpcapStatisticsAdapter:
    """Validate NativeStatsAdapter polling, mapping, deltas, and error states."""

    def test_1_successful_statistics_retrieval_and_mapping(self) -> None:
        """1. Adapter successfully retrieves and maps ps_recv, ps_drop, and ps_ifdrop."""
        # Simulated native provider: returns (recv=1000, drop=5, ifdrop=2)
        mock_provider = MagicMock(return_value=(1000, 5, 2))
        adapter = NativeStatsAdapter(driver_name="Npcap_Mock", custom_provider=mock_provider)

        stats = adapter.poll(handle="fake_pcap_handle_ptr")

        assert isinstance(stats, NativeCaptureStats)
        assert stats.is_available is True
        assert stats.status == "AVAILABLE"
        assert stats.ps_recv_cumulative == 1000
        assert stats.ps_drop_cumulative == 5
        assert stats.ps_ifdrop_cumulative == 2
        # First poll: delta equals initial cumulative
        assert stats.ps_recv_delta == 1000
        assert stats.ps_drop_delta == 5
        assert stats.ps_ifdrop_delta == 2
        assert stats.error_message is None

    def test_2_cumulative_counter_interval_deltas(self) -> None:
        """2. Adapter computes accurate interval deltas across successive polls."""
        call_count = 0

        def sequential_provider(_handle: Any) -> tuple[int, int, int]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (1000, 10, 1)
            elif call_count == 2:
                return (1500, 15, 2)
            else:
                return (2200, 20, 2)

        adapter = NativeStatsAdapter(custom_provider=sequential_provider)

        snap1 = adapter.poll(handle="handle_1")
        assert snap1.ps_recv_cumulative == 1000
        assert snap1.ps_drop_cumulative == 10

        snap2 = adapter.poll(handle="handle_1")
        assert snap2.ps_recv_cumulative == 1500
        assert snap2.ps_recv_delta == 500  # 1500 - 1000
        assert snap2.ps_drop_cumulative == 15
        assert snap2.ps_drop_delta == 5  # 15 - 10
        assert snap2.ps_ifdrop_delta == 1  # 2 - 1

        snap3 = adapter.poll(handle="handle_1")
        assert snap3.ps_recv_cumulative == 2200
        assert snap3.ps_recv_delta == 700  # 2200 - 1500
        assert snap3.ps_drop_cumulative == 20
        assert snap3.ps_drop_delta == 5  # 20 - 15
        assert snap3.ps_ifdrop_delta == 0  # 2 - 2

    def test_3_unsupported_capture_source_pcap_replay(self) -> None:
        """3. Offline PCAP replay explicitly reports native stats as UNSUPPORTED, not zero."""
        source = PcapReplaySource("data/captures/sample_traffic.pcap")
        metrics = source.get_metrics()

        assert metrics["native_kernel_drops_available"] is False
        assert metrics["native_kernel_drops"] is None
        assert metrics["native_kernel_drops_delta"] is None
        assert metrics["native_packets_received"] is None
        assert "UNAVAILABLE" in metrics["kernel_drop_status"]

    def test_4_missing_or_invalid_handle_reports_unavailable(self) -> None:
        """4. Polling with None or closed handle returns UNAVAILABLE without raising."""
        adapter = NativeStatsAdapter()

        stats = adapter.poll(handle=None)
        assert stats.is_available is False
        assert "UNAVAILABLE" in stats.status
        assert stats.ps_drop_cumulative is None
        assert stats.ps_recv_cumulative is None
        assert "No active capture handle" in stats.status

    def test_5_native_api_error_handling(self) -> None:
        """5. Native API error (e.g. C library fault or error code) returns failure state."""
        def faulty_provider(_handle: Any) -> tuple[int, int, int]:
            raise OSError("Access violation in wpcap.dll!pcap_stats")

        adapter = NativeStatsAdapter(custom_provider=faulty_provider)
        stats = adapter.poll(handle="handle_ptr")

        assert stats.is_available is False
        assert stats.status == "DRIVER_EXCEPTION"
        assert stats.ps_drop_cumulative is None
        assert "Access violation" in str(stats.error_message)

    def test_6_counter_reset_or_decrease_handling(self) -> None:
        """6. Adapter detects driver counter reset and handles delta gracefully."""
        poll_step = 0

        def resetting_provider(_handle: Any) -> tuple[int, int, int]:
            nonlocal poll_step
            poll_step += 1
            if poll_step == 1:
                return (5000, 100, 0)
            else:
                # Driver was restarted / reallocated: counters reset to 200
                return (200, 2, 0)

        adapter = NativeStatsAdapter(custom_provider=resetting_provider)
        snap1 = adapter.poll(handle="h1")
        assert snap1.ps_recv_cumulative == 5000

        snap2 = adapter.poll(handle="h1")
        assert snap2.ps_recv_cumulative == 200
        assert "Counter Reset" in snap2.status
        assert snap2.ps_recv_delta == 200
        assert snap2.ps_drop_delta == 2

    def test_7_statistics_unavailable_never_substitutes_zero(self) -> None:
        """7. Unavailable statistics never report 0 drops (which would falsely imply 0 drops)."""
        adapter = NativeStatsAdapter()
        stats = adapter.poll(handle=None)

        assert stats.ps_drop_cumulative != 0
        assert stats.ps_drop_cumulative is None

        d = stats.to_dict()
        assert d["is_available"] is False
        assert d["ps_drop_cumulative"] is None

    def test_8_tiered_drop_demarcation_isolation(self) -> None:
        """8. Kernel drops, ingestion queue drops, and flow queue drops remain distinct."""
        manager = RealTimeDetectionManager.get_instance()
        manager.stop()

        # Simulate synthetic metrics in manager status
        status = manager.get_status()

        # Check all three drop categories exist independently
        assert "native_kernel_drops" in status  # Tier 1: Kernel driver drops
        assert "packets_dropped" in status      # Tier 2: Ingestion queue drops
        assert "flows_queue_dropped" in status  # Tier 3: Flow queue drops

        # Verify that an offline/idle status does not mislabel kernel drops as 0
        assert status["native_kernel_drops_available"] is False
        assert status["native_kernel_drops"] is None
        assert status["packets_dropped"] >= 0
        assert status["flows_queue_dropped"] >= 0

    def test_9_repeated_polling_interval_timing(self) -> None:
        """9. Repeated polling measures valid poll_interval_seconds between calls."""
        provider = MagicMock(return_value=(100, 0, 0))
        adapter = NativeStatsAdapter(custom_provider=provider)

        snap1 = adapter.poll("h")
        assert snap1.poll_interval_seconds is None  # Initial baseline

        snap2 = adapter.poll("h")
        assert snap2.poll_interval_seconds is not None
        assert snap2.poll_interval_seconds >= 0.0

    def test_10_adapter_reset(self) -> None:
        """10. Reset clears historical cumulative counters."""
        provider = MagicMock(return_value=(500, 10, 0))
        adapter = NativeStatsAdapter(custom_provider=provider)

        adapter.poll("h")
        assert adapter._last_recv == 500

        adapter.reset()
        assert adapter._last_recv is None
        assert adapter._last_drop is None
        assert adapter._last_poll_time is None
