"""
Unit tests for Phase 5 Batch 1: Core Reliability & Fail-Safe Hardening.
=======================================================================
Validates:
1. Fail-fast behavior for uninitialized, missing, or failed-to-load detector models.
2. SQLite connection reliability (busy_timeout=5000, WAL mode, synchronous=NORMAL, connect_args timeout=15s).
3. Canonical PCAP replay path containment and directory traversal rejection.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app import create_app
from app.database.models import User
from app.extensions import db
from app.utils.auth import generate_token
from config.settings import TestingSettings as AppTestingSettings
from ingestion.capture.pcap_source import VALID_MAGIC_BYTES
from ml.production_service import ProductionInferenceService
from streaming.manager import validate_pcap_path

# ─── 1. Model Reliability & Fail-Safe Inference Tests ─────────────────────────

def test_uninitialized_model_raises_runtime_error():
    """Verify that an uninitialized detector refuses inference instead of returning 0.0."""
    service = ProductionInferenceService(verify_checksums=False)
    service.model = None  # Force uninitialized

    valid_flow = {
        "duration_seconds": 0.05,
        "fwd_bytes": 1000,
        "sttl": 64,
        "sload": 160000.0,
        "fwd_packets": 10,
        "swin": 255,
        "smeansz": 100.0,
        "sjit": 0.0,
        "sintpkt": 5.0,
        "is_sm_ips_ports": 0,
    }

    # predict_single must raise RuntimeError, NOT return score 0.0
    with pytest.raises(RuntimeError, match="Production detector model is uninitialized"):
        service.predict_single(valid_flow)

    # predict_batch must also raise RuntimeError
    with pytest.raises(RuntimeError, match="Production detector model is uninitialized"):
        service.predict_batch([valid_flow])


def test_missing_model_file_raises_filenotfound(tmp_path: Path):
    """Verify that specifying a non-existent model artifact path raises FileNotFoundError."""
    missing_path = tmp_path / "nonexistent_model.joblib"
    with pytest.raises(FileNotFoundError, match="Model artifact not found"):
        ProductionInferenceService(model_path=missing_path, verify_checksums=False)


def test_optional_iforest_availability_semantics():
    """Verify that when Isolation Forest is omitted, supervised still functions and availability is False."""
    # Initialize service with real detector but no iforest
    service = ProductionInferenceService(
        model_path="artifacts/models/production_detector.joblib",
        preprocessor_path="artifacts/models/production_preprocessor.joblib",
        iforest_path=None,
        verify_checksums=True,
    )
    service.iforest = None
    service.hybrid_enabled = False

    valid_flow = {
        "duration_seconds": 0.05,
        "fwd_bytes": 1000,
        "sttl": 64,
        "sload": 160000.0,
        "fwd_packets": 10,
        "swin": 255,
        "smeansz": 100.0,
        "sjit": 0.0,
        "sintpkt": 5.0,
        "is_sm_ips_ports": 0,
    }

    result = service.predict_single(valid_flow)
    assert "anomaly_score" in result
    assert result["unsupervised"]["available"] is False
    assert result["unsupervised"]["anomaly_score"] == 0.0
    # Classification must not crash and should reflect supervised alert or normal
    assert result["hybrid_classification"] in ("NORMAL_TRAFFIC", "SUPERVISED_ONLY_ALERT")


def test_api_predict_returns_503_when_model_uninitialized(client, monkeypatch):
    """Verify Flask API returns HTTP 503 instead of fabricated benign results when model fails."""
    # Create analyst token
    with client.application.app_context():
        analyst = User.query.filter_by(role="analyst").first()
        if not analyst:
            analyst = User(username="analyst_rel", role="analyst", is_active=True)
            analyst.set_password("Pass123!")
            db.session.add(analyst)
            db.session.commit()
        token = generate_token(analyst)

    headers = {"Authorization": f"Bearer {token}"}

    # Mock get_inference_service to return a service with uninitialized model
    broken_service = ProductionInferenceService(verify_checksums=False)
    broken_service.model = None

    from app.api.v1 import predict
    monkeypatch.setattr(predict, "get_inference_service", lambda: broken_service)

    flow_payload = {
        "duration_seconds": 0.05,
        "fwd_bytes": 1000,
        "sttl": 64,
        "sload": 160000.0,
        "fwd_packets": 10,
        "swin": 255,
        "smeansz": 100.0,
        "sjit": 0.0,
        "sintpkt": 5.0,
        "is_sm_ips_ports": 0,
    }

    # POST /api/v1/predict
    res_single = client.post("/api/v1/predict", json=flow_payload, headers=headers)
    assert res_single.status_code == 503
    err = res_single.get_json()["error"]
    assert err["code"] == "INFERENCE_ENGINE_UNAVAILABLE"
    assert "uninitialized" in err["message"]

    # POST /api/v1/predict/batch
    res_batch = client.post("/api/v1/predict/batch", json={"records": [flow_payload]}, headers=headers)
    assert res_batch.status_code == 503
    assert res_batch.get_json()["error"]["code"] == "INFERENCE_ENGINE_UNAVAILABLE"


# ─── 2. SQLite Connection Reliability Tests ───────────────────────────────────

def test_sqlite_pragmas_on_file_database(tmp_path: Path):
    """Verify that file-backed SQLite connections configure busy_timeout=5000, WAL, and NORMAL synchronous."""
    db_file = tmp_path / "test_reliability.db"
    settings = AppTestingSettings(database_url=f"sqlite:///{db_file.resolve().as_posix()}")
    test_app = create_app(settings)

    with test_app.app_context():
        # Open connection and query active PRAGMAs
        from sqlalchemy import text
        with db.engine.connect() as conn:
            busy = conn.execute(text("PRAGMA busy_timeout")).scalar()
            journal = conn.execute(text("PRAGMA journal_mode")).scalar()
            sync = conn.execute(text("PRAGMA synchronous")).scalar()

            assert busy == 5000, f"Expected busy_timeout=5000, got {busy}"
            assert str(journal).lower() == "wal", f"Expected journal_mode=wal, got {journal}"
            assert sync == 1, f"Expected synchronous=1 (NORMAL), got {sync}"


def test_sqlite_pragmas_on_in_memory_database():
    """Verify that in-memory SQLite connections configure busy_timeout=5000 without forcing WAL."""
    test_app = create_app("testing")
    with test_app.app_context():
        from sqlalchemy import text
        with db.engine.connect() as conn:
            busy = conn.execute(text("PRAGMA busy_timeout")).scalar()
            journal = conn.execute(text("PRAGMA journal_mode")).scalar()
            assert busy == 5000
            assert str(journal).lower() == "memory"


def test_postgresql_connection_ignores_sqlite_pragmas():
    """Verify that non-SQLite DBAPI connections (e.g. PostgreSQL) are untouched by SQLite pragmas."""
    from app import _SQLITE_PRAGMA_LISTENER_REGISTERED, set_sqlite_pragmas
    assert _SQLITE_PRAGMA_LISTENER_REGISTERED is True

    # Simulate a non-sqlite DBAPI connection (like psycopg2)
    fake_pg_conn = MagicMock()
    # It should not be an instance of sqlite3.Connection
    assert not isinstance(fake_pg_conn, sqlite3.Connection)

    # Invoke pragma configuration with non-sqlite connection
    set_sqlite_pragmas(fake_pg_conn, None)

    # fake_pg_conn.cursor() should never have been invoked
    fake_pg_conn.cursor.assert_not_called()


def test_sqlite_concurrent_readers_and_writers_in_wal(tmp_path: Path):
    """Exercise concurrent reads and writes on file-backed SQLite in WAL mode."""
    db_file = tmp_path / "wal_concurrency.db"
    settings = AppTestingSettings(database_url=f"sqlite:///{db_file.resolve().as_posix()}")
    app = create_app(settings)

    with app.app_context():
        db.create_all()

    errors: list[Exception] = []

    def writer_task():
        try:
            with app.app_context():
                for i in range(5):
                    u = User(username=f"writer_{threading.get_ident()}_{i}", role="analyst", is_active=True)
                    u.set_password("Pass123!")
                    db.session.add(u)
                    db.session.commit()
        except Exception as e:
            errors.append(e)

    def reader_task():
        try:
            with app.app_context():
                for _ in range(10):
                    _ = User.query.count()
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=writer_task),
        threading.Thread(target=writer_task),
        threading.Thread(target=reader_task),
        threading.Thread(target=reader_task),
    ]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"Concurrent WAL operations failed with errors: {errors}"


# ─── 3. PCAP Path Containment & Traversal Prevention Tests ────────────────────

def test_pcap_path_containment_legitimate_file(tmp_path: Path):
    """Verify that a legitimate PCAP inside an approved root is accepted."""
    approved_root = tmp_path / "captures"
    approved_root.mkdir()
    valid_pcap = approved_root / "test.pcap"
    valid_pcap.write_bytes(VALID_MAGIC_BYTES[0] + b"\x00" * 20)

    resolved = validate_pcap_path(valid_pcap, approved_roots=[approved_root.resolve()])
    assert resolved == valid_pcap.resolve()


def test_pcap_path_containment_traversal_rejection(tmp_path: Path):
    """Verify that .. traversal escaping the approved root is rejected."""
    approved_root = tmp_path / "captures"
    approved_root.mkdir()

    outside_file = tmp_path / "secret.pcap"
    outside_file.write_bytes(VALID_MAGIC_BYTES[0] + b"\x00" * 20)

    # Attempt directory traversal: captures/../secret.pcap
    traversal_path = approved_root / ".." / "secret.pcap"

    with pytest.raises(ValueError, match="Access denied: PCAP file path is outside authorized"):
        validate_pcap_path(traversal_path, approved_roots=[approved_root.resolve()])


def test_pcap_path_containment_absolute_outside_path(tmp_path: Path):
    """Verify that an absolute path outside approved roots is rejected."""
    approved_root = tmp_path / "captures"
    approved_root.mkdir()

    outside_root = tmp_path / "unauthorized"
    outside_root.mkdir()
    outside_file = outside_root / "evil.pcap"
    outside_file.write_bytes(VALID_MAGIC_BYTES[0] + b"\x00" * 20)

    with pytest.raises(ValueError, match="Access denied: PCAP file path is outside authorized"):
        validate_pcap_path(outside_file, approved_roots=[approved_root.resolve()])


def test_pcap_path_missing_file_raises_filenotfound(tmp_path: Path):
    """Verify that a non-existent file inside approved root raises FileNotFoundError."""
    approved_root = tmp_path / "captures"
    approved_root.mkdir()
    missing_file = approved_root / "missing.pcap"

    with pytest.raises(FileNotFoundError, match="PCAP capture file not found"):
        validate_pcap_path(missing_file, approved_roots=[approved_root.resolve()])


def test_pcap_path_directory_raises_valueerror(tmp_path: Path):
    """Verify that passing a directory instead of a regular file raises ValueError."""
    approved_root = tmp_path / "captures"
    approved_root.mkdir()
    sub_dir = approved_root / "subdir.pcap"
    sub_dir.mkdir()

    with pytest.raises(ValueError, match="Path is not a regular file"):
        validate_pcap_path(sub_dir, approved_roots=[approved_root.resolve()])


def test_api_start_replay_rejects_traversal(client):
    """Verify POST /api/v1/capture/start-replay rejects traversal with HTTP 400 PATH_TRAVERSAL_DETECTED."""
    # Obtain admin or analyst token
    with client.application.app_context():
        admin = User.query.filter_by(role="admin").first()
        if not admin:
            admin = User(username="admin_rel", role="admin", is_active=True)
            admin.set_password("AdminPass123!")
            db.session.add(admin)
            db.session.commit()
        token = generate_token(admin)

    headers = {"Authorization": f"Bearer {token}"}

    # Attempt path traversal
    payload = {
        "pcap_path": "data/captures/../../../../windows/system32/cmd.exe",
        "speed_multiplier": 1.0,
    }

    res = client.post("/api/v1/capture/start-replay", json=payload, headers=headers)
    assert res.status_code == 400
    err = res.get_json()["error"]
    assert err["code"] == "PATH_TRAVERSAL_DETECTED"
    assert "outside authorized" in err["message"]
