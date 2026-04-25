"""FastAPI application — the product API surface.

Routes
------
Admin (X-Admin-Key header):
  POST /v1/admin/tenants          Provision a new tenant + API key

Agent definitions (Bearer <api_key>):
  GET    /v1/agents               List all agents for the tenant
  POST   /v1/agents               Create an agent definition
  GET    /v1/agents/{slug}        Fetch one agent definition
  PUT    /v1/agents/{slug}        Update an agent definition
  DELETE /v1/agents/{slug}        Delete an agent definition

Execution (Bearer <api_key>):
  POST   /v1/agents/{slug}/run          Sync run — returns when complete
  POST   /v1/agents/{slug}/run/stream   Streaming run — returns SSE events

Run history:
  GET    /v1/runs/{run_id}        Fetch a completed run record

Utilities:
  GET    /v1/tools                List all registered tools
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import StreamingResponse

from agents import Runner
from agents.memory.sqlite_session import SQLiteSession
from agents.stream_events import (
    AgentUpdatedStreamEvent,
    RawResponsesStreamEvent,
    RunItemStreamEvent,
)

from .auth import AdminDep, TenantDep
from .builder import build_agent
from .config import settings
from .database import init_db
from .models import (
    AgentDefCreate,
    AgentDefResponse,
    AgentDefUpdate,
    RunRequest,
    RunResponse,
    TenantCreate,
    TenantResponse,
    ToolInfo,
)
from .registry import (
    create_agent_def,
    create_run,
    create_tenant,
    delete_agent_def,
    format_agent_response,
    get_agent_def,
    get_run,
    list_agent_defs,
    update_agent_def,
    update_run,
)
from .tools import list_tools


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    yield


app = FastAPI(
    title="Multi-Agent Platform",
    description=(
        "Variable-application multi-agent framework built on the OpenAI Agents SDK. "
        "Define agents as JSON, wire handoffs by slug, and run them via REST or SSE."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------


@app.post(
    "/v1/admin/tenants",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["admin"],
)
async def provision_tenant(_: AdminDep, body: TenantCreate) -> TenantResponse:
    """Create a new tenant and return its API key. Keep the key secret."""
    row = await create_tenant(body.name)
    return TenantResponse(**row)


# ---------------------------------------------------------------------------
# Agent definitions
# ---------------------------------------------------------------------------


@app.get("/v1/agents", response_model=list[AgentDefResponse], tags=["agents"])
async def list_agents(tenant: TenantDep) -> list[AgentDefResponse]:
    rows = await list_agent_defs(tenant["id"])
    return [AgentDefResponse(**format_agent_response(r)) for r in rows]


@app.post(
    "/v1/agents",
    response_model=AgentDefResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["agents"],
)
async def create_agent(tenant: TenantDep, body: AgentDefCreate) -> AgentDefResponse:
    existing = await get_agent_def(tenant["id"], body.slug)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Agent with slug '{body.slug}' already exists.",
        )
    row = await create_agent_def(tenant["id"], body)
    return AgentDefResponse(**format_agent_response(row))


@app.get("/v1/agents/{slug}", response_model=AgentDefResponse, tags=["agents"])
async def get_agent(tenant: TenantDep, slug: str) -> AgentDefResponse:
    row = await get_agent_def(tenant["id"], slug)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Agent '{slug}' not found.")
    return AgentDefResponse(**format_agent_response(row))


@app.put("/v1/agents/{slug}", response_model=AgentDefResponse, tags=["agents"])
async def update_agent(tenant: TenantDep, slug: str, body: AgentDefUpdate) -> AgentDefResponse:
    row = await update_agent_def(tenant["id"], slug, body)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Agent '{slug}' not found.")
    return AgentDefResponse(**format_agent_response(row))


@app.delete("/v1/agents/{slug}", status_code=status.HTTP_204_NO_CONTENT, tags=["agents"])
async def delete_agent(tenant: TenantDep, slug: str) -> None:
    deleted = await delete_agent_def(tenant["id"], slug)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Agent '{slug}' not found.")


# ---------------------------------------------------------------------------
# Execution — sync run
# ---------------------------------------------------------------------------


@app.post("/v1/agents/{slug}/run", response_model=RunResponse, tags=["runs"])
async def run_agent(tenant: TenantDep, slug: str, body: RunRequest) -> RunResponse:
    """Execute a run synchronously. Blocks until the agent finishes."""
    defn = await get_agent_def(tenant["id"], slug)
    if defn is None:
        raise HTTPException(status_code=404, detail=f"Agent '{slug}' not found.")

    agent_config = json.loads(defn["config_json"])
    max_turns = body.max_turns or agent_config.get("max_turns") or settings.max_turns_default
    session_id = body.session_id or str(uuid.uuid4())

    run_row = await create_run(tenant["id"], slug, body.input, session_id)

    agent = build_agent(
        defn,
        tenant["id"],
        template_var_overrides=body.template_vars or None,
        model_override=body.model,
    )
    session = SQLiteSession(session_id=session_id, db_path=settings.db_path)

    try:
        result = await Runner.run(agent, body.input, max_turns=max_turns, session=session)
        output = str(result.final_output) if result.final_output is not None else ""
        tokens = _extract_tokens(result)
        await update_run(
            run_row["id"],
            status="completed",
            output_text=output,
            tokens_used=tokens,
        )
        return _make_run_response(run_row, "completed", output, tokens, None)
    except Exception as exc:
        err = str(exc)
        await update_run(run_row["id"], status="failed", error_message=err)
        raise HTTPException(status_code=500, detail=err) from exc


# ---------------------------------------------------------------------------
# Execution — streaming SSE run
# ---------------------------------------------------------------------------


@app.post("/v1/agents/{slug}/run/stream", tags=["runs"])
async def stream_agent(tenant: TenantDep, slug: str, body: RunRequest) -> StreamingResponse:
    """Execute a run and stream Server-Sent Events back to the client.

    Event types:
      agent_start   — agent name that started or resumed
      text_delta    — incremental text from the model
      tool_called   — a tool was invoked
      handoff       — conversation handed off to another agent
      done          — final output; includes run_id and session_id
      error         — run failed
    """
    defn = await get_agent_def(tenant["id"], slug)
    if defn is None:
        raise HTTPException(status_code=404, detail=f"Agent '{slug}' not found.")

    agent_config = json.loads(defn["config_json"])
    max_turns = body.max_turns or agent_config.get("max_turns") or settings.max_turns_default
    session_id = body.session_id or str(uuid.uuid4())

    run_row = await create_run(tenant["id"], slug, body.input, session_id)

    agent = build_agent(
        defn,
        tenant["id"],
        template_var_overrides=body.template_vars or None,
        model_override=body.model,
    )
    session = SQLiteSession(session_id=session_id, db_path=settings.db_path)

    return StreamingResponse(
        _sse_generator(agent, body.input, max_turns, session, run_row, session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _sse_generator(
    agent: Any,
    input_text: str,
    max_turns: int,
    session: SQLiteSession,
    run_row: dict[str, Any],
    session_id: str,
) -> AsyncIterator[str]:
    run_id = run_row["id"]
    output_chunks: list[str] = []

    try:
        result = Runner.run_streamed(agent, input_text, max_turns=max_turns, session=session)

        async for event in result.stream_events():
            if isinstance(event, AgentUpdatedStreamEvent):
                yield _sse("agent_start", {"agent": event.new_agent.name})

            elif isinstance(event, RawResponsesStreamEvent):
                raw = event.data
                # Text delta — extract from OpenAI response stream events.
                if getattr(raw, "type", None) == "response.output_text.delta":
                    delta: str = getattr(raw, "delta", "")
                    if delta:
                        output_chunks.append(delta)
                        yield _sse("text_delta", {"text": delta})

            elif isinstance(event, RunItemStreamEvent):
                if event.name == "tool_called":
                    item = event.item
                    tool_name = getattr(item, "name", None) or getattr(item, "tool_name", "unknown")
                    yield _sse("tool_called", {"tool": tool_name})
                elif event.name in ("handoff_requested", "handoff_occured"):
                    item = event.item
                    target = getattr(item, "agent_name", None) or getattr(item, "target", "unknown")
                    yield _sse("handoff", {"target_agent": target})

        output = "".join(output_chunks) or (
            str(result.final_output) if result.final_output is not None else ""
        )
        tokens = _extract_tokens(result)
        await update_run(run_row["id"], status="completed", output_text=output, tokens_used=tokens)
        yield _sse(
            "done",
            {
                "run_id": run_id,
                "session_id": session_id,
                "output": output,
                "tokens_used": tokens,
            },
        )

    except Exception as exc:
        err = str(exc)
        await update_run(run_id, status="failed", error_message=err)
        yield _sse("error", {"run_id": run_id, "message": err})


# ---------------------------------------------------------------------------
# Run history
# ---------------------------------------------------------------------------


@app.get("/v1/runs/{run_id}", response_model=RunResponse, tags=["runs"])
async def get_run_record(tenant: TenantDep, run_id: str) -> RunResponse:
    row = await get_run(tenant["id"], run_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
    return RunResponse(
        run_id=row["id"],
        agent_slug=row["agent_slug"],
        session_id=row["session_id"],
        status=row["status"],
        output=row["output_text"],
        tokens_used=row["tokens_used"],
        error=row["error_message"],
        created_at=row["created_at"],
        completed_at=row["completed_at"],
    )


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


@app.get("/v1/tools", response_model=list[ToolInfo], tags=["tools"])
async def get_tools(_: TenantDep) -> list[ToolInfo]:
    """List all tools that can be referenced in agent definitions."""
    return [ToolInfo(**t) for t in list_tools()]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _extract_tokens(result: Any) -> int | None:
    try:
        usage = result.raw_responses[-1].usage if result.raw_responses else None
        if usage:
            return getattr(usage, "total_tokens", None) or (
                getattr(usage, "input_tokens", 0) + getattr(usage, "output_tokens", 0)
            )
    except Exception:
        pass
    return None


def _make_run_response(
    run_row: dict[str, Any],
    status_str: str,
    output: str | None,
    tokens: int | None,
    error: str | None,
) -> RunResponse:
    return RunResponse(
        run_id=run_row["id"],
        agent_slug=run_row["agent_slug"],
        session_id=run_row["session_id"],
        status=status_str,
        output=output,
        tokens_used=tokens,
        error=error,
        created_at=run_row["created_at"],
        completed_at=None,
    )
