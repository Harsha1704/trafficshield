#!/usr/bin/env python3
"""
TrafficShield UGR'16 Data Preparation Tool
===========================================
Prepares raw UGR'16 CSV files into verified interim format.

Reads raw UGR'16 CSV files, validates rows through UGR16Adapter,
filters or audits malformed records, and outputs clean interim CSV files
along with a provenance manifest.

Usage:
    python scripts/prepare_ugr16.py \\
        --src datasets/raw/ugr16 \\
        --dest datasets/interim/ugr16 \\
        --month 2016-03

    # Fast validation / sampling with max rows:
    python scripts/prepare_ugr16.py \\
        --src datasets/raw/ugr16/ugr16_sample.csv \\
        --dest datasets/interim/ugr16 \\
        --max-rows 1000
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ingestion.adapters.ugr16 import UGR16_COLUMNS, UGR16Adapter, UGR16ValidationError  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("prepare_ugr16")


def compute_sha256(filepath: Path, chunk_size: int = 65536) -> str:
    """Compute SHA-256 checksum of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def find_source_file(src_path: Path, month: str | None = None) -> Path:
    """Resolve the source file from directory or file path."""
    if not src_path.exists():
        raise FileNotFoundError(f"Source path does not exist: {src_path}")

    if src_path.is_file():
        return src_path

    # If it is a directory, search for candidates
    patterns = []
    if month:
        clean_month = month.replace("-", "")
        patterns.extend([
            f"*{clean_month}*.csv*",
            f"*{month}*.csv*",
        ])
    patterns.extend(["*.csv.gz", "*.csv"])

    for pat in patterns:
        matches = sorted(src_path.glob(pat))
        # Exclude partial download files
        valid_matches = [m for m in matches if not m.name.endswith(".part")]
        if valid_matches:
            return valid_matches[0]

    raise FileNotFoundError(
        f"No valid CSV or CSV.GZ files found in {src_path} (filter month: {month})"
    )


def prepare_file(
    src_file: Path,
    dest_dir: Path,
    chunk_size: int = 10000,
    max_rows: int | None = None,
    compress_output: bool = True,
) -> Path:
    """Process a raw UGR'16 file through UGR16Adapter and write clean interim data."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    adapter = UGR16Adapter(chunk_size=chunk_size, skip_invalid_rows=True)

    base_name = src_file.name
    for ext in (".csv.gz", ".csv", ".gz"):
        if base_name.endswith(ext):
            base_name = base_name[:-len(ext)]
            break

    out_ext = ".csv.gz" if compress_output else ".csv"
    out_file = dest_dir / f"{base_name}_clean{out_ext}"
    part_file = dest_dir / f"{base_name}_clean{out_ext}.tmp"

    logger.info("Preparing: %s -> %s", src_file, out_file)

    open_fn = gzip.open if compress_output else open
    rows_written = 0
    rows_read = 0
    rows_rejected = 0
    rejection_reasons: dict[str, int] = {}

    with open_fn(part_file, "wt", encoding="utf-8", newline="") as out_fh:
        writer = csv.writer(out_fh)
        # Write standard UGR'16 header
        writer.writerow(UGR16_COLUMNS)

        for flow, rejection in adapter.iter_records(src_file):
            rows_read += 1
            if flow is not None:
                # Format back as verified clean UGR'16 CSV row
                row_values = [
                    flow.flow_end_ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                    f"{flow.duration_seconds:.3f}" if flow.duration_seconds is not None else "",
                    flow.src_ip,
                    flow.dst_ip,
                    str(flow.src_port) if flow.src_port is not None else "",
                    str(flow.dst_port) if flow.dst_port is not None else "",
                    flow.protocol_name,
                    flow.tcp_flags_raw or "",
                    str(flow.fwd_status) if flow.fwd_status is not None else "",
                    str(flow.ip_tos) if flow.ip_tos is not None else "",
                    str(flow.fwd_packets),
                    str(flow.fwd_bytes),
                    flow.eval_label or "",
                ]
                writer.writerow(row_values)
                rows_written += 1
            else:
                rows_rejected += 1
                reason = rejection or "unknown"
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1

            if max_rows and rows_read >= max_rows:
                logger.info("Reached requested --max-rows limit (%d). Stopping.", max_rows)
                break

    # Atomically finalize file
    part_file.replace(out_file)
    logger.info(
        "Preparation finished: read=%d, written=%d, rejected=%d",
        rows_read, rows_written, rows_rejected,
    )
    if rejection_reasons:
        logger.info("Rejection breakdown: %s", rejection_reasons)

    # Compute checksum of interim file
    sha256 = compute_sha256(out_file)
    actual_size = out_file.stat().st_size

    # Write manifest
    manifest_data = {
        "dataset": "ugr16",
        "retrieved_at": datetime.now(UTC).isoformat(),
        "destination": str(dest_dir.resolve()),
        "files": [
            {
                "filename": out_file.name,
                "source_file": str(src_file.resolve()),
                "size_bytes": actual_size,
                "sha256": sha256,
                "rows_read": rows_read,
                "rows_accepted": rows_written,
                "rows_rejected": rows_rejected,
                "rejection_reasons": rejection_reasons,
            }
        ],
        "extra": {
            "source_raw": str(src_file.resolve()),
            "completed_at": datetime.now(UTC).isoformat(),
        },
    }
    manifest_path = dest_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
    logger.info("Manifest written to %s", manifest_path)

    return out_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="TrafficShield UGR'16 data preparation tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--src", required=True, help="Source file or directory containing raw UGR'16 data")
    parser.add_argument("--dest", required=True, help="Destination directory for clean interim data")
    parser.add_argument("--month", help="Month filter (e.g. 2016-03)")
    parser.add_argument("--max-rows", type=int, help="Optional max rows to process (for sampling/tests)")
    parser.add_argument("--chunk-size", type=int, default=10000, help="Chunk size for streaming")
    parser.add_argument("--no-compress", action="store_true", help="Output plain uncompressed CSV")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    src_path = Path(args.src)
    dest_path = Path(args.dest)

    try:
        target_src = find_source_file(src_path, args.month)
    except FileNotFoundError as exc:
        logger.error(str(exc))
        sys.exit(1)

    try:
        prepare_file(
            src_file=target_src,
            dest_dir=dest_path,
            chunk_size=args.chunk_size,
            max_rows=args.max_rows,
            compress_output=not args.no_compress,
        )
    except UGR16ValidationError as exc:
        logger.error("Validation error: %s", exc)
        sys.exit(1)
    except Exception as exc:
        logger.exception("Unexpected preparation error: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
