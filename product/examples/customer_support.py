"""Customer Support Platform — multi-agent triage and resolution.

Three-agent support system where a triage agent routes customers to
specialised billing or tech-support agents based on the nature of their issue.

Demonstrates:
  - Handoffs between specialised agents
  - Custom domain tools (order lookup, ticket creation)
  - Template vars for white-labelling (company name, support hours)
  - Session continuity across multiple turns

Run:
    OPENAI_API_KEY=sk-... uv run python -m product.examples.customer_support
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

_ORDERS: dict[str, dict[str, str]] = {
    "ORD-1001": {
        "status": "delivered",
        "date": "2026-04-20",
        "amount": "$49.00",
        "item": "Pro Plan",
    },
    "ORD-1002": {
        "status": "processing",
        "date": "2026-04-24",
        "amount": "$99.00",
        "item": "Team Plan",
    },
    "ORD-1003": {
        "status": "refunded",
        "date": "2026-04-18",
        "amount": "$49.00",
        "item": "Pro Plan",
    },
}

_ACCOUNTS: dict[str, dict[str, str]] = {
    "alice@example.com": {
        "plan": "Pro",
        "status": "active",
        "since": "2025-01-15",
        "next_bill": "2026-05-15",
    },
    "bob@example.com": {
        "plan": "Free",
        "status": "active",
        "since": "2026-03-01",
        "next_bill": "N/A",
    },
}

_TICKET_COUNTER = 0


@register_tool
@function_tool
def lookup_order(order_id: str) -> str:
    """Look up the status and details of a customer order by order ID."""
    order = _ORDERS.get(order_id.upper())
    if not order:
        return f"No order found with ID '{order_id}'. Please verify the order ID."
    return (
        f"Order {order_id.upper()}: {order['item']} — "
        f"Status: {order['status']}, Date: {order['date']}, Amount: {order['amount']}"
    )


@register_tool
@function_tool
def check_account(email: str) -> str:
    """Check account status and subscription details for a customer email address."""
    account = _ACCOUNTS.get(email.lower())
    if not account:
        return f"No account found for '{email}'."
    return (
        f"Account for {email}: Plan={account['plan']}, Status={account['status']}, "
        f"Member since {account['since']}, Next billing: {account['next_bill']}"
    )


@register_tool
@function_tool
def create_ticket(subject: str, description: str, priority: str = "normal") -> str:
    """Create a support ticket for an issue that requires follow-up.

    Args:
        subject: Short summary of the issue.
        description: Detailed description of the problem.
        priority: 'low', 'normal', or 'urgent'.
    """
    global _TICKET_COUNTER
    _TICKET_COUNTER += 1
    ticket_id = f"TKT-{_TICKET_COUNTER:04d}"
    return (
        f"Support ticket {ticket_id} created. "
        f"Priority: {priority}. Our team will follow up within "
        f"{'2 hours' if priority == 'urgent' else '1 business day'}."
    )


# ---------------------------------------------------------------------------
# Agent definitions
# ---------------------------------------------------------------------------

_AGENTS: list[AgentDefCreate] = [
    AgentDefCreate(
        slug="cs-billing",
        name="Billing Specialist",
        instructions=(
            "You are a billing specialist for {company_name}. "
            "Help customers with invoices, charges, refunds, and subscription changes. "
            "Always look up their order or account before suggesting a solution. "
            "Be empathetic and concise. Support hours: {support_hours}."
        ),
        model="gpt-4o-mini",
        tools=["lookup_order", "check_account", "create_ticket", "get_current_datetime"],
        handoffs=[],
        config=AgentConfig(
            max_turns=8,
            template_vars={
                "company_name": "Acme SaaS",
                "support_hours": "Mon–Fri 9am–6pm EST",
            },
        ),
    ),
    AgentDefCreate(
        slug="cs-tech",
        name="Tech Support Engineer",
        instructions=(
            "You are a technical support engineer for {company_name}. "
            "Diagnose bugs, guide users through troubleshooting steps, and escalate unresolved issues. "
            "Always ask for the user's browser/OS if they report a UI issue. "
            "If the problem is a confirmed bug, create a ticket. Support hours: {support_hours}."
        ),
        model="gpt-4o-mini",
        tools=["create_ticket", "get_current_datetime"],
        handoffs=[],
        config=AgentConfig(
            max_turns=10,
            template_vars={
                "company_name": "Acme SaaS",
                "support_hours": "Mon–Fri 9am–6pm EST",
            },
        ),
    ),
    AgentDefCreate(
        slug="cs-triage",
        name="Support Triage",
        instructions=(
            "You are the first point of contact for {company_name} customer support. "
            "Greet the customer warmly, understand their issue in one or two exchanges, "
            "then either resolve it yourself or transfer to the right specialist:\n"
            "- Billing questions, charges, refunds → billing specialist\n"
            "- Technical bugs, errors, app problems → tech support\n"
            "Do not attempt to resolve billing or technical issues yourself."
        ),
        model="gpt-4o-mini",
        tools=[],
        handoffs=[
            HandoffConfig(
                target_slug="cs-billing",
                description="Transfer to billing for invoice, charge, refund, or subscription questions.",
            ),
            HandoffConfig(
                target_slug="cs-tech",
                description="Transfer to tech support for bugs, errors, or product issues.",
            ),
        ],
        config=AgentConfig(
            max_turns=4,
            template_vars={"company_name": "Acme SaaS"},
        ),
    ),
]


# ---------------------------------------------------------------------------
# Demo hooks — print live activity
# ---------------------------------------------------------------------------


class SupportHooks(RunHooks):  # type: ignore[type-arg]
    async def on_agent_start(self, context: Any, agent: Agent) -> None:  # type: ignore[override]
        print(f"\n  \033[36m[{agent.name}]\033[0m is handling the conversation")

    async def on_handoff(self, context: Any, from_agent: Agent, to_agent: Agent) -> None:  # type: ignore[override]
        print(f"  \033[33m↗ Handoff:\033[0m {from_agent.name} → {to_agent.name}")

    async def on_tool_start(self, context: Any, agent: Agent, tool: Tool) -> None:  # type: ignore[override]
        print(f"  \033[35m⚙ Tool:\033[0m {tool.name}")

    async def on_tool_end(self, context: Any, agent: Agent, tool: Tool, result: str) -> None:  # type: ignore[override]
        preview = result[:80].replace("\n", " ")
        print(f"     └─ {preview}{'…' if len(result) > 80 else ''}")


# ---------------------------------------------------------------------------
# Setup and demo
# ---------------------------------------------------------------------------


async def setup(tenant_id: str) -> None:
    for defn in _AGENTS:
        await create_agent_def(tenant_id, defn)


async def run_conversation(
    tenant_id: str,
    agent_slug: str,
    turns: list[str],
    session_id: str,
    template_var_overrides: dict[str, str] | None = None,
) -> None:
    hooks = SupportHooks()
    for user_msg in turns:
        print(f"\n\033[32mUser:\033[0m {user_msg}")
        defn = await get_agent_def(tenant_id, agent_slug)
        assert defn is not None
        agent_config = __import__("json").loads(defn["config_json"])
        agent = build_agent(
            defn,
            tenant_id,
            template_var_overrides=template_var_overrides,
        )
        from agents.memory.sqlite_session import SQLiteSession

        session = SQLiteSession(session_id=session_id, db_path=settings.db_path)
        result = await __import__("agents").Runner.run(
            agent,
            user_msg,
            max_turns=agent_config.get("max_turns", 10),
            hooks=hooks,
            session=session,
        )
        print(f"\n\033[34mAgent:\033[0m {result.final_output}")


async def main() -> None:
    # Use a temp DB so this demo is self-contained.
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    settings.db_path = tmp.name
    tmp.close()

    await init_db()
    tenant = await create_tenant("Demo — Customer Support")
    tenant_id = tenant["id"]
    await setup(tenant_id)

    print("\n" + "=" * 60)
    print("  CUSTOMER SUPPORT DEMO — Acme SaaS")
    print("=" * 60)

    # Scenario 1: billing issue → handoff to billing specialist
    print("\n\033[1mScenario 1: Billing dispute\033[0m")
    await run_conversation(
        tenant_id,
        "cs-triage",
        ["Hi, I think I was charged twice for my subscription this month — order ORD-1001."],
        session_id="demo-billing-1",
    )

    # Scenario 2: technical issue → handoff to tech support, multi-turn
    print("\n\033[1mScenario 2: Technical issue (multi-turn)\033[0m")
    await run_conversation(
        tenant_id,
        "cs-triage",
        [
            "The dashboard won't load — I just get a blank screen.",
            "I'm on Chrome 124, macOS Sonoma.",
        ],
        session_id="demo-tech-1",
    )

    # Scenario 3: white-label override — same agents, different brand name
    print("\n\033[1mScenario 3: White-label override (Beta Corp)\033[0m")
    await run_conversation(
        tenant_id,
        "cs-triage",
        ["Can I get a refund for my last payment?"],
        session_id="demo-beta-1",
        template_var_overrides={"company_name": "Beta Corp"},
    )

    os.unlink(settings.db_path)


if __name__ == "__main__":
    asyncio.run(main())
