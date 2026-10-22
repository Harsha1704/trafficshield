"""
Reproducible Preprocessing Artifact Management
==============================================
Version: 1.0 (Milestone 3)

Provides secure, auditable serialization and deserialization of fitted
preprocessor pipelines with SHA-256 cryptographic provenance manifests.

Guarantees:
1. IMMUTABILITY & AUDITABILITY: Saved artifacts include a sidecar JSON manifest
   recording the feature policy version, input features, output columns,
   scaler configuration, timestamp, and SHA-256 checksum.
2. INTEGRITY VERIFICATION: Deserialization verifies the file checksum before loading
   to guard against corrupted or tampered artifacts.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib

from features.policy import FEATURE_POLICY_VERSION
from preprocessing.pipeline import TrafficShieldPreprocessor

logger = logging.getLogger(__name__)


def compute_sha256(filepath: Path, chunk_size: int = 65536) -> str:
    """Compute the SHA-256 cryptographic checksum of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def save_preprocessor(
    preprocessor: TrafficShieldPreprocessor,
    filepath: str | Path,
    metadata: dict[str, Any] | None = None,
) -> tuple[Path, Path]:
    """
    Serialize a fitted TrafficShieldPreprocessor and generate a sidecar JSON manifest.

    Parameters
    ----------
    preprocessor : fitted TrafficShieldPreprocessor
    filepath : destination path for the .joblib file
    metadata : optional additional metadata dictionary

    Returns
    -------
    (joblib_path, manifest_path)
    """
    if not isinstance(preprocessor, TrafficShieldPreprocessor):
        raise TypeError(f"Expected TrafficShieldPreprocessor, got {type(preprocessor)}")

    if not preprocessor.is_fitted_:
        raise ValueError("Cannot save an unfitted TrafficShieldPreprocessor.")

    target_path = Path(filepath).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Dump joblib artifact
    joblib.dump(preprocessor, target_path)

    # 2. Compute checksum
    sha256_hash = compute_sha256(target_path)
    file_size = target_path.stat().st_size

    # 3. Create companion metadata
    manifest_data: dict[str, Any] = {
        "format_version": "1.0",
        "feature_policy_version": FEATURE_POLICY_VERSION,
        "artifact_file": target_path.name,
        "size_bytes": file_size,
        "sha256": sha256_hash,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "scaler": preprocessor.scaler,
        "impute_strategy": preprocessor.impute_strategy,
        "feature_names_in": preprocessor.feature_names_in_,
        "feature_names_out": preprocessor.feature_names_out_,
        "numeric_features": preprocessor.numeric_features_,
        "categorical_features": preprocessor.categorical_features_,
        "boolean_features": preprocessor.boolean_features_,
        "extra_metadata": metadata or {},
    }

    manifest_path = target_path.with_suffix(".json")
    manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

    logger.info("Saved preprocessor to %s (SHA-256: %s)", target_path, sha256_hash)
    return target_path, manifest_path


def load_preprocessor(
    filepath: str | Path,
    verify_checksum: bool = True,
) -> tuple[TrafficShieldPreprocessor, dict[str, Any]]:
    """
    Load a serialized TrafficShieldPreprocessor and its companion manifest.

    Parameters
    ----------
    filepath : path to the .joblib artifact
    verify_checksum : if True, validates SHA-256 against companion .json manifest

    Returns
    -------
    (preprocessor, manifest_data)
    """
    target_path = Path(filepath).resolve()
    if not target_path.exists():
        raise FileNotFoundError(f"Preprocessor artifact not found at: {target_path}")

    manifest_path = target_path.with_suffix(".json")
    manifest_data: dict[str, Any] = {}

    if verify_checksum:
        if not manifest_path.exists():
            raise ValueError(
                f"Checksum verification failed: companion manifest not found for {target_path.name} "
                f"at {manifest_path}. Cannot verify artifact integrity without manifest."
            )
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(
                f"Failed to read companion manifest for {target_path.name}: {exc}"
            ) from exc

        if "sha256" not in manifest_data:
            raise ValueError(
                f"Checksum verification failed: 'sha256' field missing in manifest {manifest_path.name}."
            )

        actual_hash = compute_sha256(target_path)
        expected_hash = manifest_data["sha256"]
        if actual_hash != expected_hash:
            raise ValueError(
                f"Artifact integrity verification failed for {target_path.name}!\n"
                f"  Expected SHA-256: {expected_hash}\n"
                f"  Actual SHA-256:   {actual_hash}\n"
                "Artifact may be damaged or tampered."
            )
    else:
        if manifest_path.exists():
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))

    preprocessor = joblib.load(target_path)
    if not isinstance(preprocessor, TrafficShieldPreprocessor):
        raise TypeError(f"Loaded object is not a TrafficShieldPreprocessor: {type(preprocessor)}")

    return preprocessor, manifest_data
