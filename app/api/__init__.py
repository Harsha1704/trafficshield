"""API package — top-level blueprint registration."""
from __future__ import annotations

from flask import Flask


def register_blueprints(app: Flask) -> None:
    """Register all API blueprints with the Flask application."""
    from app.api.v1 import register_v1_blueprints
    register_v1_blueprints(app)

    # ─── Global error handlers ────────────────────────────────────────────────
    _register_error_handlers(app)


def _register_error_handlers(app: Flask) -> None:
    """Register centralized JSON error handlers."""
    from app.utils.response import error_response

    @app.errorhandler(400)
    def bad_request(e):
        return error_response("Bad request", 400, "BAD_REQUEST")

    @app.errorhandler(404)
    def not_found(e):
        return error_response("Resource not found", 404, "NOT_FOUND")

    @app.errorhandler(405)
    def method_not_allowed(e):
        return error_response("Method not allowed", 405, "METHOD_NOT_ALLOWED")

    @app.errorhandler(413)
    def request_entity_too_large(e):
        return error_response(
            "Upload exceeds maximum allowed size",
            413,
            "FILE_TOO_LARGE",
        )

    @app.errorhandler(429)
    def too_many_requests(e):
        return error_response("Rate limit exceeded", 429, "RATE_LIMITED")

    @app.errorhandler(500)
    def internal_error(e):
        import logging
        logging.getLogger(__name__).exception("Unhandled server error")
        return error_response("Internal server error", 500, "INTERNAL_ERROR")
