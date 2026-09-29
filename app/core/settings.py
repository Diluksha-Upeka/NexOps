"""Typed application settings parsed from environment variables.

Settings are loaded once at startup via Pydantic Settings. The application
fails fast if required values are missing or invalid, and secrets are
redacted in any string representation.
"""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration — all values come from environment or `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application ---
    app_env: str = Field(default="development", description="Running environment.")
    app_host: str = Field(default="127.0.0.1", description="Bind address.")
    app_port: int = Field(default=8000, ge=1, le=65535, description="Bind port.")

    # --- Database ---
    database_url: str = Field(
        default="postgresql+psycopg://incident_app:change-me@localhost:5432/incident_lab",
        description="SQLAlchemy async connection string.",
    )

    # --- LLM Provider ---
    llm_provider: str = Field(default="fake", description="LLM provider name or 'fake'.")
    llm_model: str = Field(default="", description="Model identifier.")
    llm_api_key: SecretStr = Field(
        default=SecretStr(""), description="Provider API key (redacted)."
    )
    llm_base_url: str = Field(default="", description="Optional custom base URL.")

    # --- Graph ---
    graph_max_rounds: int = Field(default=2, ge=1, le=10, description="Max investigation rounds.")
    graph_timeout_seconds: int = Field(default=90, ge=10, description="Graph-level timeout.")
    tool_timeout_seconds: int = Field(default=10, ge=1, description="Per-tool timeout.")

    # --- Simulator ---
    simulator_enabled: bool = Field(default=True, description="Enable simulator routes.")
    simulator_max_fault_seconds: int = Field(default=300, ge=10, description="Max fault TTL.")

    # --- Frontend ---
    frontend_origin: str = Field(
        default="http://localhost:5173",
        description="Allowed CORS origin for the frontend.",
    )

    # --- Observability ---
    otel_exporter_otlp_endpoint: str = Field(
        default="http://localhost:4318",
        description="OTLP exporter endpoint (later phases).",
    )

    # --- Logging ---
    log_level: str = Field(default="INFO", description="Root log level.")

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


def get_settings() -> Settings:
    """Construct settings from the environment. Call once at startup."""
    return Settings()
