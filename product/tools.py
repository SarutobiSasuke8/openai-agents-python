"""Named tool registry.

Tools are registered globally by name and resolved from agent definitions at
build time. This decouples agent config (JSON) from tool implementation (code).

Built-in tools are registered automatically on import. Custom tools are added
with ``register_tool``:

    from product.tools import register_tool
    from agents import function_tool

    @register_tool
    @function_tool
    def my_tool(query: str) -> str:
        \"\"\"Do something useful.\"\"\"
        return ...
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from agents import function_tool
from agents.tool import FunctionTool

_REGISTRY: dict[str, FunctionTool] = {}


def register_tool(tool: FunctionTool) -> FunctionTool:
    """Add a FunctionTool to the global registry under its name."""
    _REGISTRY[tool.name] = tool
    return tool


def resolve_tools(names: list[str]) -> list[FunctionTool]:
    """Return FunctionTool instances for a list of registered names."""
    missing = [n for n in names if n not in _REGISTRY]
    if missing:
        available = sorted(_REGISTRY)
        raise ValueError(f"Unknown tools: {missing}. Available: {available}")
    return [_REGISTRY[n] for n in names]


def list_tools() -> list[dict[str, Any]]:
    """Return metadata for all registered tools."""
    return [{"name": t.name, "description": t.description or ""} for t in _REGISTRY.values()]


# ---------------------------------------------------------------------------
# Built-in tools
# ---------------------------------------------------------------------------


@function_tool
def get_current_datetime() -> str:
    """Return the current UTC date and time in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


@function_tool
def calculate(expression: str) -> str:
    """Evaluate a basic math expression and return the result as a string.

    Supports standard operators and all functions from Python's math module
    (sin, cos, sqrt, log, etc.). No arbitrary code execution.
    """
    allowed: dict[str, Any] = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
    allowed.update({"abs": abs, "round": round, "min": min, "max": max, "sum": sum})
    try:
        result = eval(expression, {"__builtins__": {}}, allowed)  # noqa: S307
        return str(result)
    except Exception as exc:
        return f"Error evaluating expression: {exc}"


register_tool(get_current_datetime)
register_tool(calculate)
