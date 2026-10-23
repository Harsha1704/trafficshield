"""
Real-Time Capture & PCAP Replay API Endpoints
==============================================
Milestone 14 — Real-Time Network Detection & Flow Reconstruction

Exposes secure, auditable endpoints to control packet capture sessions,
inspect network interfaces, pace PCAP replays, and stream real-time detections.

Routes:
- GET  /api/v1/capture/status: Retrieve real-time worker state, metrics, and event buffer
- GET  /api/v1/capture/interfaces: Enumerate network interfaces and capture driver health
- GET  /api/v1/capture/sample-pcaps: List authorized local PCAP replay files
- POST /api/v1/capture/start-replay: Initiate offline PCAP replay session (analyst/admin)
- POST /api/v1/capture/start-live: Initiate passive live interface capture (analyst/admin)
- POST /api/v1/capture/pause: Pause active packet stream (analyst/admin)
- POST /api/v1/capture/resume: Resume paused packet stream (analyst/admin)
- POST /api/v1/capture/stop: Halt capture and flush in-flight flows (analyst/admin)
- POST /api/v1/capture/upload-pcap: Securely upload PCAP for instant replay (analyst/admin)
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, request
from werkzeug.utils import secure_filename

from app.utils.auth import require_role
from app.utils.response import error_response, success_response
from ingestion.capture.live_source import enumerate_network_interfaces, is_capture_driver_available
from streaming.manager import RealTimeDetectionManager

logger = logging.getLogger("capture_api")

capture_bp = Blueprint("capture", __name__)


@capture_bp.route("/status", methods=["GET"])
def get_capture_status() -> Any:
    """Retrieve operational status, metrics, and recent detection events."""
    manager = RealTimeDetectionManager.get_instance()
    status = manager.get_status()
    return success_response(data=status, status_code=200)


@capture_bp.route("/interfaces", methods=["GET"])
def get_interfaces() -> Any:
    """Enumerate host network interfaces and kernel packet filter availability."""
    interfaces = enumerate_network_interfaces()
    driver_ok, driver_msg = is_capture_driver_available()
    return success_response(
        data={
            "driver_available": driver_ok,
            "driver_status": driver_msg,
            "interfaces": interfaces,
        },
        status_code=200,
    )


@capture_bp.route("/sample-pcaps", methods=["GET"])
def list_sample_pcaps() -> Any:
    """List available local authorized PCAP files available for immediate replay."""
    candidates: list[dict[str, Any]] = []

    search_dirs = [
        Path("data/captures"),
        Path("tests/fixtures"),
        Path("datasets/samples"),
    ]

    for d in search_dirs:
        if d.exists() and d.is_dir():
            for f in d.glob("*.pcap*"):
                if f.is_file():
                    candidates.append({
                        "filename": f.name,
                        "path": str(f.resolve()),
                        "size_bytes": f.stat().st_size,
                    })

    return success_response(data=candidates, status_code=200)


@capture_bp.route("/start-replay", methods=["POST"])
@require_role("analyst", "admin")
def start_replay() -> Any:
    """Start an offline PCAP replay session."""
    if not request.is_json:
        return error_response(
            message="Request body must be valid application/json",
            status_code=400,
            error_code="INVALID_CONTENT_TYPE",
        )

    data = request.get_json(silent=True) or {}
    pcap_path = data.get("pcap_path")
    if not pcap_path:
        return error_response(
            message="Missing required field 'pcap_path'",
            status_code=400,
            error_code="MISSING_PCAP_PATH",
        )

    speed_multiplier = float(data.get("speed_multiplier", 1.0))
    max_packets = data.get("max_packets")
    if max_packets is not None:
        max_packets = int(max_packets)

    manager = RealTimeDetectionManager.get_instance()

    try:
        status = manager.start_pcap_replay(
            pcap_path=pcap_path,
            speed_multiplier=speed_multiplier,
            app=current_app._get_current_object(),  # type: ignore[attr-defined]
            max_packets=max_packets,
        )
        return success_response(
            data=status,
            message="PCAP replay session started successfully.",
            status_code=200,
        )
    except FileNotFoundError as fnf:
        return error_response(message=str(fnf), status_code=404, error_code="FILE_NOT_FOUND")
    except ValueError as ve:
        return error_response(message=str(ve), status_code=400, error_code="INVALID_PCAP")
    except RuntimeError as re:
        return error_response(message=str(re), status_code=409, error_code="SESSION_CONFLICT")
    except Exception as exc:
        logger.error("Failed to start PCAP replay: %s", exc, exc_info=True)
        return error_response(message=str(exc), status_code=500, error_code="REPLAY_START_FAILED")


@capture_bp.route("/start-live", methods=["POST"])
@require_role("analyst", "admin")
def start_live() -> Any:
    """Start a passive live interface capture session."""
    if not request.is_json:
        return error_response(
            message="Request body must be valid application/json",
            status_code=400,
            error_code="INVALID_CONTENT_TYPE",
        )

    data = request.get_json(silent=True) or {}
    interface = data.get("interface")
    if not interface:
        return error_response(
            message="Missing required field 'interface'",
            status_code=400,
            error_code="MISSING_INTERFACE",
        )

    bpf_filter = data.get("bpf_filter", "ip")
    manager = RealTimeDetectionManager.get_instance()

    try:
        status = manager.start_live_capture(
            interface=interface,
            bpf_filter=bpf_filter,
            app=current_app._get_current_object(),  # type: ignore[attr-defined]
        )
        return success_response(
            data=status,
            message=f"Live capture started on interface '{interface}'.",
            status_code=200,
        )
    except RuntimeError as re:
        logger.warning("Live capture start rejected: %s", re)
        return error_response(message=str(re), status_code=400, error_code="DRIVER_OR_SESSION_ERROR")
    except Exception as exc:
        logger.error("Failed to start live capture on %s: %s", interface, exc, exc_info=True)
        return error_response(message=str(exc), status_code=500, error_code="LIVE_CAPTURE_FAILED")


@capture_bp.route("/pause", methods=["POST"])
@require_role("analyst", "admin")
def pause_capture() -> Any:
    """Pause an active capture or replay session."""
    manager = RealTimeDetectionManager.get_instance()
    status = manager.pause()
    return success_response(data=status, message="Session paused.", status_code=200)


@capture_bp.route("/resume", methods=["POST"])
@require_role("analyst", "admin")
def resume_capture() -> Any:
    """Resume a paused capture or replay session."""
    manager = RealTimeDetectionManager.get_instance()
    status = manager.resume()
    return success_response(data=status, message="Session resumed.", status_code=200)


@capture_bp.route("/stop", methods=["POST"])
@require_role("analyst", "admin")
def stop_capture() -> Any:
    """Halt capture, flush in-flight flows, and terminate workers."""
    manager = RealTimeDetectionManager.get_instance()
    status = manager.stop()
    return success_response(data=status, message="Session stopped successfully.", status_code=200)


@capture_bp.route("/upload-pcap", methods=["POST"])
@require_role("analyst", "admin")
def upload_pcap() -> Any:
    """Upload a PCAP capture file for immediate replay."""
    if "file" not in request.files:
        return error_response(
            message="No file part in multipart request",
            status_code=400,
            error_code="NO_FILE_PART",
        )

    file = request.files["file"]
    if not file or not file.filename:
        return error_response(
            message="No file selected for upload",
            status_code=400,
            error_code="EMPTY_FILENAME",
        )

    filename = secure_filename(file.filename)
    if not (filename.endswith(".pcap") or filename.endswith(".pcapng")):
        return error_response(
            message="File must have .pcap or .pcapng extension",
            status_code=400,
            error_code="INVALID_EXTENSION",
        )

    dest_dir = Path("data/captures")
    dest_dir.mkdir(parents=True, exist_ok=True)
    target_path = dest_dir / filename

    file.save(str(target_path))

    return success_response(
        data={
            "filename": filename,
            "filepath": str(target_path.resolve()),
            "size_bytes": target_path.stat().st_size,
        },
        message="PCAP uploaded successfully and ready for replay.",
        status_code=201,
    )
