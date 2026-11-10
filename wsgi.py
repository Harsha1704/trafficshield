"""
TrafficShield — Production WSGI Entry Point (Waitress)
=====================================================
Single-process, multi-threaded production WSGI server for Windows environments.

Execution commands:
    python wsgi.py
Or using Waitress CLI:
    waitress-serve --listen=127.0.0.1:5000 wsgi:app
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import types
from typing import Any

# Windows Smart App Control / WDAC compatibility guard:
if "sklearn.linear_model._sag_fast" not in sys.modules:
    try:
        import sklearn.linear_model._sag_fast  # noqa: F401
    except (ImportError, OSError):
        _mock_sag = types.ModuleType("sklearn.linear_model._sag_fast")
        _mock_sag.sag32 = lambda *args, **kwargs: None  # type: ignore[attr-defined]
        _mock_sag.sag64 = lambda *args, **kwargs: None  # type: ignore[attr-defined]
        sys.modules["sklearn.linear_model._sag_fast"] = _mock_sag

if "scipy.stats._qmvnt_cy" not in sys.modules:
    try:
        import scipy.stats._qmvnt_cy  # noqa: F401
    except (ImportError, OSError):
        _mock_qmvnt = types.ModuleType("scipy.stats._qmvnt_cy")
        _mock_qmvnt._qmvn_inner = lambda *args, **kwargs: (0.0, 0.0)
        _mock_qmvnt._qmvt_inner = lambda *args, **kwargs: (0.0, 0.0)
        sys.modules["scipy.stats._qmvnt_cy"] = _mock_qmvnt

from app import create_app
from app.lifecycle import run_startup_preflight, shutdown_application
from config.settings import BaseAppSettings, get_settings

logger = logging.getLogger("trafficshield.wsgi")

# Top-level WSGI callable
_env = os.getenv("FLASK_ENV", "production")
app = create_app(env=_env)


def run_production_server(
    host: str | None = None,
    port: int | None = None,
    threads: int | None = None,
    application: Any = None,
    settings: BaseAppSettings | None = None,
) -> None:
    """
    Launch TrafficShield under the Waitress production WSGI server.
    Enforces startup preflight qualification and single-process execution.
    """
    import waitress

    target_app = application or app
    if settings is None:
        settings = target_app.config.get("TRAFFICSHIELD_SETTINGS") or get_settings("production")

    server_host = host or getattr(settings, "server_host", "127.0.0.1")
    server_port = int(port or getattr(settings, "server_port", 5000))
    server_threads = int(threads or getattr(settings, "server_threads", 4))

    # 1. Execute fail-fast startup preflight
    preflight_report = run_startup_preflight(target_app, settings)
    logger.info("Preflight validation passed: %s", preflight_report)

    # 2. Attach OS signal handlers for graceful shutdown (main thread only)
    def _handle_signal(signum: int, _frame: Any) -> None:
        sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        logger.info("Received OS termination signal %s; initiating graceful teardown...", sig_name)
        shutdown_application(target_app)
        sys.exit(0)

    if threading.current_thread() is threading.main_thread():
        try:
            signal.signal(signal.SIGINT, _handle_signal)
            signal.signal(signal.SIGTERM, _handle_signal)
        except (ValueError, AttributeError):
            pass

    # 3. Print production startup banner
    banner = (
        f"\n{'='*70}\n"
        f" TrafficShield Production WSGI Server (Waitress)\n"
        f" Environment: {settings.app_name} v{settings.app_version}\n"
        f" Architecture: Single Process, Multi-Threaded ({server_threads} worker threads)\n"
        f" Bound Address: http://{server_host}:{server_port}\n"
        f" In-Memory Capture Manager: Unified (Process-Local)\n"
        f"{'='*70}\n"
    )
    sys.stdout.write(banner)
    sys.stdout.flush()

    # 4. Start Waitress WSGI server
    try:
        waitress.serve(
            target_app,
            host=server_host,
            port=server_port,
            threads=server_threads,
            ident="TrafficShield-WSGI",
        )
    except (KeyboardInterrupt, SystemExit):
        logger.info("Server interrupted; proceeding to teardown.")
    finally:
        logger.info("Executing final application shutdown sequence...")
        shutdown_application(target_app)


if __name__ == "__main__":
    run_production_server()
