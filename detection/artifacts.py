"""
Reproducible Detector Artifact Management
=========================================
Version: 1.0 (Milestone 4)

Provides secure serialization, provenance tracking, and integrity verification
for trained TrafficShield anomaly detectors.

Security Warning:
-----------------
Artifact integrity checks (SHA-256) verify that a file has not been altered
since it was created by the system. However, standard joblib/pickle formats
execute arbitrary Python code during deserialization. NEVER load detector
artifacts from untrusted, public, or unauthenticated sources.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import scipy
import sklearn

from detection.base import BaseDetector
from features.policy import FEATURE_POLICY_VERSION

logger = logging.getLogger(__name__)


def compute_sha256(filepath: Path, chunk_size: int = 65536) -> str:
    """Compute the SHA-256 cryptographic checksum of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def save_detector(
    detector: BaseDetector,
    filepath: str | Path,
    preprocessor_artifact_ref: str | None = None,
    threshold_config: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[Path, Path]:
    """
    Serialize a fitted detector and generate a companion JSON provenance manifest.

    Parameters
    ----------
    detector : fitted BaseDetector instance
    filepath : destination path for the .joblib artifact
    preprocessor_artifact_ref : optional reference/path to compatible preprocessor artifact
    threshold_config : optional dictionary detailing threshold provenance
    metadata : optional additional metadata

    Returns
    -------
    (joblib_path, manifest_path)
    """
    if not isinstance(detector, BaseDetector):
        raise TypeError(f"Expected BaseDetector, got {type(detector)}")

    if not detector.is_fitted_:
        raise ValueError("Cannot save an unfitted detector.")

    target_path = Path(filepath).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Dump joblib artifact
    joblib.dump(detector, target_path)

    # 2. Checksum and size
    sha256_hash = compute_sha256(target_path)
    file_size = target_path.stat().st_size

    # 3. Create companion metadata
    manifest_data: dict[str, Any] = {
        "format_version": "1.0",
        "detector_type": detector.__class__.__name__,
        "feature_policy_version": FEATURE_POLICY_VERSION,
        "artifact_file": target_path.name,
        "size_bytes": file_size,
        "sha256": sha256_hash,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "feature_names_in": detector.feature_names_in_,
        "n_features_in": detector.n_features_in_,
        "threshold": detector.threshold_,
        "threshold_config": threshold_config or {},
        "preprocessor_artifact_ref": preprocessor_artifact_ref,
        "parameters": detector.get_params(),
        "library_versions": {
            "sklearn": sklearn.__version__,
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "joblib": joblib.__version__,
        },
        "extra_metadata": metadata or {},
    }

    manifest_path = target_path.with_suffix(".json")
    manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

    logger.info("Saved detector to %s (SHA-256: %s)", target_path, sha256_hash)
    return target_path, manifest_path


def load_detector(
    filepath: str | Path,
    verify_checksum: bool = True,
) -> tuple[BaseDetector, dict[str, Any]]:
    """
    Load a serialized detector and its companion manifest.

    Parameters
    ----------
    filepath : path to the .joblib artifact
    verify_checksum : if True, validates SHA-256 against companion .json manifest

    Returns
    -------
    (detector, manifest_data)
    """
    target_path = Path(filepath).resolve()
    if not target_path.exists():
        raise FileNotFoundError(f"Detector artifact not found at: {target_path}")

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
                f"Detector artifact integrity check failed for {target_path.name}!\n"
                f"  Expected SHA-256: {expected_hash}\n"
                f"  Actual SHA-256:   {actual_hash}\n"
                "File may have been corrupted or tampered."
            )
    else:
        if manifest_path.exists():
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))

    detector = joblib.load(target_path)
    if not isinstance(detector, BaseDetector):
        raise TypeError(f"Loaded object is not a BaseDetector: {type(detector)}")

    return detector, manifest_data
