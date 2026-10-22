"""
Consistent JSON response helpers for TrafficShield API.

All API endpoints must use these helpers to ensure a uniform response envelope:

    {
        "success": true | false,
        "data":    <payload>,       # present on success
        "error":   <error_info>,    # present on failure
        "meta":    <optional_meta>  # pagination, timing, etc.
    }
"""
from __future__ import annotations

from http import HTTPStatus
from typing import Any, Optional

from flask import jsonify


def success_response(
    data: Any = None,
    message: Optional[str] = None,
    status_code: int = HTTPStatus.OK,
    meta: Optional[dict] = None,
):
    """Return a JSON success response."""
    body: dict[str, Any] = {"success": True}
    if data is not None:
        body["data"] = data
    if message is not None:
        body["message"] = message
    if meta is not None:
        body["meta"] = meta
    return jsonify(body), status_code


def error_response(
    message: str,
    status_code: int = HTTPStatus.BAD_REQUEST,
    error_code: Optional[str] = None,
    details: Optional[Any] = None,
):
    """Return a JSON error response."""
    body: dict[str, Any] = {
        "success": False,
        "error": {
            "message": message,
        },
    }
    if error_code is not None:
        body["error"]["code"] = error_code
    if details is not None:
        body["error"]["details"] = details
    return jsonify(body), status_code


def paginated_response(
    items: list,
    total: int,
    page: int,
    per_page: int,
    status_code: int = HTTPStatus.OK,
):
    """Return a paginated JSON response."""
    return success_response(
        data=items,
        status_code=status_code,
        meta={
            "pagination": {
                "total": total,
                "page": page,
                "per_page": per_page,
                "pages": max(1, -(-total // per_page)),  # ceiling division
            }
        },
    )
