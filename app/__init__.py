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
        supports_credentials=False,
    )
    limiter.init_app(app)

    # ─── Register blueprints ──────────────────────────────────────────────────
    from app.api import register_blueprints
    register_blueprints(app)

    # ─── Database tables ──────────────────────────────────────────────────────
    with app.app_context():
        # Import models so SQLAlchemy sees them before create_all
        from app.database import models  # noqa: F401
        db.create_all()

    logger.info("TrafficShield ready", extra={"db_uri": _safe_db_uri(settings.database_url)})
    return app


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
