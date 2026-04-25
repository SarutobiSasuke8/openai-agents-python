"""Content Pipeline — multi-agent content creation for marketing teams.

A sequential pipeline where a briefer agent turns a topic into a structured
brief, a writer produces a first draft, and an editor polishes and finalises
the content. All agents are white-labelled via template vars so a single
pipeline serves multiple brands.

Demonstrates:
  - Sequential handoff pipeline (briefer → writer → editor)
  - Template vars for brand customisation (brand_name, audience, tone)
  - Per-run template var overrides (run the same pipeline for different clients)
  - Content-specific tools (word count, reading time estimate)

Run:
    OPENAI_API_KEY=sk-... uv run python -m product.examples.content_pipeline
"""

from __future__ import annotations

import asyncio
import math
import os
import tempfile
from typing import Any

from agents import Agent, RunHooks, function_tool
from agents.tool import Tool
from product.builder import build_agent
from product.config import settings
from product.database import init_db
from product.models import AgentConfig, AgentDefCreate, HandoffConfig
from product.registry import create_agent_def, create_tenant, get_agent_def
from product.tools import register_tool

# ---------------------------------------------------------------------------
# Domain tools
# ---------------------------------------------------------------------------

# In-memory content store — passed between agents in the pipeline.
_CONTENT_STORE: dict[str, str] = {}


@register_tool
@function_tool
def word_count(text: str) -> str:
    """Count the number of words in a text."""
    count = len(text.split())
    return f"{count} words"


@register_tool
@function_tool
def estimate_reading_time(text: str) -> str:
    """Estimate how long it takes an average adult to read a piece of text.

    Based on an average reading speed of 238 words per minute.
    """
    words = len(text.split())
    minutes = math.ceil(words / 238)
    return f"~{minutes} minute read ({words} words)"


@register_tool
@function_tool
def save_content(stage: str, content: str) -> str:
    """Save content produced at a pipeline stage for the next agent to retrieve.

    Args:
        stage: Pipeline stage identifier, e.g. 'brief', 'draft', 'final'.
        content: The content to save.
    """
    _CONTENT_STORE[stage] = content
    return f"Content saved at stage '{stage}' ({len(content.split())} words)."


@register_tool
@function_tool
def get_content(stage: str) -> str:
    """Retrieve content saved at a previous pipeline stage.

    Args:
        stage: The stage identifier to retrieve, e.g. 'brief' or 'draft'.
    """
    content = _CONTENT_STORE.get(stage)
    if not content:
        available = list(_CONTENT_STORE.keys()) or ["none yet"]
        return f"No content found at stage '{stage}'. Available stages: {available}."
    return content


# ---------------------------------------------------------------------------
# Agent definitions
# ---------------------------------------------------------------------------

_AGENTS: list[AgentDefCreate] = [
    AgentDefCreate(
        slug="content-writer",
        name="Content Writer",
        instructions=(
            "You are a skilled content writer for {brand_name}, writing for {audience}.\n"
            "Brand tone: {tone}\n\n"
            "When called:\n"
            "1. Retrieve the content brief using get_content('brief').\n"
            "2. Write a complete first draft following the brief exactly.\n"
            "   - Match the specified format, word count, and tone.\n"
            "   - Use natural, engaging language appropriate for {audience}.\n"
            "3. Save the draft with save_content('draft', <your draft>).\n"
            "4. Report the word count using word_count.\n\n"
            "Do not edit or critique — just write the draft as specified."
        ),
        model=settings.default_model,
        tools=["get_content", "save_content", "word_count"],
        handoffs=[],
        config=AgentConfig(
            max_turns=6,
            template_vars={
                "brand_name": "Acme SaaS",
                "audience": "small business owners",
                "tone": "friendly, practical, and jargon-free",
            },
        ),
    ),
    AgentDefCreate(
        slug="content-editor",
        name="Content Editor",
        instructions=(
            "You are a senior content editor for {brand_name}.\n"
            "Brand tone: {tone}. Audience: {audience}.\n\n"
            "When called:\n"
            "1. Retrieve the draft with get_content('draft').\n"
            "2. Edit for: clarity, flow, tone consistency, grammar, and conciseness.\n"
            "   - Cut filler words and passive voice.\n"
            "   - Ensure every paragraph earns its place.\n"
            "   - Keep the brand voice ({tone}) consistent throughout.\n"
            "3. Save the polished version with save_content('final', <final content>).\n"
            "4. Provide a brief editor's note (2–3 sentences) explaining your main changes.\n"
            "5. Report the reading time with estimate_reading_time on the final content."
        ),
        model=settings.default_model,
        tools=["get_content", "save_content", "estimate_reading_time"],
        handoffs=[],
        config=AgentConfig(
            max_turns=6,
            template_vars={
                "brand_name": "Acme SaaS",
                "audience": "small business owners",
                "tone": "friendly, practical, and jargon-free",
            },
        ),
    ),
    AgentDefCreate(
        slug="content-briefer",
        name="Content Briefer",
        instructions=(
            "You are a content strategist for {brand_name}. Your job is to turn a raw content "
            "request into a precise brief that a writer can execute without ambiguity.\n\n"
            "When given a content request:\n"
            "1. Write a structured brief containing:\n"
            "   - **Title:** A working title.\n"
            "   - **Goal:** What this piece should achieve.\n"
            "   - **Audience:** {audience} — what they care about.\n"
            "   - **Format:** Article / listicle / email / social post, etc.\n"
            "   - **Word count:** Target length.\n"
            "   - **Tone:** {tone}\n"
            "   - **Key points:** 3–5 must-cover points.\n"
            "   - **CTA:** Desired reader action after reading.\n"
            "2. Save the brief with save_content('brief', <the brief>).\n"
            "3. Hand off to the writer to produce the first draft.\n"
            "4. After the writer is done, hand off to the editor to polish it.\n\n"
            "Do not write the content yourself — only produce the brief."
        ),
        model=settings.default_model_fast,
        tools=["save_content"],
        handoffs=[
            HandoffConfig(
                target_slug="content-writer",
                description="Hand off to the writer once the brief is saved.",
            ),
            HandoffConfig(
                target_slug="content-editor",
                description="Hand off to the editor once the writer's draft is saved.",
            ),
        ],
        config=AgentConfig(
            max_turns=4,
            template_vars={
                "brand_name": "Acme SaaS",
                "audience": "small business owners",
                "tone": "friendly, practical, and jargon-free",
            },
        ),
    ),
]


