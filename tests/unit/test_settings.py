"""Unit tests for settings and configuration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.settings import Settings


class TestSettings:
    """Verify typed settings load correctly and apply defaults."""

    def test_defaults(self) -> None:
        """Default settings should produce a valid development config."""
        settings = Settings()
        assert settings.app_env == "development"
        assert settings.app_host == "127.0.0.1"
        assert settings.app_port == 8000
        assert settings.llm_provider == "fake"
        assert settings.simulator_enabled is True
        assert settings.is_development is True
        assert settings.graph_max_rounds == 2

    def test_port_validation(self) -> None:
        """Port must be within valid TCP range."""
        with pytest.raises(ValidationError):
            Settings(app_port=0)
        with pytest.raises(ValidationError):
            Settings(app_port=70000)

    def test_secret_redaction(self) -> None:
        """API key must not appear in string representation."""
        settings = Settings(llm_api_key="sk-super-secret-key")
        settings_str = str(settings.llm_api_key)
        assert "sk-super-secret-key" not in settings_str

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Environment variables should override defaults."""
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("APP_PORT", "9000")
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        settings = Settings()
        assert settings.app_env == "production"
        assert settings.app_port == 9000
        assert settings.llm_provider == "openai"
        assert settings.is_development is False
