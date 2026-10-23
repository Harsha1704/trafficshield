"""
TrafficShield Windows Production WSGI Server (Waitress)
========================================================
Milestone 13 — Production Deployment, Security Hardening & Release Readiness

Provides production-grade multi-threaded WSGI serving for Windows host deployments
without requiring Docker or Unix-only Gunicorn.

Usage:
    python run_waitress.py
    python run_waitress.py --port=5000 --threads=8
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from waitress import serve

from app import create_app
from config.settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("waitress_runner")


def main() -> None:
    parser = argparse.ArgumentParser(description="TrafficShield Windows Production WSGI Server")
    parser.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"), help="Host to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "5000")), help="Port to listen (default: 5000)")
    parser.add_argument("--threads", type=int, default=int(os.getenv("WAITRESS_THREADS", "8")), help="Worker threads (default: 8)")
    parser.add_argument("--channel-timeout", type=int, default=60, help="Channel timeout in seconds (default: 60)")
    args = parser.parse_args()

    env_name = os.getenv("FLASK_ENV") or os.getenv("APP_ENV") or "development"
    logger.info("Initializing TrafficShield Flask application (environment: %s)...", env_name)

    app = create_app()
    settings = get_settings()

    logger.info("================================================================================")
    logger.info("  TrafficShield Production Server (Waitress WSGI)")
    logger.info("  App Name:     %s v%s", settings.app_name, settings.app_version)
    logger.info("  Listening on: http://%s:%d", args.host, args.port)
    logger.info("  Threads:      %d (channel timeout: %ds)", args.threads, args.channel_timeout)
    logger.info("  Health Probe: http://localhost:%d/api/v1/health", args.port)
    logger.info("  Ready Probe:  http://localhost:%d/api/v1/ready", args.port)
    logger.info("================================================================================")

    try:
        serve(
            app,
            host=args.host,
            port=args.port,
            threads=args.threads,
            channel_timeout=args.channel_timeout,
            ident="TrafficShield-SOC/1.0",
        )
    except KeyboardInterrupt:
        logger.info("TrafficShield server shutdown requested. Exiting cleanly.")
        sys.exit(0)


if __name__ == "__main__":
    main()
