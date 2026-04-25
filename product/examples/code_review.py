"""Code Review Pipeline — automated PR review across security and quality dimensions.

A coordinator agent splits an incoming code diff into parallel review workstreams,
delegating to a security reviewer and a code-quality reviewer, then synthesises
the findings into a single structured report.

Demonstrates:
  - Parallel specialist handoffs (coordinator → security + quality reviewers)
  - Structured output with severity levels and actionable suggestions
  - Code-analysis tools (pattern matching, complexity, line counting)
  - Template vars for team-specific review standards ({language}, {severity_threshold})

Run:
    OPENAI_API_KEY=sk-... uv run python -m product.examples.code_review
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

_FINDINGS: list[dict[str, str]] = []

_VULN_PATTERNS = {
    "sql_injection": ['f"SELECT', 'f"SELECT', "execute(f", "% sql", "+ sql"],
    "hardcoded_secret": ["password =", "api_key =", "secret =", "token =", 'AWS_SECRET"'],
    "insecure_random": ["random.random()", "random.randint(", "Math.random()"],
    "eval_exec": ["eval(", "exec(", "os.system(", "subprocess.call(shell=True"],
    "open_redirect": ["redirect(request.GET", "redirect(request.args"],
}


@register_tool
@function_tool
def scan_for_vulnerabilities(code: str) -> str:
    """Scan code for common security vulnerability patterns.

    Returns a list of detected issues with line references where possible.
    """
    issues = []
    lines = code.splitlines()
    for i, line in enumerate(lines, 1):
        for vuln_type, patterns in _VULN_PATTERNS.items():
            if any(p.lower() in line.lower() for p in patterns):
                issues.append(f"Line {i} [{vuln_type.upper()}]: {line.strip()}")
    if not issues:
        return "No common vulnerability patterns detected."
    return f"Found {len(issues)} potential issue(s):\n" + "\n".join(issues)


@register_tool
@function_tool
def measure_complexity(code: str) -> str:
    """Estimate code complexity: function count, nesting depth, and line count."""
    lines = code.splitlines()
    func_count = sum(
        1 for ln in lines if ln.strip().startswith(("def ", "function ", "async def "))
    )
    max_indent = max((len(ln) - len(ln.lstrip()) for ln in lines if ln.strip()), default=0) // 4
    return (
        f"Lines: {len(lines)}, "
        f"Functions/methods: {func_count}, "
        f"Max nesting depth: ~{max_indent} levels"
    )


@register_tool
@function_tool
def log_finding(severity: str, category: str, description: str, suggestion: str) -> str:
    """Record a review finding for inclusion in the final report.

    Args:
        severity: 'critical', 'high', 'medium', or 'low'.
        category: e.g. 'security', 'performance', 'maintainability', 'style'.
        description: What the issue is.
        suggestion: How to fix or improve it.
    """
    _FINDINGS.append(
        {
            "severity": severity,
            "category": category,
            "description": description,
            "suggestion": suggestion,
        }
    )
    return f"Finding logged: [{severity.upper()}] {category} — {description[:60]}…"


@register_tool
@function_tool
def get_findings() -> str:
    """Retrieve all logged review findings for synthesis into a final report."""
    if not _FINDINGS:
        return "No findings logged yet."
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    sorted_findings = sorted(_FINDINGS, key=lambda f: order.get(f["severity"], 9))
    lines = []
    for f in sorted_findings:
        lines.append(
            f"[{f['severity'].upper()}] {f['category'].title()}\n"
            f"  Issue: {f['description']}\n"
            f"  Fix:   {f['suggestion']}"
        )
    return f"{len(_FINDINGS)} finding(s):\n\n" + "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Agent definitions
# ---------------------------------------------------------------------------

_AGENTS: list[AgentDefCreate] = [
    AgentDefCreate(
        slug="security-reviewer",
        name="Security Reviewer",
        instructions=(
            "You are an expert security code reviewer specialising in {language} applications.\n"
            "Review the provided code for security vulnerabilities.\n\n"
            "Steps:\n"
            "1. Run scan_for_vulnerabilities on the code.\n"
            "2. For each detected issue, log a finding with log_finding using severity "
            "   'critical' or 'high' as appropriate.\n"
            "3. Also look for logical security issues not caught by pattern scanning "
            "   (e.g. missing auth checks, unsafe deserialization, insecure defaults).\n"
            "4. Log those findings too.\n"
            "5. Summarise what you reviewed and how many security issues you found."
        ),
        model=settings.default_model_fast,
        tools=["scan_for_vulnerabilities", "log_finding"],
        handoffs=[],
        config=AgentConfig(
            max_turns=8,
            template_vars={"language": "Python"},
        ),
    ),
    AgentDefCreate(
        slug="quality-reviewer",
        name="Code Quality Reviewer",
        instructions=(
            "You are a senior {language} engineer reviewing code quality.\n"
            "Review the provided code for maintainability, style, and correctness.\n\n"
            "Steps:\n"
            "1. Run measure_complexity to understand the code structure.\n"
            "2. Identify issues in: naming, error handling, code duplication, "
            "   missing tests/documentation, performance, and readability.\n"
            "3. Log each issue with log_finding using severity 'medium' or 'low'.\n"
            "4. Summarise the overall quality and your top 3 improvement suggestions."
        ),
        model=settings.default_model_fast,
        tools=["measure_complexity", "log_finding"],
        handoffs=[],
        config=AgentConfig(
            max_turns=8,
            template_vars={"language": "Python"},
        ),
    ),
    AgentDefCreate(
        slug="review-coordinator",
        name="Review Coordinator",
        instructions=(
            "You are a lead {language} engineer coordinating a pull request review.\n\n"
            "When given a code diff or snippet:\n"
            "1. Briefly acknowledge the code and hand off to the Security Reviewer.\n"
            "2. After security review, hand off to the Code Quality Reviewer.\n"
            "3. After quality review, call get_findings to collect all logged issues.\n"
            "4. Produce a final structured PR review:\n"
            "   ## PR Review Summary\n"
            "   - **Verdict:** APPROVE / REQUEST CHANGES / BLOCK\n"
            "   - **Critical issues:** (count)\n"
            "   - **Total findings:** (count)\n"
            "   ## Findings (by severity)\n"
            "   (list all findings)\n"
            "   ## Recommendation\n"
            "   (overall guidance)\n\n"
            "Block if any critical findings. Request changes if any high findings. "
            "Approve only if medium/low only."
        ),
        model=settings.default_model,
        tools=["get_findings"],
        handoffs=[
            HandoffConfig(
                target_slug="security-reviewer",
                description="Delegate security vulnerability scanning to the security reviewer.",
            ),
            HandoffConfig(
                target_slug="quality-reviewer",
                description="Delegate code quality review to the quality reviewer.",
            ),
        ],
        config=AgentConfig(
            max_turns=8,
            template_vars={"language": "Python"},
        ),
    ),
]

# ---------------------------------------------------------------------------
# Demo code samples
# ---------------------------------------------------------------------------

_SAMPLE_CODE = """\
import sqlite3, random, os

