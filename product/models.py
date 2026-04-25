"""Pydantic contracts for the product API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Tenant
# ---------------------------------------------------------------------------


class TenantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class TenantResponse(BaseModel):
    id: str
    name: str
    api_key: str
    created_at: str


# ---------------------------------------------------------------------------
# Agent definition
# ---------------------------------------------------------------------------


class HandoffConfig(BaseModel):
    """Reference to another agent by slug; wired as a handoff at build time."""

    target_slug: str
    description: str = "Transfer conversation to a specialised agent."


class AgentConfig(BaseModel):
    """Per-agent optional settings."""

    max_turns: int | None = None
    template_vars: dict[str, str] = Field(default_factory=dict)
    model_settings: dict[str, Any] = Field(default_factory=dict)


class AgentDefCreate(BaseModel):
    slug: str = Field(..., pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=1, max_length=80)
    name: str = Field(..., min_length=1, max_length=120)
    instructions: str = Field(
        ...,
        description=(
            "Agent system prompt. Use {var} placeholders for runtime substitution. "
            "Example: 'You are a support agent for {company_name}.'"
        ),
    )
    model: str | None = Field(
        default=None,
        description="Model override; falls back to server DEFAULT_MODEL env var.",
    )
    tools: list[str] = Field(
        default_factory=list,
        description="Registered tool names to attach. Example: ['get_current_datetime', 'calculate']",  # noqa: E501
    )
    handoffs: list[HandoffConfig] = Field(
        default_factory=list,
        description="Other agent slugs this agent can hand off to.",
    )
    config: AgentConfig = Field(default_factory=AgentConfig)


class AgentDefUpdate(BaseModel):
    name: str | None = None
    instructions: str | None = None
    model: str | None = None
    tools: list[str] | None = None
    handoffs: list[HandoffConfig] | None = None
    config: AgentConfig | None = None


class AgentDefResponse(BaseModel):
    id: str
    slug: str
    name: str
    instructions: str
    model: str | None
    tools: list[str]
    handoffs: list[HandoffConfig]
    config: AgentConfig
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


class RunRequest(BaseModel):
    input: str = Field(..., description="User message to start or continue the conversation.")
    session_id: str | None = Field(
        default=None,
        description="Reuse a prior session to maintain conversation history.",
    )
    template_vars: dict[str, str] = Field(
        default_factory=dict,
        description="Runtime overrides for {var} placeholders in agent instructions.",
    )
    model: str | None = Field(default=None, description="Per-run model override.")
    max_turns: int | None = Field(default=None, description="Per-run max turns override.")


class RunResponse(BaseModel):
    run_id: str
    agent_slug: str
    session_id: str | None
    status: str
    output: str | None
    tokens_used: int | None
    error: str | None
    created_at: str
    completed_at: str | None


# ---------------------------------------------------------------------------
# Tool listing
# ---------------------------------------------------------------------------


class ToolInfo(BaseModel):
    name: str
    description: str
