"""
Command-Line Interface for TrafficShield Soak Qualification Harness
====================================================================
Milestone 17 — Sustained-Soak Qualification & Resource Monitoring

Usage Examples:
    # Run 60-second offline PCAP replay soak test with 10s sampling
    python -m tools.soak.cli --mode PCAP_REPLAY --duration 60 --interval 10

    # Run passive live capture soak test (requires explicit authorization)
    python -m tools.soak.cli --mode LIVE_CAPTURE --target "Wi-Fi" --duration 7200 --interval 60
"""
# ruff: noqa: T201
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from tools.soak.soak_harness import SoakConfig, SoakTestHarness


def setup_cli_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main() -> int:
    setup_cli_logging()
    parser = argparse.ArgumentParser(
        description="TrafficShield Sustained-Soak Qualification Runner",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=60.0,
        help="Total soak test duration in seconds (default: 60.0)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=10.0,
        help="Periodic resource & pipeline sampling interval in seconds (default: 10.0)",
    )
    parser.add_argument(
        "--mode",
        choices=["PCAP_REPLAY", "LIVE_CAPTURE"],
        default="PCAP_REPLAY",
        help="Ingestion mode: PCAP_REPLAY (offline) or LIVE_CAPTURE (wire sniffing)",
    )
    parser.add_argument(
        "--target",
        type=str,
        default="data/captures/sample_traffic.pcap",
        help="PCAP filepath (for PCAP_REPLAY) or network interface name (for LIVE_CAPTURE)",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Replay speed multiplier (0.0 = max throughput, 1.0 = real-time pacing)",
    )
    parser.add_argument(
        "--bpf",
        type=str,
        default="ip",
        help="Berkeley Packet Filter string for LIVE_CAPTURE (default: 'ip')",
    )
    parser.add_argument(
        "--max-packets",
        type=int,
        default=None,
        help="Optional upper bound on packets to process",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports/m17_soak_qualification"),
        help="Directory to save JSON summaries and Markdown reports",
    )

    args = parser.parse_args()

    try:
        config = SoakConfig(
            duration_seconds=args.duration,
            sample_interval_seconds=args.interval,
            mode=args.mode,
            target=args.target,
            speed_multiplier=args.speed,
            bpf_filter=args.bpf,
            max_packets=args.max_packets,
            output_dir=args.output_dir,
        )
    except Exception as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    harness = SoakTestHarness(config)
    summary = harness.run()

    print("\n" + "=" * 70)
    print("TRAFFICSHIELD SOAK QUALIFICATION EXECUTION SUMMARY")
    print("=" * 70)
    print(f"Session ID:           {summary.session_id}")
    print(f"Mode:                 {summary.mode}")
    print(f"Target:               {summary.target}")
    print(f"Actual Duration:      {summary.duration_actual}s (configured: {summary.duration_configured}s)")
    print(f"Samples Recorded:     {summary.sample_count}")
    print(f"Shutdown Latency:     {summary.shutdown_duration_ms:.2f} ms")
    print(f"Baseline RSS Memory:  {summary.resource_baseline_rss_mb:.2f} MB")
    print(f"Peak RSS Memory:      {summary.resource_peak_rss_mb:.2f} MB")
    print(f"Peak CPU:             {summary.resource_max_cpu_pct:.1f}%")
    print(f"Model Hashes Verified:{summary.model_hashes_verified}")
    print("-" * 70)
    print("INVARIANT RESULTS:")
    for inv in summary.invariants:
        status = "PASS" if inv.passed else "FAIL"
        print(f"  [{status}] {inv.name}: Expected {inv.expected}, Actual {inv.actual}")
    print("-" * 70)
    print(f"OVERALL SOAK STATUS:  {'SUCCESS (PASS)' if summary.success else 'FAILED'}")
    print("=" * 70 + "\n")

    return 0 if summary.success else 1


if __name__ == "__main__":
    sys.exit(main())
