"""Provider-agnostic model access.

The model is reached through an OpenAI-compatible endpoint. The provider is
whatever ``OPENAI_BASE_URL`` points at (Anthropic for dev, a local open-model
server for prod) — nothing here is provider-specific. Swapping providers is a
config change, never a code change.
"""

from __future__ import annotations

from openai import OpenAI

from .config import llm_settings


def make_client() -> OpenAI:
    cfg = llm_settings()
    if not cfg.api_key or cfg.api_key.startswith("sk-REPLACE"):
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Copy .env.example to .env and fill it in."
        )
    return OpenAI(base_url=cfg.base_url, api_key=cfg.api_key)


def model_name() -> str:
    return llm_settings().model
