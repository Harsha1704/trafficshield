#!/usr/bin/env python3
"""
TrafficShield Dataset Acquisition Script
=========================================
Safe, explicit, auditable dataset download tool.

IMPORTANT: This script does NOT download anything automatically.
You must invoke it explicitly with the correct arguments.

Usage:
    python scripts/acquire_dataset.py info ugr16

    python scripts/acquire_dataset.py download ugr16 \\
        --dest datasets/raw/ugr16 \\
        --month 2016-03 \\
        --username YOUR_UGR16_USERNAME \\
        --password-env NESG_PASSWORD

    python scripts/acquire_dataset.py download cicids2017 \\
        --dest datasets/raw/cicids2017

    python scripts/acquire_dataset.py download unswnb15 \\
        --dest datasets/raw/unswnb15

Requirements:
    requests, tqdm (listed in requirements.txt)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("acquire_dataset")

# ─── Dataset registry ─────────────────────────────────────────────────────────
DATASET_REGISTRY: dict[str, dict] = {
    "ugr16": {
        "name": "UGR'16",
        "full_name": "UGR'16 — A New Dataset for the Evaluation of Cyclostationarity-Based Network IDSs",
        "official_page": "https://nesg.ugr.es/nesg-ugr16/index.php",
        "paper": "Maciá-Fernández et al., Computer Networks, Elsevier, 2018",
        "license": "Academic/research use. Contact nesg@ugr.es for access.",
        "format": "nfcapd binary or preprocessed CSV (nfdump export)",
        "auth_required": True,
        "base_url": "https://nesg.ugr.es/nesg-ugr16/",
        "approx_size_csv_per_month_gb": 2.0,
        "approx_size_total_gb": 341.0,
        "notes": (
            "IPs anonymized with CryptoPan. "
            "Training period: March-June 2016 (background only). "
            "Test period: July-August 2016 (background + attacks)."
        ),
        "available_months": [
            "2016-03", "2016-04", "2016-05", "2016-06",
            "2016-07", "2016-08",
        ],
        "checksums": {},  # Published per-release; provide via --expected-checksum
    },
    "cicids2017": {
        "name": "CICIDS2017",
        "full_name": "CICIDS2017 — Canadian Institute for Cybersecurity IDS 2017",
        "official_page": "https://www.unb.ca/cic/datasets/ids-2017.html",
        "paper": "Sharafaldin et al., ICISSP 2018",
        "license": "Academic use. Attribution required.",
        "format": "CSV (CICFlowMeter bidirectional flow features)",
        "auth_required": False,
        "base_url": "https://www.unb.ca/cic/datasets/ids-2017.html",
        "approx_size_csv_per_month_gb": 0.15,
        "approx_size_total_gb": 0.9,
        "notes": (
            "Contains bidirectional flow features. "
            "TrafficShield filters out reverse-direction columns before model input."
        ),
        "checksums": {},
    },
    "unswnb15": {
        "name": "UNSW-NB15",
        "full_name": "UNSW-NB15 Network Intrusion Dataset",
        "official_page": "https://research.unsw.edu.au/projects/unsw-nb15-dataset",
        "paper": "Moustafa & Slay, MilCIS 2015",
        "license": "Academic use.",
        "format": "CSV (ARGUS tool output + manual features)",
        "auth_required": False,
        "base_url": "https://research.unsw.edu.au/projects/unsw-nb15-dataset",
        "approx_size_total_gb": 0.1,
        "notes": "9 attack categories. Features derived from pcap files.",
        "checksums": {},
    },
}


def compute_sha256(filepath: Path, chunk_size: int = 65536) -> str:
    """Compute SHA-256 checksum of a file without loading it entirely into memory."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(
    dest_dir: Path,
    dataset_name: str,
    files: list[dict],
    extra_meta: dict | None = None,
) -> Path:
    """Write a JSON manifest recording provenance for downloaded files."""
    manifest = {
        "dataset": dataset_name,
        "registry_entry": DATASET_REGISTRY.get(dataset_name, {}),
        "retrieved_at": datetime.now(UTC).isoformat(),
        "destination": str(dest_dir.resolve()),
        "files": files,
        "extra": extra_meta or {},
    }
    manifest_path = dest_dir / "manifest.json"
    if manifest_path.exists():
        logger.warning("Manifest already exists at %s — updating", manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    logger.info("Manifest written to %s", manifest_path)
    return manifest_path


def print_dataset_info(name: str) -> None:
    """Print dataset information and storage requirements without downloading."""
    entry = DATASET_REGISTRY.get(name)
    if not entry:
        logger.error("Unknown dataset: %s. Available: %s", name, list(DATASET_REGISTRY))
        sys.exit(1)
    print(f"\n{'='*60}")
    print(f"Dataset:  {entry['full_name']}")
    print(f"Page:     {entry['official_page']}")
    print(f"License:  {entry['license']}")
    print(f"Format:   {entry['format']}")
    print(f"Auth:     {'Required' if entry.get('auth_required') else 'Not required'}")
    if "approx_size_total_gb" in entry:
        print(f"Size:     ~{entry['approx_size_total_gb']} GB total")
    if "notes" in entry:
        print(f"Notes:    {entry['notes']}")
    print(f"{'='*60}\n")


def cmd_info(args: argparse.Namespace) -> None:
    """Print dataset info — safe, no download."""
    print_dataset_info(args.dataset)


def cmd_download(args: argparse.Namespace) -> None:
    """Attempt dataset download with resume and safe checksum verification."""
    entry = DATASET_REGISTRY.get(args.dataset)
    if not entry:
        logger.error("Unknown dataset: %s", args.dataset)
        sys.exit(1)

    print_dataset_info(args.dataset)

    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)

    try:
        import requests
        from tqdm import tqdm  # noqa: F401
    except ImportError:
        logger.error(
            "Download requires 'requests' and 'tqdm'. "
            "Install with: pip install requests tqdm"
        )
        sys.exit(1)

    auth = None
    if entry.get("auth_required"):
        username = args.username
        if not username:
            logger.error("Dataset %s requires --username", args.dataset)
            sys.exit(1)
        password_env = getattr(args, "password_env", "NESG_PASSWORD")
        password = os.environ.get(password_env, "")
        if not password:
            logger.error(
                "Password not found in environment variable %s. "
                "Set it with: set %s=yourpassword",
                password_env, password_env,
            )
            sys.exit(1)
        auth = (username, password)

    if args.dataset == "ugr16":
        _download_ugr16(args, entry, dest, auth, requests)
    else:
        logger.error(
            "Download for '%s' is not automated in this script. "
            "Visit %s and download manually, then use 'manifest' subcommand to record.",
            args.dataset, entry["official_page"],
        )
        sys.exit(1)


