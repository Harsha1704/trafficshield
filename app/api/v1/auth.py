"""
TrafficShield SOC Authentication API Endpoints
===============================================
Milestone 13 — Production Deployment, Security Hardening & Release Readiness

Routes:
- POST /api/v1/auth/login: Authenticate user, set secure session cookie, return JWT-style Bearer token.
- POST /api/v1/auth/logout: Terminate session and clear session cookie.
- GET  /api/v1/auth/me: Retrieve profile and permissions of authenticated user.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from flask import Blueprint, current_app, request

from app.database.models import User
from app.extensions import db, limiter
from app.utils.auth import (
    COOKIE_NAME,
    generate_token,
    get_current_user_from_request,
    require_auth,
)
from app.utils.response import error_response, success_response

logger = logging.getLogger("auth_api")

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/login", methods=["POST"])
@limiter.limit("10 per minute")
def login() -> Any:
    """
    Authenticate analyst or administrator.
    Throttled to 10 requests per minute to prevent brute-force attacks.
    Returns generic error to prevent account enumeration.
    """
    if not request.is_json:
        return error_response(
            message="Request body must be valid application/json",
            status_code=400,
            error_code="INVALID_CONTENT_TYPE",
        )

    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()

    if not username or not password:
        return error_response(
            message="Username and password are required",
            status_code=400,
            error_code="MISSING_CREDENTIALS",
        )

    # Constant-time lookup / check
    user = User.query.filter(User.username == username).first()

    # Always perform a password check even if user doesn't exist to prevent timing attacks
    dummy_hash = "scrypt:32768:8:1$dummy$dummypasswordhashforconstanttimechecking12345"
    if user is None:
        from werkzeug.security import check_password_hash
        check_password_hash(dummy_hash, password)
        return error_response(
            message="Invalid username or password",
            status_code=401,
            error_code="INVALID_CREDENTIALS",
        )

    if not user.check_password(password) or not user.is_active:
        logger.warning("Failed login attempt for user '%s'", username)
        return error_response(
            message="Invalid username or password",
            status_code=401,
            error_code="INVALID_CREDENTIALS",
        )

    # Update login timestamp
    user.last_login_at = datetime.now(UTC)
    db.session.commit()

    token = generate_token(user)
    user_dict = user.to_dict()

    secure_cookie = current_app.config.get("SESSION_COOKIE_SECURE", False)
    httponly = current_app.config.get("SESSION_COOKIE_HTTPONLY", True)
    samesite = current_app.config.get("SESSION_COOKIE_SAMESITE", "Lax")
    expiry_hours = current_app.config.get("AUTH_TOKEN_EXPIRY_HOURS", 8)

    resp, status_code = success_response(
        message=f"Authentication successful. Welcome, {user.username}.",
        data={
            "token": token,
            "user": user_dict,
        },
        status_code=200,
    )

    # Set secure session cookie
    resp.set_cookie(
        COOKIE_NAME,
        token,
        max_age=int(expiry_hours * 3600),
        secure=secure_cookie,
        httponly=httponly,
        samesite=samesite,
        path="/",
    )

    logger.info("Successful login for user '%s' (role: %s)", user.username, user.role)
    return resp, status_code


@auth_bp.route("/logout", methods=["POST"])
def logout() -> Any:
    """Clear session cookie and terminate active session."""
    resp, status_code = success_response(
        message="Session terminated successfully.",
        data={"authenticated": False},
        status_code=200,
    )
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp, status_code


@auth_bp.route("/me", methods=["GET"])
@require_auth
def get_current_user_profile() -> Any:
    """Return profile and role of currently authenticated user."""
    user = get_current_user_from_request()
    if not user:
        return error_response("Not authenticated", 401, "UNAUTHORIZED")
    return success_response(data=user.to_dict(), status_code=200)
