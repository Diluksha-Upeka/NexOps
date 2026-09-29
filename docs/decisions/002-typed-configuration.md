# ADR-002: Typed Configuration with Pydantic Settings

**Status:** Accepted  
**Date:** 2026-09-29  
**Context:** How to handle application configuration, secrets, and environment-specific values.

## Decision

Use `pydantic-settings` to parse all configuration from environment variables (with `.env` fallback in development). Settings are validated at startup; invalid values cause immediate failure. Secrets use `SecretStr` for automatic redaction.

## Rationale

- Fail-fast on invalid config prevents silent runtime errors.
- `SecretStr` ensures API keys never appear in logs or string representations.
- A single `Settings` class is the source of truth for all configuration.
- `.env.example` is committed; `.env` is gitignored — secrets stay out of version control.

## Consequences

- Every new configuration value must be added to `Settings` and `.env.example`.
- Tests can override settings via `monkeypatch` without touching real environment files.
- Provider-specific settings (LLM keys, model names) are optional and only validated when that provider is active.
