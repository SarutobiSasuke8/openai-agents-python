"""CRUD helpers for tenants, agent definitions, and run records."""

from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

from .database import get_db
from .models import AgentConfig, AgentDefCreate, AgentDefUpdate, HandoffConfig


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Tenants
# ---------------------------------------------------------------------------


async def create_tenant(name: str) -> dict[str, Any]:
    tenant_id = str(uuid.uuid4())
    api_key = secrets.token_urlsafe(32)
    async with get_db() as db:
        await db.execute(
            "INSERT INTO tenants (id, api_key, name) VALUES (?, ?, ?)",
            (tenant_id, api_key, name),
        )
        await db.commit()
    return {"id": tenant_id, "name": name, "api_key": api_key, "created_at": _now()}


async def get_tenant_by_key(api_key: str) -> dict[str, Any] | None:
    async with get_db() as db:
        async with db.execute(
            "SELECT id, name, is_active, created_at FROM tenants WHERE api_key = ?",
            (api_key,),
        ) as cur:
            row = await cur.fetchone()
    if row is None or not row["is_active"]:
        return None
    return dict(row)


# ---------------------------------------------------------------------------
# Agent definitions
# ---------------------------------------------------------------------------


async def create_agent_def(tenant_id: str, body: AgentDefCreate) -> dict[str, Any]:
    defn_id = str(uuid.uuid4())
    now = _now()
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO agent_definitions
                (id, tenant_id, slug, name, instructions, model,
                 tools_json, handoffs_json, config_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                defn_id,
                tenant_id,
                body.slug,
                body.name,
                body.instructions,
                body.model,
                json.dumps(body.tools),
                json.dumps([h.model_dump() for h in body.handoffs]),
                json.dumps(body.config.model_dump()),
                now,
                now,
            ),
        )
        await db.commit()
    return await get_agent_def(tenant_id, body.slug)  # type: ignore[return-value]


async def get_agent_def(tenant_id: str, slug: str) -> dict[str, Any] | None:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM agent_definitions WHERE tenant_id = ? AND slug = ?",
            (tenant_id, slug),
        ) as cur:
            row = await cur.fetchone()
    return dict(row) if row else None


async def list_agent_defs(tenant_id: str) -> list[dict[str, Any]]:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM agent_definitions WHERE tenant_id = ? ORDER BY created_at",
            (tenant_id,),
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def update_agent_def(
    tenant_id: str, slug: str, body: AgentDefUpdate
) -> dict[str, Any] | None:
    existing = await get_agent_def(tenant_id, slug)
    if existing is None:
        return None

    # Merge update fields over existing values.
    fields: dict[str, Any] = {
        "name": body.name if body.name is not None else existing["name"],
        "instructions": body.instructions
        if body.instructions is not None
        else existing["instructions"],
        "model": body.model if body.model is not None else existing["model"],
        "tools_json": json.dumps(body.tools) if body.tools is not None else existing["tools_json"],
        "handoffs_json": (
            json.dumps([h.model_dump() for h in body.handoffs])
            if body.handoffs is not None
            else existing["handoffs_json"]
        ),
        "config_json": (
            json.dumps(body.config.model_dump())
            if body.config is not None
            else existing["config_json"]
        ),
        "updated_at": _now(),
    }

    async with get_db() as db:
        await db.execute(
            """
            UPDATE agent_definitions
            SET name=:name, instructions=:instructions, model=:model,
                tools_json=:tools_json, handoffs_json=:handoffs_json,
                config_json=:config_json, updated_at=:updated_at
            WHERE tenant_id=:tenant_id AND slug=:slug
            """,
            {**fields, "tenant_id": tenant_id, "slug": slug},
        )
        await db.commit()
    return await get_agent_def(tenant_id, slug)


async def delete_agent_def(tenant_id: str, slug: str) -> bool:
    async with get_db() as db:
        cur = await db.execute(
            "DELETE FROM agent_definitions WHERE tenant_id = ? AND slug = ?",
            (tenant_id, slug),
        )
        await db.commit()
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


async def create_run(
    tenant_id: str,
    agent_slug: str,
    input_text: str,
    session_id: str | None,
) -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    now = _now()
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO runs
                (id, tenant_id, agent_slug, session_id, input_text, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """,
            (run_id, tenant_id, agent_slug, session_id, input_text, now),
        )
        await db.commit()
    return {
        "id": run_id,
        "tenant_id": tenant_id,
        "agent_slug": agent_slug,
        "session_id": session_id,
        "input_text": input_text,
        "status": "pending",
        "output_text": None,
        "tokens_used": None,
        "error_message": None,
        "created_at": now,
        "completed_at": None,
    }


async def update_run(
    run_id: str,
    *,
    status: str,
    output_text: str | None = None,
    tokens_used: int | None = None,
    error_message: str | None = None,
) -> None:
    async with get_db() as db:
        await db.execute(
            """
            UPDATE runs SET
                status=?, output_text=?, tokens_used=?,
                error_message=?, completed_at=?
            WHERE id=?
            """,
            (status, output_text, tokens_used, error_message, _now(), run_id),
        )
        await db.commit()


async def get_run(tenant_id: str, run_id: str) -> dict[str, Any] | None:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM runs WHERE id = ? AND tenant_id = ?",
            (run_id, tenant_id),
        ) as cur:
            row = await cur.fetchone()
    return dict(row) if row else None


def _row_to_agent_response(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw DB row into the AgentDefResponse shape."""
    return {
        "id": row["id"],
        "slug": row["slug"],
        "name": row["name"],
        "instructions": row["instructions"],
        "model": row["model"],
        "tools": json.loads(row["tools_json"]),
        "handoffs": [HandoffConfig(**h) for h in json.loads(row["handoffs_json"])],
        "config": AgentConfig(**json.loads(row["config_json"])),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def format_agent_response(row: dict[str, Any]) -> dict[str, Any]:
    return _row_to_agent_response(row)
