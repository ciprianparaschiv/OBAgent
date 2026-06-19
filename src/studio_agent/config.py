"""Configuration from environment variables.

Nothing here is provider- or secret-specific at import time: values come from the
environment (loaded from a local, gitignored ``.env`` during development).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class DBSettings(BaseSettings):
    """Connection to the LOCAL MySQL copy of the PMS snapshot. Read-only by intent."""

    model_config = SettingsConfigDict(env_prefix="DB_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "studio_ro"
    password: str = "studio_ro_pw"
    name: str = "studio_pms"
    # Legacy PMS rows may be stored as latin1; default accordingly but overridable.
    charset: str = "latin1"


class LLMSettings(BaseSettings):
    """Any OpenAI-compatible endpoint. The provider is whatever ``base_url`` points at."""

    model_config = SettingsConfigDict(env_prefix="OPENAI_", env_file=".env", extra="ignore")

    # Defaults target Google Gemini's free, OpenAI-compatible endpoint; override
    # in .env to point at any other provider or a local open-model server.
    base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    api_key: str = ""
    model: str = "gemini-2.5-flash"


@lru_cache
def db_settings() -> DBSettings:
    return DBSettings()


@lru_cache
def llm_settings() -> LLMSettings:
    return LLMSettings()
