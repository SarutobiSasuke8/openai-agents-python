"""SQLite persistence layer using aiosqlite."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aiosqlite

from .config import settings

# DDL — product tables only; the SDK's SQLiteSession manages its own tables.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    id          TEXT PRIMARY KEY,
    api_key     TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agent_definitions (
    id           TEXT PRIMARY KEY,
    tenant_id    TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    slug         TEXT NOT NULL,
    name         TEXT NOT NULL,
    instructions TEXT NOT NULL,
    model        TEXT,
    tools_json   TEXT NOT NULL DEFAULT '[]',
    handoffs_json TEXT NOT NULL DEFAULT '[]',
    config_json  TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(tenant_id, slug)
);

CREATE TABLE IF NOT EXISTS runs (
    id            TEXT PRIMARY KEY,
    tenant_id     TEXT NOT NULL REFERENCES tenants(id),
    agent_slug    TEXT NOT NULL,
    session_id    TEXT,
    input_text    TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    output_text   TEXT,
    tokens_used   INTEGER,
    error_message TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_defs_tenant
    ON agent_definitions(tenant_id);

CREATE INDEX IF NOT EXISTS idx_runs_tenant_agent
    ON runs(tenant_id, agent_slug);
"""


async def init_db() -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.executescript(_SCHEMA)
        await db.commit()


@asynccontextmanager
async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        yield db
