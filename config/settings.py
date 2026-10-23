"""
TrafficShield Configuration
============================
Environment-aware settings using pydantic-settings.
Configuration is loaded from environment variables and .env files.

Usage:
    from config.settings import get_settings
    settings = get_settings()
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent


class BaseAppSettings(BaseSettings):
    """Shared settings across all environments."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ─── Application ─────────────────────────────────────────────────────────
    app_name: str = Field(default="TrafficShield")
    app_version: str = Field(default="0.1.0")
    secret_key: str = Field(default="dev-secret-key-change-in-production")

    # ─── Database ─────────────────────────────────────────────────────────────
    database_url: str = Field(
        default=f"sqlite:///{PROJECT_ROOT / 'trafficshield_dev.db'}"
    )

    # ─── Redis / Celery ───────────────────────────────────────────────────────
    redis_url: str = Field(default="redis://localhost:6379/0")
    celery_broker_url: str = Field(default="redis://localhost:6379/0")
    celery_result_backend: str = Field(default="redis://localhost:6379/1")

    # ─── MLflow ───────────────────────────────────────────────────────────────
    mlflow_tracking_uri: str = Field(default="sqlite:///mlruns.db")
    mlflow_experiment_name: str = Field(default="trafficshield")

    # ─── Upload limits ────────────────────────────────────────────────────────
    max_upload_bytes: int = Field(default=100 * 1024 * 1024)  # 100 MB
    allowed_extensions: str = Field(default="csv,pcap,pcapng")

    # ─── Rate limiting ────────────────────────────────────────────────────────
    ratelimit_default: str = Field(default="200 per hour")
    ratelimit_storage_url: str = Field(default="memory://")

    # ─── CORS ─────────────────────────────────────────────────────────────────
    cors_origins: str = Field(
        default="http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000"
    )

    # ─── Logging ──────────────────────────────────────────────────────────────
    log_level: str = Field(default="INFO")
    log_format: Literal["json", "text"] = Field(default="json")

    # ─── Security & Auth ──────────────────────────────────────────────────────
    session_cookie_secure: bool = Field(default=False)
    session_cookie_httponly: bool = Field(default=True)
    session_cookie_samesite: str = Field(default="Lax")
    auth_enabled: bool = Field(default=True)
    auth_token_expiry_hours: int = Field(default=8)
    admin_initial_username: str = Field(default="admin")
    admin_initial_password: str = Field(default="")
    analyst_initial_username: str = Field(default="analyst")
    analyst_initial_password: str = Field(default="")

    # ─── Monitoring Operational Thresholds ────────────────────────────────────
    monitoring_retention_days: int = Field(default=30)
    monitoring_stale_hours: int = Field(default=24)

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid:
            raise ValueError(f"log_level must be one of {valid}")
        return upper

    @property
    def allowed_extension_set(self) -> set[str]:
        return {ext.strip().lower() for ext in self.allowed_extensions.split(",")}

    @property
    def is_production(self) -> bool:
        return False

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def to_flask_config(self) -> dict:
        """Return a dict suitable for app.config.update()."""
        return {
            "SECRET_KEY": self.secret_key,
            "SQLALCHEMY_DATABASE_URI": self.database_url,
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "MAX_CONTENT_LENGTH": self.max_upload_bytes,
            "RATELIMIT_DEFAULT": self.ratelimit_default,
            "RATELIMIT_STORAGE_URI": self.ratelimit_storage_url,
            "SESSION_COOKIE_SECURE": self.session_cookie_secure,
            "SESSION_COOKIE_HTTPONLY": self.session_cookie_httponly,
            "SESSION_COOKIE_SAMESITE": self.session_cookie_samesite,
            "AUTH_ENABLED": self.auth_enabled,
            "AUTH_TOKEN_EXPIRY_HOURS": self.auth_token_expiry_hours,
        }


class DevelopmentSettings(BaseAppSettings):
    """Development environment — verbose logging, debug mode."""

    flask_debug: bool = Field(default=True)
    log_level: str = Field(default="DEBUG")
    log_format: Literal["json", "text"] = Field(default="text")


class TestingSettings(BaseAppSettings):
    """Testing environment — in-memory SQLite, no rate limits."""

    database_url: str = Field(default="sqlite:///:memory:")
    testing: bool = Field(default=True)
    auth_enabled: bool = Field(default=False)
    log_level: str = Field(default="WARNING")
    ratelimit_default: str = Field(default="99999 per hour")
    ratelimit_storage_url: str = Field(default="memory://")

    def to_flask_config(self) -> dict:
        cfg = super().to_flask_config()
        cfg["TESTING"] = True
        cfg["WTF_CSRF_ENABLED"] = False
        cfg["SQLALCHEMY_ENGINE_OPTIONS"] = {"connect_args": {"check_same_thread": False}}
        return cfg


class ProductionSettings(BaseAppSettings):
    """Production environment — enforces security requirements."""

    flask_debug: bool = Field(default=False)
    session_cookie_secure: bool = Field(default=True)
    log_format: Literal["json", "text"] = Field(default="json")

    @property
    def is_production(self) -> bool:
        return True

    @field_validator("secret_key")
    @classmethod
    def secret_key_must_be_strong(cls, v: str) -> str:
        if v in ("dev-secret-key-change-in-production", "change-me-in-production-use-secrets-manager"):
            raise ValueError(
                "SECRET_KEY must be set to a strong random value in production"
            )
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters in production")
        return v

    @field_validator("database_url")
    @classmethod
    def db_must_not_be_sqlite(cls, v: str) -> str:
        if v.startswith("sqlite"):
            raise ValueError("Production database must not use SQLite")
        return v

    @field_validator("cors_origins")
    @classmethod
    def cors_must_not_be_wildcard(cls, v: str) -> str:
        origins = [o.strip() for o in v.split(",") if o.strip()]
        if "*" in origins:
            raise ValueError("Wildcard CORS origin '*' is strictly prohibited in production")
        return v

    @field_validator("flask_debug")
    @classmethod
    def debug_must_be_false(cls, v: bool) -> bool:
        if v is True:
            raise ValueError("flask_debug must be False in production")
        return v


# ─── Environment selection ────────────────────────────────────────────────────
_ENV_MAP: dict[str, type[BaseAppSettings]] = {
    "development": DevelopmentSettings,
    "testing": TestingSettings,
    "production": ProductionSettings,
}


@lru_cache(maxsize=1)
def get_settings(env: str | None = None) -> BaseAppSettings:
    """
    Return the singleton settings object for the current environment.

    The environment is determined by the FLASK_ENV (or APP_ENV) variable,
    defaulting to 'development'.
    """
    env = env or os.getenv("FLASK_ENV") or os.getenv("APP_ENV") or os.getenv("ENV") or "development"
    env = env.lower()
    settings_cls = _ENV_MAP.get(env, DevelopmentSettings)
    return settings_cls()


def get_testing_settings() -> TestingSettings:
    """Return a fresh TestingSettings instance (not cached)."""
    return TestingSettings()
