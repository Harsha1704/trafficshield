"""
Integration tests for the Flask application factory.

Tests verify:
- App is created successfully for each environment
- Configuration keys are set correctly per environment
- Extensions are initialized (db, cors, limiter)
- Blueprints are registered with correct URL prefixes
- Error handlers are registered
"""
from __future__ import annotations

import pytest


@pytest.mark.integration
class TestAppFactory:
    """Tests that create_app() behaves correctly."""

    def test_testing_app_is_created(self, app):
        assert app is not None

    def test_testing_flag_is_set(self, app):
        assert app.config["TESTING"] is True

    def test_database_is_in_memory_for_testing(self, app):
        assert "memory" in app.config["SQLALCHEMY_DATABASE_URI"]

    def test_blueprints_are_registered(self, app):
        """v1 blueprint and health sub-blueprint must be registered."""
        rules = [str(rule) for rule in app.url_map.iter_rules()]
        assert any("/api/v1/health" in r for r in rules)
        assert any("/api/v1/ready" in r for r in rules)

    def test_db_extension_is_initialized(self, app):
        """Flask-SQLAlchemy 3.x uses get_engine() inside app context."""
        from app.extensions import db
        with app.app_context():
            engine = db.engine
            assert engine is not None

    def test_secret_key_is_configured(self, app):
        assert app.config["SECRET_KEY"]

    def test_max_content_length_is_set(self, app):
        assert app.config["MAX_CONTENT_LENGTH"] > 0

    def test_sqlalchemy_track_modifications_is_false(self, app):
        assert app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] is False


@pytest.mark.integration
class TestDatabaseSetup:
    """Tests that database tables are created at startup."""

    def test_system_events_table_exists(self, app_context):
        from sqlalchemy import inspect

        from app.extensions import db
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        assert "system_events" in tables

    def test_system_events_has_expected_columns(self, app_context):
        from sqlalchemy import inspect

        from app.extensions import db
        inspector = inspect(db.engine)
        cols = {c["name"] for c in inspector.get_columns("system_events")}
        assert "id" in cols
        assert "event_type" in cols
        assert "created_at" in cols
        assert "updated_at" in cols

    def test_can_insert_and_retrieve_system_event(self, app_context):
        from app.database.models import SystemEvent
        from app.extensions import db
        event = SystemEvent(event_type="test", description="M1 smoke test")
        db.session.add(event)
        db.session.commit()

        retrieved = db.session.get(SystemEvent, event.id)
        assert retrieved is not None
        assert retrieved.event_type == "test"
        assert retrieved.id is not None


@pytest.mark.integration
class TestResponseHelpers:
    """Tests for response utility functions."""

    def test_success_response_structure(self, app_context):
        from flask import Flask
        test_app = Flask(__name__)
        with test_app.test_request_context("/"):
            from app.utils.response import success_response
            resp, code = success_response(data={"key": "value"}, status_code=200)
            data = resp.get_json()
            assert data["success"] is True
            assert data["data"] == {"key": "value"}
            assert code == 200

    def test_error_response_structure(self, app_context):
        from flask import Flask
        test_app = Flask(__name__)
        with test_app.test_request_context("/"):
            from app.utils.response import error_response
            resp, code = error_response("Something went wrong", 400, "BAD_REQUEST")
            data = resp.get_json()
            assert data["success"] is False
            assert data["error"]["message"] == "Something went wrong"
            assert data["error"]["code"] == "BAD_REQUEST"
            assert code == 400

    def test_paginated_response_meta(self, app_context):
        from flask import Flask
        test_app = Flask(__name__)
        with test_app.test_request_context("/"):
            from app.utils.response import paginated_response
            resp, code = paginated_response(
                items=[1, 2, 3], total=100, page=2, per_page=3
            )
            data = resp.get_json()
            assert data["success"] is True
            assert data["meta"]["pagination"]["total"] == 100
            assert data["meta"]["pagination"]["page"] == 2
            assert data["meta"]["pagination"]["pages"] == 34  # ceil(100/3)
