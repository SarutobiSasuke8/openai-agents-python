"""Research Assistant — multi-agent research and synthesis pipeline.

A coordinator agent breaks a research question into subtasks and delegates to
a researcher (who searches and retrieves information) and an analyst (who
synthesises findings into structured insights).

Demonstrates:
  - Multi-stage pipeline with handoffs (coordinator → researcher → analyst)
  - Agents-as-tools pattern: researcher and analyst exposed as handoff targets
  - Mocked search/retrieval tools that can be swapped for real integrations
  - Structured research output with sources

Run:
    OPENAI_API_KEY=sk-... uv run python -m product.examples.research_assistant
"""

from __future__ import annotations

import asyncio
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

# In-memory note store shared across tool calls within a run.
_NOTES: dict[str, str] = {}

# Mocked search index — replace with a real search API (Brave, Tavily, etc.)
_SEARCH_INDEX: dict[str, list[dict[str, str]]] = {
    "quantum computing 2025": [
        {
            "title": "IBM Quantum reaches 1000-qubit milestone",
            "url": "https://example.com/ibm-quantum",
            "snippet": "IBM announced its Condor processor with 1121 qubits, marking a major step toward practical quantum advantage in optimisation problems.",
        },
        {
            "title": "Google Willow chip cuts error rates",
            "url": "https://example.com/google-willow",
            "snippet": "Google's Willow chip demonstrated exponential error reduction as qubit count scaled, a key requirement for fault-tolerant quantum computing.",
        },
        {
            "title": "Quantum computing market to hit $450B by 2030",
            "url": "https://example.com/qc-market",
            "snippet": "McKinsey estimates the quantum computing industry will generate $450 billion annually by 2030, driven by pharmaceutical and logistics use cases.",
        },
    ],
    "ai regulation europe": [
        {
            "title": "EU AI Act enters into force",
            "url": "https://example.com/eu-ai-act",
            "snippet": "The EU AI Act became law in August 2024, introducing risk-based requirements for AI systems with full enforcement expected by 2026.",
        },
        {
            "title": "High-risk AI systems face strict compliance",
            "url": "https://example.com/ai-compliance",
            "snippet": "Under the Act, high-risk AI systems in healthcare, education, and law enforcement must pass conformity assessments before deployment.",
        },
    ],
}

_ARTICLE_CONTENT: dict[str, str] = {
    "https://example.com/ibm-quantum": (
        "IBM's Condor processor achieved 1121 qubits in late 2023. The company's roadmap targets "
        "100,000 qubits by 2033 using modular architecture. Key challenges remain in error correction "
        "and coherence time. Partners include universities and Fortune 500 companies in finance and logistics."
    ),
    "https://example.com/google-willow": (
        "Google's Willow chip solved a benchmark problem in under 5 minutes that would take classical "
        "computers 10 septillion years. The breakthrough lies in 'below threshold' error correction — "
        "adding more qubits actively reduces rather than amplifies errors."
    ),
    "https://example.com/eu-ai-act": (
        "The EU AI Act classifies AI systems into four risk tiers: unacceptable (banned), high-risk "
        "(strict compliance), limited risk (transparency), and minimal risk (self-regulation). "
        "General-purpose AI models like GPT-4 face additional transparency requirements."
    ),
}


@register_tool
@function_tool
def search_web(query: str, max_results: int = 3) -> str:
    """Search the web for information on a topic and return top results with snippets.

    Args:
        query: The search query.
        max_results: Maximum number of results to return (1–5).
    """
    # Normalise query to find the closest match in the mock index.
    query_lower = query.lower()
    for key, results in _SEARCH_INDEX.items():
        if any(word in query_lower for word in key.split()):
            limited = results[: max(1, min(max_results, 5))]
            formatted = []
            for i, r in enumerate(limited, 1):
                formatted.append(f"{i}. [{r['title']}]({r['url']})\n   {r['snippet']}")
            return "\n\n".join(formatted)
    return f"No results found for '{query}'. Try a different query."


@register_tool
@function_tool
def fetch_article(url: str) -> str:
    """Fetch and return the full text content of an article by URL."""
    content = _ARTICLE_CONTENT.get(url)
    if not content:
        return f"Could not retrieve content from '{url}'."
    return content


@register_tool
@function_tool
def save_note(key: str, content: str) -> str:
    """Save a research note under a key for later retrieval by the analyst.

    Args:
        key: Short identifier for the note (e.g. 'ibm-quantum-summary').
        content: The note content to save.
    """
    _NOTES[key] = content
    return f"Note '{key}' saved ({len(content)} characters)."


@register_tool
@function_tool
def get_notes() -> str:
    """Retrieve all saved research notes as a structured summary."""
    if not _NOTES:
        return "No notes saved yet."
    parts = [f"**{k}**\n{v}" for k, v in _NOTES.items()]
    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# Agent definitions
# ---------------------------------------------------------------------------

