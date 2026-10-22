"""
Unit tests for configuration system.

Tests verify:
- Environment selection logic
- Setting values and defaults
- Validation rules (e.g., weak secret key rejected in production)
- Flask config dict generation
"""
from __future__ import annotations

import pytest


@pytest.mark.unit
class TestTestingSettings:
    """Tests for the TestingSettings configuration class."""

    def test_testing_settings_uses_in_memory_sqlite(self):
        from config.settings import get_testing_settings
        s = get_testing_settings()
        assert s.database_url == "sqlite:///:memory:"

    def test_testing_settings_flag_is_true(self):
        from config.settings import get_testing_settings
        s = get_testing_settings()
        assert s.testing is True

    def test_testing_settings_flask_config_has_testing_key(self):
        from config.settings import get_testing_settings
        s = get_testing_settings()
        cfg = s.to_flask_config()
        assert cfg["TESTING"] is True
        assert cfg["SQLALCHEMY_DATABASE_URI"] == "sqlite:///:memory:"

    def test_testing_settings_rate_limit_is_permissive(self):
        from config.settings import get_testing_settings
        s = get_testing_settings()
        assert "99999" in s.ratelimit_default


@pytest.mark.unit
class TestDevelopmentSettings:
    """Tests for the DevelopmentSettings configuration class."""

    def test_development_settings_loads(self):
        from config.settings import DevelopmentSettings
        s = DevelopmentSettings()
        assert s is not None

    def test_development_log_level_is_debug(self):
        from config.settings import DevelopmentSettings
        s = DevelopmentSettings()
        assert s.log_level == "DEBUG"

    def test_allowed_extension_set(self):
        from config.settings import DevelopmentSettings
        s = DevelopmentSettings()
        exts = s.allowed_extension_set
        assert "csv" in exts
        assert "pcap" in exts
        assert "pcapng" in exts

    def test_cors_origin_list(self):
        from config.settings import DevelopmentSettings
        s = DevelopmentSettings()
        origins = s.cors_origin_list
        assert isinstance(origins, list)
        assert len(origins) >= 1


@pytest.mark.unit
class TestProductionSettings:
    """Tests for ProductionSettings validation."""

    def test_weak_secret_key_is_rejected(self):
        from pydantic import ValidationError

        from config.settings import ProductionSettings
        with pytest.raises((ValidationError, ValueError)):
            ProductionSettings(
                secret_key="dev-secret-key-change-in-production",
                database_url="postgresql://user:pass@host/db",
            )

    def test_short_secret_key_is_rejected(self):
        from pydantic import ValidationError

        from config.settings import ProductionSettings
        with pytest.raises((ValidationError, ValueError)):
            ProductionSettings(
                secret_key="tooshort",
                database_url="postgresql://user:pass@host/db",
            )

    def test_sqlite_db_url_is_rejected_in_production(self):
        from pydantic import ValidationError

        from config.settings import ProductionSettings
        with pytest.raises((ValidationError, ValueError)):
            ProductionSettings(
                secret_key="a" * 64,
                database_url="sqlite:///trafficshield.db",
            )

    def test_valid_production_settings(self):
        from config.settings import ProductionSettings
        s = ProductionSettings(
            secret_key="a" * 64,
            database_url="postgresql://user:pass@localhost/trafficshield",
        )
        assert s.session_cookie_secure is True


@pytest.mark.unit
class TestSettingsHelpers:
    """Tests for settings helper methods."""

    def test_log_level_is_normalized_uppercase(self):
        from config.settings import DevelopmentSettings
        s = DevelopmentSettings(log_level="debug")
        assert s.log_level == "DEBUG"

    def test_invalid_log_level_raises(self):
        from pydantic import ValidationError

        from config.settings import DevelopmentSettings
        with pytest.raises((ValidationError, ValueError)):
            DevelopmentSettings(log_level="VERBOSE")

    def test_flask_config_has_required_keys(self):
        from config.settings import get_testing_settings
        cfg = get_testing_settings().to_flask_config()
        assert "SECRET_KEY" in cfg
        assert "SQLALCHEMY_DATABASE_URI" in cfg
        assert "SQLALCHEMY_TRACK_MODIFICATIONS" in cfg
        assert cfg["SQLALCHEMY_TRACK_MODIFICATIONS"] is False
