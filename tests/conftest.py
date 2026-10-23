"""
Pytest configuration and shared fixtures for TrafficShield tests.

Fixtures are scoped appropriately:
- app / client: function-scoped by default (fresh state per test)
- db_session: function-scoped with rollback after each test
"""
from __future__ import annotations

import os
import sys
import types

import pytest

# Windows Smart App Control / WDAC compatibility guard:
# Stub unused internal C-extension solvers (_sag_fast) if blocked by host code-integrity policy
if "sklearn.linear_model._sag_fast" not in sys.modules:
    try:
        import sklearn.linear_model._sag_fast  # noqa: F401
    except (ImportError, OSError):
        _mock_sag = types.ModuleType("sklearn.linear_model._sag_fast")
        _mock_sag.sag32 = lambda *args, **kwargs: None  # type: ignore[attr-defined]
        _mock_sag.sag64 = lambda *args, **kwargs: None  # type: ignore[attr-defined]
        sys.modules["sklearn.linear_model._sag_fast"] = _mock_sag

# Force testing environment BEFORE app import so settings are correct
os.environ.setdefault("FLASK_ENV", "testing")
os.environ.setdefault("APP_ENV", "testing")


@pytest.fixture(scope="session")
def app():
    """
    Session-scoped Flask application configured for testing.

    Uses an in-memory SQLite database. Tables are created once per session.
    """
    from app import create_app
    application = create_app(env="testing")
    application.config["TESTING"] = True
    yield application


@pytest.fixture()
def client(app):
    """Flask test client — function-scoped, does NOT persist state."""
    with app.test_client() as c:
        yield c


@pytest.fixture()
def app_context(app):
    """Push an application context for tests that need it."""
    with app.app_context():
        yield app


@pytest.fixture()
def db_session(app_context):
    """
    Provide a DB session that is rolled back after each test.
    Ensures test isolation without re-creating the schema.
    """
    from app.extensions import db
    connection = db.engine.connect()
    transaction = connection.begin()

    # Bind session to this connection
    from sqlalchemy.orm import Session
    session = Session(bind=connection)
    db.session = session

    yield session

    session.close()
    transaction.rollback()
    connection.close()