def _download_ugr16(
    args: argparse.Namespace,
    entry: dict,
    dest: Path,
    auth: tuple | None,
    requests_module,
) -> None:
    """Download one UGR'16 month CSV from the NESG server with resume support."""
    from tqdm import tqdm

    month = getattr(args, "month", None)
    if not month:
        logger.error("UGR'16 download requires --month (e.g. --month 2016-03)")
        sys.exit(1)
    if month not in entry["available_months"]:
        logger.error(
            "Month %s not in available months: %s",
            month, entry["available_months"],
        )
        sys.exit(1)

    year_month = month.replace("-", "")
    url = f"{entry['base_url']}data/{year_month}/ugr16_{year_month}.csv.gz"

    out_file = dest / f"ugr16_{year_month}.csv.gz"
    part_file = dest / f"ugr16_{year_month}.csv.gz.part"

    if out_file.exists():
        if not args.force:
            logger.info("File %s already exists. Use --force to overwrite.", out_file)
            return
        logger.warning("Overwriting existing %s due to --force", out_file)
        out_file.unlink()

    if args.force and part_file.exists():
        part_file.unlink()

    # Resume support
    existing_bytes = 0
    headers = {}
    if part_file.exists() and not getattr(args, "no_resume", False):
        existing_bytes = part_file.stat().st_size
        if existing_bytes > 0:
            headers["Range"] = f"bytes={existing_bytes}-"
            logger.info("Found partial download (%d bytes). Attempting to resume...", existing_bytes)

    logger.info("Attempting download: %s -> %s", url, part_file)
    try:
        resp = requests_module.get(url, auth=auth, headers=headers, stream=True, timeout=30)
        if resp.status_code == 416:  # Range not satisfiable
            logger.warning("Server rejected byte range; restarting from beginning")
            part_file.unlink(missing_ok=True)
            existing_bytes = 0
            headers.pop("Range", None)
            resp = requests_module.get(url, auth=auth, stream=True, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        logger.error("Download failed: %s", exc)
        logger.info("Partial download preserved at %s (if any).", part_file)
        sys.exit(1)

    is_resumed = (resp.status_code == 206)
    write_mode = "ab" if is_resumed else "wb"
    total_len = int(resp.headers.get("content-length", 0))
    if is_resumed:
        total_len += existing_bytes

    try:
        with open(part_file, write_mode) as f, tqdm(
            total=total_len,
            initial=existing_bytes if is_resumed else 0,
            unit="B",
            unit_scale=True,
            desc=out_file.name,
        ) as bar:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    bar.update(len(chunk))
    except (KeyboardInterrupt, Exception) as exc:
        logger.warning("Download interrupted: %s. Partial file retained at %s", exc, part_file)
        sys.exit(1)

    # ── Checksum verification ─────────────────────────────────────────────────
    actual_size = part_file.stat().st_size
    sha256 = compute_sha256(part_file)
    logger.info("Downloaded %s bytes, SHA-256: %s", actual_size, sha256)

    expected_checksum = getattr(args, "expected_checksum", None) or entry["checksums"].get(month)
    if expected_checksum:
        if sha256.lower() != expected_checksum.lower():
            logger.error(
                "CHECKSUM MISMATCH for %s! Expected: %s, Got: %s. "
                "Partial file left at %s for review.",
                part_file.name, expected_checksum, sha256, part_file,
            )
            sys.exit(1)
        logger.info("Checksum verified successfully.")
    elif getattr(args, "verify_checksum", False):
        logger.warning("No expected checksum configured or supplied for %s.", month)

    # Atomically move .part to destination file
    part_file.replace(out_file)
    logger.info("Download completed successfully: %s", out_file)

    # Write manifest
    write_manifest(
        dest_dir=dest,
        dataset_name="ugr16",
        files=[
            {
                "filename": out_file.name,
                "url": url,
                "size_bytes": actual_size,
                "sha256": sha256,
                "month": month,
            }
        ],
        extra_meta={"month": month},
    )


def cmd_manifest(args: argparse.Namespace) -> None:
    """Record a manually-downloaded file into a manifest."""
    filepath = Path(args.file)
    if not filepath.exists():
        logger.error("File not found: %s", filepath)
        sys.exit(1)

    dest = filepath.parent
    size = filepath.stat().st_size
    logger.info("Computing SHA-256 for %s (%d bytes)...", filepath, size)
    sha256 = compute_sha256(filepath)
    logger.info("SHA-256: %s", sha256)

    write_manifest(
        dest_dir=dest,
        dataset_name=args.dataset,
        files=[
            {
                "filename": filepath.name,
                "source": args.source or "manual",
                "size_bytes": size,
                "sha256": sha256,
            }
        ],
    )


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(
        description="TrafficShield safe dataset acquisition tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # ── info ──────────────────────────────────────────────────────────────────
    p_info = sub.add_parser("info", help="Print dataset info without downloading")
    p_info.add_argument("dataset", choices=list(DATASET_REGISTRY))
    p_info.set_defaults(func=cmd_info)

    # ── download ──────────────────────────────────────────────────────────────
    p_dl = sub.add_parser("download", help="Download a dataset (explicit, not automatic)")
    p_dl.add_argument("dataset", choices=list(DATASET_REGISTRY))
    p_dl.add_argument("--dest", required=True, help="Destination directory")
    p_dl.add_argument("--month", help="Month to download (UGR'16 only), e.g. 2016-03")
    p_dl.add_argument("--username", help="Username (if auth required)")
    p_dl.add_argument("--password-env", default="NESG_PASSWORD",
                      dest="password_env", help="Env var containing password")
    p_dl.add_argument("--force", action="store_true", help="Overwrite existing files")
    p_dl.add_argument("--no-resume", action="store_true", dest="no_resume",
                      help="Do not attempt to resume partial download")
    p_dl.add_argument("--verify-checksum", action="store_true",
                      dest="verify_checksum", help="Verify checksum after download")
    p_dl.add_argument("--expected-checksum", dest="expected_checksum",
                      help="Expected SHA-256 checksum to verify against")
    p_dl.set_defaults(func=cmd_download)

    # ── manifest ──────────────────────────────────────────────────────────────
    p_mf = sub.add_parser("manifest", help="Record a manually-downloaded file")
    p_mf.add_argument("dataset", choices=list(DATASET_REGISTRY))
    p_mf.add_argument("--file", required=True, help="Path to downloaded file")
    p_mf.add_argument("--source", help="Source URL or description")
    p_mf.set_defaults(func=cmd_manifest)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
