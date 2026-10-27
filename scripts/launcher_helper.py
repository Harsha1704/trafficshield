"""
TrafficShield Launcher Service Inspector & Readiness Verifier
=============================================================
Helper utility for `run_trafficshield.bat`.
Performs socket connectivity and HTTP health verification using standard library only.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import time
import urllib.error
import urllib.request

BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 5000
BACKEND_HEALTH_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}/api/v1/health"

FRONTEND_HOST = "127.0.0.1"
FRONTEND_PORT = 5173
FRONTEND_URL = f"http://localhost:{FRONTEND_PORT}/"


def is_port_in_use(host: str, port: int) -> bool:
    """Check if a TCP port is currently open and listening."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.8)
        return s.connect_ex((host, port)) == 0


def probe_backend() -> str:
    """
    Probe the backend port and health endpoint.
    Returns: 'FREE', 'ALREADY_RUNNING', or 'CONFLICT'.
    """
    if not is_port_in_use(BACKEND_HOST, BACKEND_PORT):
        return "FREE"

    # Port is in use: check if it's TrafficShield backend
    try:
        req = urllib.request.Request(BACKEND_HEALTH_URL)
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            if resp.status == 200:
                body = resp.read().decode("utf-8", errors="ignore")
                data = json.loads(body)
                if data.get("data", {}).get("service") == "TrafficShield":
                    return "ALREADY_RUNNING"
        return "CONFLICT"
    except Exception:
        return "CONFLICT"


def probe_frontend() -> str:
    """
    Probe the frontend port and root endpoint.
    Returns: 'FREE', 'ALREADY_RUNNING', or 'CONFLICT'.
    """
    if not is_port_in_use(FRONTEND_HOST, FRONTEND_PORT):
        return "FREE"

    # Port is in use: check if it responds as Vite frontend
    try:
        req = urllib.request.Request(FRONTEND_URL)
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            if resp.status == 200:
                body = resp.read().decode("utf-8", errors="ignore")
                if "vite" in body.lower() or "trafficshield" in body.lower() or "html" in body.lower():
                    return "ALREADY_RUNNING"
        return "CONFLICT"
    except Exception:
        return "CONFLICT"


def check_ports() -> int:
    """Check both ports and print status for batch file consumption."""
    b_stat = probe_backend()
    f_stat = probe_frontend()
    print(f"BACKEND_STATUS={b_stat}")
    print(f"FRONTEND_STATUS={f_stat}")

    if b_stat == "CONFLICT" or f_stat == "CONFLICT":
        return 1
    return 0


def wait_ready(timeout_seconds: int = 60) -> int:
    """
    Poll both services until healthy or timeout expires.
    Exit codes:
        0: Both ready
        1: Backend failed / timed out
        2: Frontend failed / timed out
        3: Both failed / timed out
    """
    start_time = time.time()
    backend_ready = False
    frontend_ready = False

    while time.time() - start_time < timeout_seconds:
        elapsed = int(time.time() - start_time)

        # Probe backend
        if not backend_ready:
            try:
                req = urllib.request.Request(BACKEND_HEALTH_URL)
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                        if data.get("data", {}).get("service") == "TrafficShield":
                            backend_ready = True
            except Exception:
                pass

        # Probe frontend
        if not frontend_ready:
            try:
                req = urllib.request.Request(FRONTEND_URL)
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    if resp.status == 200:
                        frontend_ready = True
            except Exception:
                pass

        if backend_ready and frontend_ready:
            print(f"All services ready after {elapsed}s.")
            return 0

        # Status heartbeat
        b_mark = "[OK]" if backend_ready else "[WAIT]"
        f_mark = "[OK]" if frontend_ready else "[WAIT]"
        sys.stdout.write(f"\r  Elapsed: {elapsed:2d}s / {timeout_seconds}s  |  Backend (Port 5000): {b_mark}  |  Frontend (Port 5173): {f_mark}   ")
        sys.stdout.flush()
        time.sleep(1.0)

    print("\n")
    if not backend_ready and not frontend_ready:
        print("[TIMEOUT] Both Backend and Frontend failed to become ready within deadline.")
        return 3
    if not backend_ready:
        print("[TIMEOUT] Backend failed to become ready within deadline.")
        return 1
    if not frontend_ready:
        print("[TIMEOUT] Frontend failed to become ready within deadline.")
        return 2

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="TrafficShield Launcher Helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("check-ports", help="Probe port availability and status")

    wait_parser = subparsers.add_parser("wait-ready", help="Wait for services to become ready")
    wait_parser.add_argument("--timeout", type=int, default=60, help="Timeout in seconds")

    args = parser.parse_args()

    if args.command == "check-ports":
        sys.exit(check_ports())
    elif args.command == "wait-ready":
        sys.exit(wait_ready(args.timeout))


if __name__ == "__main__":
    main()