def get_user(username):
    # Get user from database
    conn = sqlite3.connect("app.db")
    query = f"SELECT * FROM users WHERE username = '{username}'"
    result = conn.execute(query).fetchone()
    return result

def generate_token():
    token = str(random.randint(100000, 999999))
    return token

def reset_password(user_id, new_password):
    password = new_password  # store directly
    conn = sqlite3.connect("app.db")
    conn.execute(f"UPDATE users SET password = '{password}' WHERE id = {user_id}")
    conn.commit()
"""


# ---------------------------------------------------------------------------
# Demo hooks
# ---------------------------------------------------------------------------


class ReviewHooks(RunHooks):  # type: ignore[type-arg]
    async def on_agent_start(self, context: Any, agent: Agent) -> None:  # type: ignore[override]
        print(f"\n  \033[36m[{agent.name}]\033[0m")

    async def on_handoff(self, context: Any, from_agent: Agent, to_agent: Agent) -> None:  # type: ignore[override]
        print(f"  \033[33m↗ Review stage:\033[0m {from_agent.name} → {to_agent.name}")

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


async def run_review(
    tenant_id: str,
    code: str,
    language_override: str | None = None,
) -> None:
    _FINDINGS.clear()
    lang = language_override or "Python"
    print(f"\n\033[32mReviewing {lang} code ({len(code.splitlines())} lines)...\033[0m")

    defn = await get_agent_def(tenant_id, "review-coordinator")
    assert defn is not None
    overrides = {"language": lang} if language_override else None
    agent = build_agent(defn, tenant_id, template_var_overrides=overrides)

    from agents import Runner
    from agents.memory.sqlite_session import SQLiteSession

    session = SQLiteSession(session_id=f"review-{id(code)}", db_path=settings.db_path)
    result = await Runner.run(
        agent,
        f"Please review this {lang} code:\n\n```{lang.lower()}\n{code}\n```",
        max_turns=25,
        hooks=ReviewHooks(),
        session=session,
    )
    print(f"\n\033[34m--- REVIEW REPORT ---\033[0m\n{result.final_output}")


async def main() -> None:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    settings.db_path = tmp.name
    tmp.close()

    await init_db()
    tenant = await create_tenant("Demo — Code Review")
    await setup(tenant["id"])

    print("\n" + "=" * 60)
    print("  CODE REVIEW PIPELINE DEMO")
    print("=" * 60)

    await run_review(tenant["id"], _SAMPLE_CODE)

    os.unlink(settings.db_path)


if __name__ == "__main__":
    asyncio.run(main())
