#!/usr/bin/env python3
"""
Validate a dataset manifest JSON file.

Usage:
    python scripts/check_manifest.py datasets/interim/ugr16/manifest.json
"""
from __future__ import annotations

import hashlib
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("check_manifest")

REQUIRED_MANIFEST_KEYS = {"dataset", "retrieved_at", "destination", "files"}
REQUIRED_FILE_KEYS = {"filename", "size_bytes", "sha256"}


def compute_sha256(filepath: Path, chunk_size: int = 65536) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def validate_manifest(manifest_path: Path) -> bool:
    if not manifest_path.exists():
        logger.error("Manifest not found: %s", manifest_path)
        return False

    with open(manifest_path) as f:
        manifest = json.load(f)

    missing_keys = REQUIRED_MANIFEST_KEYS - set(manifest.keys())
    if missing_keys:
        logger.error("Manifest missing required keys: %s", missing_keys)
        return False

    logger.info("Dataset: %s", manifest.get("dataset"))
    logger.info("Retrieved at: %s", manifest.get("retrieved_at"))
    logger.info("Destination: %s", manifest.get("destination"))

    all_ok = True
    base_dir = manifest_path.parent

    for file_entry in manifest.get("files", []):
        missing = REQUIRED_FILE_KEYS - set(file_entry.keys())
        if missing:
            logger.error("File entry missing keys %s: %s", missing, file_entry)
            all_ok = False
            continue

        filepath = base_dir / file_entry["filename"]
        if not filepath.exists():
            logger.error("File not found: %s", filepath)
            all_ok = False
            continue

        actual_size = filepath.stat().st_size
        expected_size = file_entry["size_bytes"]
        if actual_size != expected_size:
            logger.error(
                "Size mismatch for %s: expected %d, got %d",
                filepath.name, expected_size, actual_size,
            )
            all_ok = False
        else:
            logger.info("Size OK: %s (%d bytes)", filepath.name, actual_size)

        logger.info("Computing SHA-256 for %s...", filepath.name)
        actual_sha256 = compute_sha256(filepath)
        expected_sha256 = file_entry["sha256"]
        if actual_sha256 != expected_sha256:
            logger.error(
                "SHA-256 MISMATCH for %s!\n  Expected: %s\n  Got:      %s",
                filepath.name, expected_sha256, actual_sha256,
            )
            all_ok = False
        else:
            logger.info("SHA-256 OK: %s", filepath.name)

    if all_ok:
        logger.info("All manifest checks PASSED.")
    else:
        logger.error("One or more manifest checks FAILED.")

    return all_ok


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/check_manifest.py <manifest.json>")
        sys.exit(1)

    manifest_path = Path(sys.argv[1])
    ok = validate_manifest(manifest_path)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
