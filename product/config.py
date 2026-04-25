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
