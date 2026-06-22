"""Configuration from environment variables.

Nothing here is provider- or secret-specific at import time: values come from the
environment (loaded from a local, gitignored ``.env`` during development).
"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_file() -> str:
    """Which .env to load. Default is the local snapshot profile; set
    ``STUDIO_ENV_FILE=.env.live`` to point at the live (read-only) production DB.
    """
    return os.getenv("STUDIO_ENV_FILE", ".env")


class DBSettings(BaseSettings):
    """Connection to the LOCAL MySQL copy of the PMS snapshot. Read-only by intent."""

    model_config = SettingsConfigDict(env_prefix="DB_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "studio_ro"
    password: str = "studio_ro_pw"
    name: str = "studio_pms"
    # Tables are latin1, but we connect as utf8mb4 so MySQL converts text
    # server-side. The strict client-side cp1252 codec (what charset="latin1"
    # uses) raises on bytes undefined in cp1252 (0x81/0x8d/0x8f/0x90/0x9d), which
    # real rows contain; utf8mb4 is lenient. Double-encoded rows are still
    # repaired in the repository.
    charset: str = "utf8mb4"


class LLMSettings(BaseSettings):
    """Any OpenAI-compatible endpoint. The provider is whatever ``base_url`` points at."""

    model_config = SettingsConfigDict(env_prefix="OPENAI_", env_file=".env", extra="ignore")

    # Defaults target Google Gemini's free, OpenAI-compatible endpoint; override
    # in .env to point at any other provider or a local open-model server.
    base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    api_key: str = ""
    model: str = "gemini-2.5-flash"


class NotionSettings(BaseSettings):
    """Read-only Notion access (incoming briefs). Empty token = Notion disabled."""

    model_config = SettingsConfigDict(env_prefix="NOTION_", env_file=".env", extra="ignore")

    token: str = ""
    # Comma-separated Notion database ids holding incoming briefs. Defaults to the
    # RO Design / Development task boards under the team's Notion homebase.
    briefs_dbs: str = (
        "14b35e67-7f07-802e-b271-e98a8240e65e,"
        "14b35e67-7f07-8051-83c6-db499173f309"
    )


@lru_cache
def notion_settings() -> NotionSettings:
    return NotionSettings(_env_file=_env_file())


class WebAuthSettings(BaseSettings):
    """Optional HTTP Basic Auth for the local web UI/API. Empty = no auth."""

    model_config = SettingsConfigDict(env_prefix="WEB_AUTH_", env_file=".env", extra="ignore")

    user: str = ""
    password: str = ""


@lru_cache
def web_auth() -> tuple[str, str] | None:
    s = WebAuthSettings(_env_file=_env_file())
    return (s.user, s.password) if s.user and s.password else None


@lru_cache
def db_settings() -> DBSettings:
    return DBSettings(_env_file=_env_file())


@lru_cache
def llm_settings() -> LLMSettings:
    return LLMSettings(_env_file=_env_file())