# ---------------------------------------------------------------------------
# Demo hooks
# ---------------------------------------------------------------------------


class PipelineHooks(RunHooks):  # type: ignore[type-arg]
    async def on_agent_start(self, context: Any, agent: Agent) -> None:  # type: ignore[override]
        print(f"\n  \033[36m[{agent.name}]\033[0m")

    async def on_handoff(self, context: Any, from_agent: Agent, to_agent: Agent) -> None:  # type: ignore[override]
        print(f"  \033[33m↗ Pipeline step:\033[0m {from_agent.name} → {to_agent.name}")

    async def on_tool_start(self, context: Any, agent: Agent, tool: Tool) -> None:  # type: ignore[override]
        print(f"  \033[35m⚙ {tool.name}\033[0m")

    async def on_tool_end(self, context: Any, agent: Agent, tool: Tool, result: str) -> None:  # type: ignore[override]
        preview = result[:90].replace("\n", " ")
        print(f"     └─ {preview}{'…' if len(result) > 90 else ''}")


# ---------------------------------------------------------------------------
# Setup and demo
# ---------------------------------------------------------------------------


async def setup(tenant_id: str) -> None:
    for defn in _AGENTS:
        await create_agent_def(tenant_id, defn)


async def run_pipeline(
    tenant_id: str,
    request: str,
    brand_overrides: dict[str, str] | None = None,
) -> None:
    _CONTENT_STORE.clear()
    label = brand_overrides.get("brand_name", "Acme SaaS") if brand_overrides else "Acme SaaS"
    print(f"\n\033[32mContent request [{label}]:\033[0m {request}")

    defn = await get_agent_def(tenant_id, "content-briefer")
    assert defn is not None
    agent = build_agent(defn, tenant_id, template_var_overrides=brand_overrides)

    from agents import Runner
    from agents.memory.sqlite_session import SQLiteSession

    session = SQLiteSession(session_id=f"content-{hash(request + label)}", db_path=settings.db_path)
    result = await Runner.run(
        agent,
        request,
        max_turns=20,
        hooks=PipelineHooks(),
        session=session,
    )

    final = _CONTENT_STORE.get("final", result.final_output or "")
    print(f"\n\033[34m--- FINAL CONTENT ---\033[0m\n{final}")

    if "final" in _CONTENT_STORE:
        words = len(final.split())
        minutes = math.ceil(words / 238)
        print(f"\n\033[90m({words} words · ~{minutes} min read)\033[0m")


async def main() -> None:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    settings.db_path = tmp.name
    tmp.close()

    await init_db()
    tenant = await create_tenant("Demo — Content Pipeline")
    await setup(tenant["id"])

    print("\n" + "=" * 60)
    print("  CONTENT PIPELINE DEMO")
    print("=" * 60)

    # Scenario 1: default brand
    await run_pipeline(
        tenant["id"],
        "Write a short blog post (300 words) explaining why small businesses should automate their invoicing.",
    )

    # Scenario 2: different brand via per-run template var override
    print("\n" + "-" * 60)
    await run_pipeline(
        tenant["id"],
        "Write a LinkedIn post announcing our new AI-powered reporting feature.",
        brand_overrides={
            "brand_name": "FinFlow",
            "audience": "finance directors at mid-market companies",
            "tone": "authoritative and data-driven",
        },
    )

    os.unlink(settings.db_path)


if __name__ == "__main__":
    asyncio.run(main())
