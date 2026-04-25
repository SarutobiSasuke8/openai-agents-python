"""Sales Pipeline — multi-agent B2B sales automation.

A coordinator routes an inbound lead through qualification, personalised
outreach drafting, and objection handling, producing a ready-to-send email
and a CRM-ready lead record.

Demonstrates:
  - Three-stage sequential pipeline (qualifier → outreach writer → objection handler)
  - Shared in-memory CRM store updated by each stage
  - Lead scoring with configurable thresholds ({min_score})
  - Per-run template var overrides (sales rep name, product, ICP criteria)

Run:
    OPENAI_API_KEY=sk-... uv run python -m product.examples.sales_pipeline
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

# In-memory CRM store — updated across pipeline stages.
_CRM: dict[str, Any] = {}

# Mocked company enrichment data.
_ENRICHMENT_DB: dict[str, dict[str, Any]] = {
    "acme corp": {
        "company": "Acme Corp",
        "industry": "Manufacturing",
        "employees": 450,
        "revenue_usd": 80_000_000,
        "tech_stack": ["SAP", "Salesforce", "Excel"],
        "recent_news": "Acme Corp announced a digital transformation initiative in Q1 2025.",
        "linkedin_url": "https://linkedin.com/company/acme-corp",
    },
    "nova health": {
        "company": "Nova Health",
        "industry": "Healthcare",
        "employees": 1200,
        "revenue_usd": 250_000_000,
        "tech_stack": ["Epic", "Tableau", "AWS"],
        "recent_news": "Nova Health raised $40M Series C to expand AI diagnostics platform.",
        "linkedin_url": "https://linkedin.com/company/nova-health",
    },
    "greenleaf logistics": {
        "company": "Greenleaf Logistics",
        "industry": "Logistics",
        "employees": 320,
        "revenue_usd": 45_000_000,
        "tech_stack": ["Oracle TMS", "QuickBooks"],
        "recent_news": "Greenleaf Logistics won a 3-year government freight contract in March 2025.",
        "linkedin_url": "https://linkedin.com/company/greenleaf-logistics",
    },
}

_OBJECTION_PLAYBOOK: dict[str, str] = {
    "price": (
        "Acknowledge the investment concern. Pivot to ROI: share a relevant customer story "
        "where the product paid back within 6 months. Offer a phased rollout or pilot to "
        "reduce upfront commitment."
    ),
    "timing": (
        "Validate the timing challenge. Ask what would need to change for timing to work. "
        "Offer a future-dated pilot start or a 'reserve your spot' option to avoid losing momentum."
    ),
    "competitor": (
        "Thank them for the transparency. Ask which specific features or outcomes matter most. "
        "Focus the conversation on the 2-3 differentiators most relevant to their pain point. "
        "Never disparage the competitor by name."
    ),
    "trust": (
        "Offer social proof: a customer reference in their industry, G2/Capterra reviews, or "
        "a free proof-of-concept. Invite them to speak with an existing customer directly."
    ),
    "features": (
        "Clarify which specific features are missing. Check the product roadmap. If it's on the "
        "roadmap, share expected timeline. If not, explore whether a workaround meets the need."
    ),
}


@register_tool
@function_tool
def enrich_company(company_name: str) -> str:
    """Look up firmographic data for a company: industry, size, revenue, tech stack, recent news.

    Args:
        company_name: The company name to look up (case-insensitive).
    """
    data = _ENRICHMENT_DB.get(company_name.lower())
    if not data:
        return (
            f"No enrichment data found for '{company_name}'. "
            "Proceed with the information provided by the lead."
        )
    lines = [
        f"Company: {data['company']}",
        f"Industry: {data['industry']}",
        f"Employees: {data['employees']}",
        f"Revenue: ~${data['revenue_usd']:,}",
        f"Tech stack: {', '.join(data['tech_stack'])}",
        f"Recent news: {data['recent_news']}",
        f"LinkedIn: {data['linkedin_url']}",
    ]
    return "\n".join(lines)


@register_tool
@function_tool
def score_lead(
    company_name: str,
    title: str,
    budget_confirmed: bool,
    timeline_months: int,
    pain_point_match: int,
) -> str:
    """Score a lead 0–100 based on BANT-style criteria.

    Args:
        company_name: Lead's company name.
        title: Lead's job title.
        budget_confirmed: Whether budget availability was confirmed.
        timeline_months: Expected purchase timeline in months (shorter = higher score).
        pain_point_match: How well our product matches their pain (1=weak, 5=strong).
    """
    score = 0
    score += 25 if budget_confirmed else 0
    score += max(0, 25 - (timeline_months - 1) * 3)
    score += pain_point_match * 8
    seniority_keywords = ["cto", "ceo", "coo", "vp", "director", "head of", "chief"]
    if any(k in title.lower() for k in seniority_keywords):
        score += 20
    else:
        score += 10
    score = min(score, 100)

    _CRM["lead_score"] = score
    _CRM["company"] = company_name
    _CRM["title"] = title

    tier = "HOT" if score >= 70 else "WARM" if score >= 40 else "COLD"
    return f"Lead score: {score}/100 ({tier}) — stored in CRM."


@register_tool
@function_tool
def save_crm_field(field: str, value: str) -> str:
    """Save a field to the lead's CRM record.

    Args:
        field: Field name (e.g. 'pain_summary', 'outreach_email', 'objection_response').
        value: Value to store.
    """
    _CRM[field] = value
    return f"CRM field '{field}' saved ({len(value)} chars)."


@register_tool
@function_tool
def get_crm_record() -> str:
    """Retrieve the current CRM record for the lead being processed."""
    if not _CRM:
        return "CRM record is empty."
    lines = [f"{k}: {str(v)[:120]}" for k, v in _CRM.items()]
    return "CRM record:\n" + "\n".join(lines)


@register_tool
@function_tool
def get_objection_playbook(objection_type: str) -> str:
    """Retrieve the recommended handling strategy for a sales objection.

    Args:
        objection_type: One of: 'price', 'timing', 'competitor', 'trust', 'features'.
    """
    strategy = _OBJECTION_PLAYBOOK.get(objection_type.lower())
    if not strategy:
        available = list(_OBJECTION_PLAYBOOK.keys())
        return f"Unknown objection type '{objection_type}'. Available: {available}."
    return f"Objection playbook [{objection_type.upper()}]:\n{strategy}"


# ---------------------------------------------------------------------------
# Agent definitions
# ---------------------------------------------------------------------------

_AGENTS: list[AgentDefCreate] = [
    AgentDefCreate(
        slug="lead-qualifier",
        name="Lead Qualifier",
        instructions=(
            "You are a B2B sales development representative (SDR) at {company_name}, "
            "selling {product_name} to {icp_description}.\n\n"
            "When given a lead's details:\n"
            "1. Enrich the company with enrich_company.\n"
            "2. Score the lead with score_lead using the information provided.\n"
            "3. Save a 2-sentence pain_summary to CRM with save_crm_field.\n"
            "4. If score >= {min_score}: summarise why this is a qualified lead and hand off "
            "   to the Outreach Writer to draft personalised outreach.\n"
            "   If score < {min_score}: explain why the lead is below threshold and do NOT "
            "   hand off — recommend nurture sequence instead.\n\n"
            "Be factual and concise. Base qualification on the enriched data, not assumptions."
        ),
        model=settings.default_model_fast,
        tools=["enrich_company", "score_lead", "save_crm_field"],
        handoffs=[
            HandoffConfig(
                target_slug="outreach-writer",
                description="Hand off to the outreach writer when the lead qualifies (score >= min_score).",
            ),
        ],
        config=AgentConfig(
            max_turns=8,
            template_vars={
                "company_name": "Nexus Analytics",
                "product_name": "Nexus BI Platform",
                "icp_description": "operations and finance leaders at mid-market companies (100–2000 employees)",
                "min_score": "50",
            },
        ),
    ),
    AgentDefCreate(
        slug="outreach-writer",
        name="Outreach Writer",
        instructions=(
            "You are a senior account executive at {company_name} writing a cold outreach email.\n\n"
            "When called:\n"
            "1. Retrieve the CRM record with get_crm_record.\n"
            "2. Write a personalised first-touch email that:\n"
            "   - Opens with a specific observation about their company (use recent_news or tech_stack).\n"
            "   - Connects their likely pain to {product_name} in one sentence.\n"
            "   - States a concrete outcome a similar customer achieved (make it plausible).\n"
            "   - Has a single low-friction CTA (e.g. '15-minute call this week?').\n"
            "   - Is under 120 words, no bullet points, no jargon.\n"
            "3. Save the email to CRM with save_crm_field('outreach_email', <email>).\n"
            "4. Hand off to the Objection Handler to prepare for likely pushback.\n\n"
            "Write in a warm, direct, human tone — not a template blast."
        ),
        model=settings.default_model,
        tools=["get_crm_record", "save_crm_field"],
        handoffs=[
            HandoffConfig(
                target_slug="objection-handler",
                description="Hand off to the objection handler to prepare responses for anticipated pushback.",
            ),
        ],
        config=AgentConfig(
            max_turns=6,
            template_vars={
                "company_name": "Nexus Analytics",
                "product_name": "Nexus BI Platform",
            },
        ),
    ),
    AgentDefCreate(
        slug="objection-handler",
        name="Objection Handler",
        instructions=(
            "You are a sales coach at {company_name}. Your job is to prepare the rep for "
            "objections they are likely to face with this specific lead.\n\n"
            "When called:\n"
            "1. Retrieve the CRM record with get_crm_record.\n"
            "2. Based on the lead's profile (industry, score, pain summary), identify the "
            "   2 most likely objections they will raise.\n"
            "3. For each objection, call get_objection_playbook to get the strategy.\n"
            "4. Write a tailored response for each objection (3–4 sentences each), "
            "   referencing the specific lead context.\n"
            "5. Save all objection responses with save_crm_field('objection_prep', <text>).\n"
            "6. Produce a final battle card summary:\n"
            "   ## Lead Battle Card\n"
            "   **Company:** ...\n"
            "   **Score:** .../100\n"
            "   **Pain Summary:** ...\n"
            "   ## Outreach Email\n"
            "   (the email)\n"
            "   ## Objection Preparation\n"
            "   (the objection responses)\n"
        ),
        model=settings.default_model,
        tools=["get_crm_record", "get_objection_playbook", "save_crm_field"],
        handoffs=[],
        config=AgentConfig(
            max_turns=8,
            template_vars={
                "company_name": "Nexus Analytics",
            },
        ),
    ),
    AgentDefCreate(
        slug="sales-coordinator",
        name="Sales Coordinator",
        instructions=(
            "You are a sales operations coordinator at {company_name}.\n\n"
            "When given a new inbound lead:\n"
            "1. Acknowledge the lead and hand off to the Lead Qualifier immediately.\n"
            "2. The pipeline will run automatically: Qualifier → Outreach Writer → Objection Handler.\n"
            "3. Do not attempt to qualify, write, or handle objections yourself.\n\n"
            "Your role is to route the lead and ensure the pipeline completes."
        ),
        model=settings.default_model_fast,
        tools=[],
        handoffs=[
            HandoffConfig(
                target_slug="lead-qualifier",
                description="Route the inbound lead to the qualifier to begin the pipeline.",
            ),
        ],
        config=AgentConfig(
            max_turns=4,
            template_vars={
                "company_name": "Nexus Analytics",
            },
        ),
    ),
]

# ---------------------------------------------------------------------------
# Demo leads
# ---------------------------------------------------------------------------

_LEADS = [
    {
        "name": "Sarah Chen",
        "title": "VP of Operations",
        "company": "Acme Corp",
        "email": "s.chen@acmecorp.com",
        "message": (
            "Hi, I came across Nexus BI at an operations conference last week. "
            "We're currently drowning in Excel and our Salesforce data doesn't talk to SAP. "
            "We have a Q3 budget cycle opening up and I'd love to explore options."
        ),
    },
    {
        "name": "Mike Torres",
        "title": "IT Manager",
        "company": "Greenleaf Logistics",
        "email": "m.torres@greenleaflogistics.com",
        "message": (
            "Hello, saw your ad online. We use Oracle TMS and might be interested "
            "in better reporting. No confirmed budget yet. Just browsing."
        ),
    },
]

# ---------------------------------------------------------------------------
# Demo hooks
# ---------------------------------------------------------------------------


class SalesHooks(RunHooks):  # type: ignore[type-arg]
    async def on_agent_start(self, context: Any, agent: Agent) -> None:  # type: ignore[override]
        print(f"\n  \033[36m[{agent.name}]\033[0m")

    async def on_handoff(self, context: Any, from_agent: Agent, to_agent: Agent) -> None:  # type: ignore[override]
        print(f"  \033[33m↗ Pipeline:\033[0m {from_agent.name} → {to_agent.name}")

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


async def process_lead(
    tenant_id: str,
    lead: dict[str, Any],
    overrides: dict[str, str] | None = None,
) -> None:
    _CRM.clear()
    print(f"\n\033[32mInbound lead:\033[0m {lead['name']} ({lead['title']}) @ {lead['company']}")

    defn = await get_agent_def(tenant_id, "sales-coordinator")
    assert defn is not None
    agent = build_agent(defn, tenant_id, template_var_overrides=overrides)

    from agents import Runner
    from agents.memory.sqlite_session import SQLiteSession

    session = SQLiteSession(
        session_id=f"sales-{lead['email'].replace('@', '-')}",
        db_path=settings.db_path,
    )
    prompt = (
        f"New inbound lead:\n"
        f"  Name: {lead['name']}\n"
        f"  Title: {lead['title']}\n"
        f"  Company: {lead['company']}\n"
        f"  Email: {lead['email']}\n"
        f"  Message: {lead['message']}\n\n"
        f"Budget confirmed: {'Yes' if 'budget' in lead['message'].lower() else 'No'}\n"
        f"Estimated timeline: 3 months\n"
        f"Pain point match (1-5): 4"
    )
    result = await Runner.run(
        agent,
        prompt,
        max_turns=30,
        hooks=SalesHooks(),
        session=session,
    )
    print(f"\n\033[34m--- PIPELINE OUTPUT ---\033[0m\n{result.final_output}")


async def main() -> None:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    settings.db_path = tmp.name
    tmp.close()

    await init_db()
    tenant = await create_tenant("Demo — Sales Pipeline")
    await setup(tenant["id"])

    print("\n" + "=" * 60)
    print("  SALES PIPELINE DEMO")
    print("=" * 60)

    # Lead 1: high-score, qualified — full pipeline runs
    await process_lead(tenant["id"], _LEADS[0])

    print("\n" + "-" * 60)

    # Lead 2: low-score, nurture candidate — qualifier does not hand off
    await process_lead(tenant["id"], _LEADS[1])

    os.unlink(settings.db_path)


if __name__ == "__main__":
    asyncio.run(main())