_AGENTS: list[AgentDefCreate] = [
    AgentDefCreate(
        slug="researcher",
        name="Web Researcher",
        instructions=(
            "You are a thorough web researcher. Given a research topic or question:\n"
            "1. Search for relevant information using search_web.\n"
            "2. Fetch full content from the most relevant URLs using fetch_article.\n"
            "3. Save key findings as structured notes using save_note.\n"
            "4. Provide a concise summary of what you found with sources cited.\n\n"
            "Be systematic. Search at least twice with different query angles before concluding."
        ),
        model="gpt-4o-mini",
        tools=["search_web", "fetch_article", "save_note"],
        handoffs=[],
        config=AgentConfig(max_turns=12),
    ),
    AgentDefCreate(
        slug="analyst",
        name="Research Analyst",
        instructions=(
            "You are a senior research analyst. Your job is to synthesise raw research findings into "
            "clear, actionable insights.\n\n"
            "When called:\n"
            "1. Retrieve all saved research notes with get_notes.\n"
            "2. Identify the 3–5 most significant findings.\n"
            "3. Note any gaps, contradictions, or areas needing further research.\n"
            "4. Produce a structured report: Executive Summary, Key Findings, Implications, "
            "   and Recommended Next Steps.\n\n"
            "Be analytical and specific. Cite sources where relevant."
        ),
        model="gpt-4o",
        tools=["get_notes"],
        handoffs=[],
        config=AgentConfig(max_turns=6),
    ),
    AgentDefCreate(
        slug="research-coordinator",
        name="Research Coordinator",
        instructions=(
            "You are a research coordinator. When given a research question:\n"
            "1. Acknowledge the question and briefly outline your research plan.\n"
            "2. Hand off to the Web Researcher to gather raw information.\n"
            "3. After research is complete, hand off to the Research Analyst to synthesise findings.\n\n"
            "Do not attempt to research or analyse yourself — delegate to specialists.\n"
            "Your role is to orchestrate and ensure the final report is comprehensive."
        ),
        model="gpt-4o-mini",
        tools=[],
        handoffs=[
            HandoffConfig(
                target_slug="researcher",
                description="Delegate information gathering to the web researcher.",
            ),
            HandoffConfig(
                target_slug="analyst",
                description="Delegate synthesis and report writing to the research analyst.",
            ),
        ],
        config=AgentConfig(max_turns=6),
    ),
]


# ---------------------------------------------------------------------------
# Demo hooks
# ---------------------------------------------------------------------------


class ResearchHooks(RunHooks):  # type: ignore[type-arg]
    async def on_agent_start(self, context: Any, agent: Agent) -> None:  # type: ignore[override]
        print(f"\n  \033[36m[{agent.name}]\033[0m activated")

    async def on_handoff(self, context: Any, from_agent: Agent, to_agent: Agent) -> None:  # type: ignore[override]
        print(f"  \033[33m↗ Delegating:\033[0m {from_agent.name} → {to_agent.name}")

    async def on_tool_start(self, context: Any, agent: Agent, tool: Tool) -> None:  # type: ignore[override]
        print(f"  \033[35m⚙ {tool.name}\033[0m")

    async def on_tool_end(self, context: Any, agent: Agent, tool: Tool, result: str) -> None:  # type: ignore[override]
        preview = result[:100].replace("\n", " ")
        print(f"     └─ {preview}{'…' if len(result) > 100 else ''}")


# ---------------------------------------------------------------------------
# Setup and demo
# ---------------------------------------------------------------------------


async def setup(tenant_id: str) -> None:
    for defn in _AGENTS:
        await create_agent_def(tenant_id, defn)


async def run_research(tenant_id: str, question: str) -> None:
    _NOTES.clear()
    print(f"\n\033[32mResearch question:\033[0m {question}")

    defn = await get_agent_def(tenant_id, "research-coordinator")
    assert defn is not None
    agent = build_agent(defn, tenant_id)

    from agents import Runner
    from agents.memory.sqlite_session import SQLiteSession

    session = SQLiteSession(session_id=f"research-{hash(question)}", db_path=settings.db_path)
    result = await Runner.run(
        agent,
        question,
        max_turns=20,
        hooks=ResearchHooks(),
        session=session,
    )
    print(f"\n\033[34m--- FINAL REPORT ---\033[0m\n{result.final_output}")


async def main() -> None:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    settings.db_path = tmp.name
    tmp.close()

    await init_db()
    tenant = await create_tenant("Demo — Research Assistant")
    await setup(tenant["id"])

    print("\n" + "=" * 60)
    print("  RESEARCH ASSISTANT DEMO")
    print("=" * 60)

    await run_research(
        tenant["id"],
        "What is the current state of quantum computing and what are the most significant recent breakthroughs?",
    )

    os.unlink(settings.db_path)


if __name__ == "__main__":
    asyncio.run(main())
