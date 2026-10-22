"""
Unit Tests for Preprocessing Artifact Management
=================================================
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from preprocessing.artifacts import load_preprocessor, save_preprocessor
from preprocessing.pipeline import TrafficShieldPreprocessor


@pytest.fixture
def fitted_preprocessor():
    df = pd.DataFrame({
        "fwd_packets": [10.0, 20.0, 30.0],
        "fwd_bytes": [1000.0, 2000.0, 3000.0],
        "duration_seconds": [1.0, 2.0, 3.0],
        "protocol_category": ["TCP", "UDP", "TCP"],
        "dst_port_category": ["well_known", "registered", "ephemeral"],
        "is_well_known_dst_port": [1, 0, 0],
    })
    prep = TrafficShieldPreprocessor(scaler="standard")
    prep.fit(df)
    return prep, df


def test_save_and_load_roundtrip(fitted_preprocessor, tmp_path: Path):
    prep, df = fitted_preprocessor
    artifact_path = tmp_path / "models" / "preprocessor.joblib"

    joblib_path, json_path = save_preprocessor(
        prep,
        artifact_path,
        metadata={"experiment": "exp-001", "author": "TrafficShield"},
    )

    assert joblib_path.exists()
    assert json_path.exists()

    loaded_prep, manifest = load_preprocessor(joblib_path, verify_checksum=True)

    assert manifest["format_version"] == "1.0"
    assert manifest["extra_metadata"]["experiment"] == "exp-001"
    assert "sha256" in manifest

    # Transform outputs must match exactly
    orig_output = prep.transform(df)
    loaded_output = loaded_prep.transform(df)
    np.testing.assert_allclose(orig_output, loaded_output, atol=1e-7)


def test_checksum_mismatch_detection(fitted_preprocessor, tmp_path: Path):
    prep, _ = fitted_preprocessor
    artifact_path = tmp_path / "preprocessor.joblib"
    joblib_path, json_path = save_preprocessor(prep, artifact_path)

    # Tamper with the joblib binary file by appending garbage bytes
    with open(joblib_path, "ab") as f:
        f.write(b"CORRUPTED_BYTES")

    # Loading with verify_checksum=True must raise ValueError
    with pytest.raises(ValueError) as exc_info:
        load_preprocessor(joblib_path, verify_checksum=True)
    assert "Artifact integrity verification failed" in str(exc_info.value)


def test_save_unfitted_raises(tmp_path: Path):
    unfitted = TrafficShieldPreprocessor()
    with pytest.raises(ValueError) as exc:
        save_preprocessor(unfitted, tmp_path / "unfitted.joblib")
    assert "Cannot save an unfitted" in str(exc.value)


def test_load_nonexistent_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_preprocessor(tmp_path / "does_not_exist.joblib")


def test_missing_manifest_rejected_when_checksum_enabled(fitted_preprocessor, tmp_path: Path):
    prep, _ = fitted_preprocessor
    artifact_path = tmp_path / "prep_no_manifest.joblib"
    joblib_p, json_p = save_preprocessor(prep, artifact_path)

    # Delete manifest
    json_p.unlink()

    with pytest.raises(ValueError) as exc:
        load_preprocessor(joblib_p, verify_checksum=True)
    assert "companion manifest not found" in str(exc.value)

    # When verify_checksum=False, loads cleanly
    loaded_prep, _ = load_preprocessor(joblib_p, verify_checksum=False)
    assert loaded_prep.is_fitted_


def test_missing_sha256_in_manifest_rejected(fitted_preprocessor, tmp_path: Path):
    prep, _ = fitted_preprocessor
    artifact_path = tmp_path / "prep_bad_manifest.joblib"
    joblib_p, json_p = save_preprocessor(prep, artifact_path)

    json_p.write_text('{"format_version": "1.0"}', encoding="utf-8")

    with pytest.raises(ValueError) as exc:
        load_preprocessor(joblib_p, verify_checksum=True)
    assert "'sha256' field missing" in str(exc.value)
