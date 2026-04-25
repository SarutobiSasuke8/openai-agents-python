"""Settings — all values read from environment variables at startup.

Single-key deployment via OpenRouter (OpenAI-compatible, 200+ models):
    export OPENAI_API_KEY=sk-or-v1-...          # your OpenRouter key
    export OPENAI_BASE_URL=https://openrouter.ai/api/v1
    export DEFAULT_MODEL=anthropic/claude-sonnet-4-6
    export DEFAULT_MODEL_FAST=anthropic/claude-haiku-4-5

Via LiteLLM (install: uv sync --extra litellm):
    export ANTHROPIC_API_KEY=sk-ant-...
    export DEFAULT_MODEL=litellm/anthropic/claude-sonnet-4-6
    export DEFAULT_MODEL_FAST=litellm/anthropic/claude-haiku-4-5-20251001
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    db_path: str = field(default_factory=lambda: os.getenv("PRODUCT_DB_PATH", "product.db"))
    default_model: str = field(default_factory=lambda: os.getenv("DEFAULT_MODEL", "gpt-4o"))
    default_model_fast: str = field(
        default_factory=lambda: os.getenv("DEFAULT_MODEL_FAST", "gpt-4o-mini")
    )
    max_turns_default: int = field(
        default_factory=lambda: int(os.getenv("MAX_TURNS_DEFAULT", "10"))
    )
    admin_key: str = field(default_factory=lambda: os.getenv("ADMIN_KEY", "changeme"))
    host: str = field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))


settings = Settings()
