"""
Authentication & Role-Based Access Control (RBAC) Utilities
============================================================
Milestone 13 — Production Deployment, Security Hardening & Release Readiness

Provides:
- Cryptographic token generation and verification using itsdangerous
- HTTP-Only session cookie and Bearer token handling
- Server-side role authorization decorators (@require_auth, @require_role)
- Initial credential bootstrap for admin and analyst accounts
"""
from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

from flask import current_app, g, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.database.models import User
from app.extensions import db
from app.utils.response import error_response

logger = logging.getLogger("auth")

AUTH_SALT = "trafficshield-auth-v1"
COOKIE_NAME = "trafficshield_session"


def get_serializer() -> URLSafeTimedSerializer:
    """Return itsdangerous serializer using application secret key."""
    secret = current_app.config.get("SECRET_KEY", "fallback-secret-key-change-in-production")
    return URLSafeTimedSerializer(secret_key=secret, salt=AUTH_SALT)


def generate_token(user: User, expires_in_hours: int | None = None) -> str:
    """Generate signed, time-limited authentication token."""
    serializer = get_serializer()
    now_ts = int(datetime.now(UTC).timestamp())
    payload = {
        "sub": user.id,
        "username": user.username,
        "role": user.role,
        "iat": now_ts,
    }
    return serializer.dumps(payload)


def verify_token(token: str, max_age_seconds: int | None = None) -> dict[str, Any] | None:
    """Validate signed token and return claims payload or None if invalid/expired."""
    serializer = get_serializer()
    if max_age_seconds is None:
        expiry_hours = current_app.config.get("AUTH_TOKEN_EXPIRY_HOURS", 8)
        max_age_seconds = int(expiry_hours * 3600)

    try:
        data = serializer.loads(token, max_age=max_age_seconds)
        if isinstance(data, dict) and "sub" in data and "role" in data:
            return data
    except SignatureExpired:
        logger.debug("Authentication token expired")
        return None
    except BadSignature:
        logger.warning("Invalid token signature detected")
        return None
    except Exception as exc:
        logger.warning("Token verification unexpected error: %s", exc)
        return None
    return None


def get_current_user_from_request() -> User | None:
    """
    Extract and verify user identity from Bearer token header or session cookie.
    Caches resolved user on Flask 'g.current_user'.
    """
    if hasattr(g, "current_user") and g.current_user is not None:
        return cast(User, g.current_user)

    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()

    if not token:
        token = request.cookies.get(COOKIE_NAME)

    if not token:
        return None

    claims = verify_token(token)
    if not claims:
        return None

    user_id = claims.get("sub")
    if not user_id:
        return None

    try:
        user = db.session.get(User, user_id)
        if user and user.is_active:
            g.current_user = user
            return user
    except Exception as exc:
        logger.error("Error retrieving user from database: %s", exc)
        return None

    return None


def require_auth(f: Callable) -> Callable:
    """Decorator requiring valid user authentication."""
    @functools.wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        if not current_app.config.get("AUTH_ENABLED", True):
            return f(*args, **kwargs)

        user = get_current_user_from_request()
        if not user:
            return error_response(
                message="Authentication credentials missing, invalid, or expired",
                status_code=401,
                error_code="UNAUTHORIZED",
            )
        return f(*args, **kwargs)

    return decorated


def require_role(*allowed_roles: str) -> Callable:
    """Decorator requiring user authentication and specific role authorization."""
    def decorator(f: Callable) -> Callable:
        @functools.wraps(f)
        def decorated(*args: Any, **kwargs: Any) -> Any:
            if not current_app.config.get("AUTH_ENABLED", True):
                return f(*args, **kwargs)

            user = get_current_user_from_request()
            if not user:
                return error_response(
                    message="Authentication credentials missing, invalid, or expired",
                    status_code=401,
                    error_code="UNAUTHORIZED",
                )

            if user.role not in allowed_roles:
                logger.warning(
                    "Forbidden access attempt: user %s (role %s) attempted action requiring %s",
                    user.username,
                    user.role,
                    allowed_roles,
                )
                return error_response(
                    message=f"Access forbidden: operation requires role in {allowed_roles}",
                    status_code=403,
                    error_code="FORBIDDEN",
                )

            return f(*args, **kwargs)

        return decorated

    return decorator


def bootstrap_initial_users(app) -> None:
    """Bootstrap default admin and analyst users if user table is empty."""
    with app.app_context():
        try:
            # Check if users already exist
            if User.query.count() > 0:
                return

            settings = app.config.get("TRAFFICSHIELD_SETTINGS")
            is_prod = getattr(settings, "is_production", False)

            if not is_prod:
                # Seed standard development/testing users
                admin = User(username="admin", role="admin", is_active=True)
                admin.set_password("AdminPass123!")

                analyst = User(username="analyst", role="analyst", is_active=True)
                analyst.set_password("AnalystPass123!")

                db.session.add_all([admin, analyst])
                db.session.commit()
                logger.info("Bootstrapped default dev users: 'admin' and 'analyst'")
            else:
                # Production: read initial credentials from environment if provided
                adm_user = app.config.get("ADMIN_INITIAL_USERNAME") or "admin"
                adm_pass = app.config.get("ADMIN_INITIAL_PASSWORD")

                if adm_pass and len(adm_pass) >= 12:
                    admin = User(username=adm_user, role="admin", is_active=True)
                    admin.set_password(adm_pass)
                    db.session.add(admin)
                    logger.info("Bootstrapped initial production admin user '%s'", adm_user)

                ana_user = app.config.get("ANALYST_INITIAL_USERNAME") or "analyst"
                ana_pass = app.config.get("ANALYST_INITIAL_PASSWORD")
                if ana_pass and len(ana_pass) >= 12:
                    analyst = User(username=ana_user, role="analyst", is_active=True)
                    analyst.set_password(ana_pass)
                    db.session.add(analyst)
                    logger.info("Bootstrapped initial production analyst user '%s'", ana_user)

                db.session.commit()
        except Exception as exc:
            db.session.rollback()
            logger.warning("User bootstrap encountered non-fatal error: %s", exc)
