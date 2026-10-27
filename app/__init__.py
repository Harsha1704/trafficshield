"""
TrafficShield — Flask Application Factory
==========================================
Creates and configures the Flask application.

Usage:
    from app import create_app
    app = create_app()              # uses FLASK_ENV to select config
    app = create_app("testing")     # explicit environment
"""
from __future__ import annotations

import logging
import os

from flask import Flask

from app.extensions import cors, db, limiter, migrate
from app.utils.logging import configure_logging
from config.settings import BaseAppSettings, get_settings, get_testing_settings


def create_app(env: str | None = None) -> Flask:
    """
    Application factory.

    Parameters
    ----------
    env : str, optional
        Environment name: 'development', 'testing', or 'production'.
        If omitted, reads from FLASK_ENV / APP_ENV environment variable,
        defaulting to 'development'.
    """
    app = Flask(__name__, instance_relative_config=False)

    # ─── Load settings ────────────────────────────────────────────────────────
    settings: BaseAppSettings
    if env == "testing":
        settings = get_testing_settings()
    else:
        settings = get_settings(env)

    app.config.update(settings.to_flask_config())
    app.config["TRAFFICSHIELD_SETTINGS"] = settings

    # ─── Logging ──────────────────────────────────────────────────────────────
    configure_logging(
        level=settings.log_level,
        fmt=settings.log_format,
    )
    logger = logging.getLogger(__name__)
    logger.info(
        "TrafficShield starting",
        extra={"env": env or os.getenv("FLASK_ENV", "development"), "version": settings.app_version},
    )

    # ─── Extensions ───────────────────────────────────────────────────────────
    db.init_app(app)
    migrate.init_app(app, db)
    cors.init_app(
        app,
        origins=settings.cors_origin_list,
        supports_credentials=True if "*" not in settings.cors_origin_list else False,
        allow_headers=["Content-Type", "Authorization", "X-Request-ID", "X-Batch-ID", "X-Source"],
        expose_headers=["X-Request-ID"],
    )
    limiter.init_app(app)

    # ─── Register blueprints ──────────────────────────────────────────────────
    from app.api import register_blueprints
    register_blueprints(app)

    # ─── Frontend Static SPA Serving (when bundle is built) ───────────────────
    _configure_frontend_routes(app)

    # ─── Database tables & Initial Bootstrap ──────────────────────────────────
    with app.app_context():
        # Import models so SQLAlchemy sees them
        from app.database import models  # noqa: F401

        is_prod = getattr(settings, "is_production", False)
        is_migration = os.getenv("ALEMBIC_MIGRATION_RUN") == "1"
        if not is_migration:
            if not is_prod:
                db.create_all()

            # Bootstrap default admin and analyst users if accounts are missing
            from app.utils.auth import bootstrap_initial_users
            bootstrap_initial_users(app)

            # Dispose DB engine connection pool in production so master process does not retain open sockets across fork
            if is_prod:
                try:
                    db.engine.dispose()
                except Exception:
                    pass

    # ─── Register CLI Commands ────────────────────────────────────────────────
    from app.cli import register_cli_commands
    register_cli_commands(app)

    # ─── Request Correlation & Security Headers ───────────────────────────────
    _configure_security_and_tracing(app, settings)

    logger.info("TrafficShield ready", extra={"db_uri": _safe_db_uri(settings.database_url)})
    return app


def _configure_frontend_routes(app: Flask) -> None:
    """Serve built React single-page application when static bundle exists."""
    from pathlib import Path

    root = Path(app.root_path).parent
    dist_dir = root / "frontend_dist"
    if not dist_dir.exists():
        dist_dir = root / "frontend" / "dist"

    if dist_dir.exists() and (dist_dir / "index.html").exists():
        from flask import send_from_directory

        spa_routes = {
            "",
            "overview",
            "traffic",
            "live",
            "alerts",
            "inspector",
            "model",
            "monitoring",
            "reports",
            "settings",
            "login",
        }

        @app.route("/", defaults={"path": ""})
        @app.route("/<path:path>")
        def serve_spa(path: str):
            if path.startswith("api/"):
                from app.utils.response import error_response
                return error_response(f"API endpoint '/{path}' not found", 404, "NOT_FOUND")

            target = dist_dir / path
            if path and target.exists() and target.is_file():
                return send_from_directory(str(dist_dir), path)

            if path in spa_routes:
                return send_from_directory(str(dist_dir), "index.html")

            from app.utils.response import error_response
            return error_response(f"Resource '/{path}' not found", 404, "NOT_FOUND")


def _configure_security_and_tracing(app: Flask, settings: BaseAppSettings) -> None:
    """Attach request correlation ID and defense-in-depth security headers."""
    import uuid

    from flask import g, request

    @app.before_request
    def set_correlation_id():
        req_id = request.headers.get("X-Request-ID")
        if not req_id or len(req_id) > 128:
            req_id = str(uuid.uuid4())
        g.request_id = req_id

    @app.after_request
    def apply_security_headers(response):
        # Propagate correlation ID
        response.headers["X-Request-ID"] = getattr(g, "request_id", str(uuid.uuid4()))

        # Browser Defensive Headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

        # Content Security Policy (strict default-src, inline styles allowed for modern UI widgets)
        csp = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "connect-src 'self' http: https:; "
            "font-src 'self' data:; "
            "frame-ancestors 'none';"
        )
        response.headers["Content-Security-Policy"] = csp

        # HSTS only in production with secure cookies
        if getattr(settings, "is_production", False) or settings.session_cookie_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response


def _safe_db_uri(uri: str) -> str:
    """Redact credentials from database URI for logging."""
    try:
        from urllib.parse import urlparse, urlunparse
        parts = urlparse(uri)
        if parts.password:
            safe = parts._replace(netloc=f"{parts.username}:***@{parts.hostname}:{parts.port}")
            return urlunparse(safe)
    except Exception:
        pass
    return uri
