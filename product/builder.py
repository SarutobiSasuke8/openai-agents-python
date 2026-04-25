"""Dynamic agent builder: converts a registry AgentDef dict into an SDK Agent.

This is the heart of the variable-application design. No code changes are
needed to deploy a new agent; every property — instructions, model, tools,
and the full handoff graph — is driven by the JSON stored in the registry.

Key design decisions
--------------------
* Template vars: ``{var}`` placeholders in ``instructions`` are expanded at
  build time using the merged vars from the agent definition and the per-run
  override dict passed to ``build_agent``.

* Lazy handoffs: target agents are resolved from the registry at the moment
  the handoff is *invoked*, not at build time. This means circular handoff
  graphs work and agents can reference each other without ordering concerns.

* Tool resolution: tools are looked up by name from the global tool registry
  (``product.tools``). A missing name raises an error immediately so
  misconfigured agents are caught early.
"""

from __future__ import annotations

import json
from typing import Any

from agents import Agent, RunContextWrapper
from agents.handoffs import Handoff

from .tools import resolve_tools


def build_agent(
    defn: dict[str, Any],
    tenant_id: str,
    template_var_overrides: dict[str, str] | None = None,
    model_override: str | None = None,
) -> Agent[Any]:
    """Return an SDK Agent constructed from a registry agent-definition dict.

    Args:
        defn: Raw dict as stored in the DB (id, slug, name, instructions,
              model, tools_json, handoffs_json, config_json).
        tenant_id: The owning tenant; passed to lazy handoffs so they can
                   query the same tenant's registry.
        template_var_overrides: Per-run ``{var}`` values that take precedence
                                over the definition's ``config.template_vars``.
        model_override: Per-run model override; wins over the definition's
                        model field.
    """
    config: dict[str, Any] = json.loads(defn["config_json"])
    tools_names: list[str] = json.loads(defn["tools_json"])
    handoff_configs: list[dict[str, Any]] = json.loads(defn["handoffs_json"])

    # --- resolve instructions template ---
    base_vars: dict[str, str] = config.get("template_vars", {})
    merged_vars = {**base_vars, **(template_var_overrides or {})}
    instructions: str = (
        defn["instructions"].format_map(merged_vars) if merged_vars else defn["instructions"]
    )

    # --- resolve tools ---
    tools = resolve_tools(tools_names)

    # --- resolve model ---
    from .config import settings

    model: str = model_override or defn.get("model") or settings.default_model

    # --- build lazy handoffs ---
    handoffs: list[Handoff[Any, Any]] = [
        _make_lazy_handoff(hc["target_slug"], hc.get("description", ""), tenant_id)
        for hc in handoff_configs
    ]

    return Agent(
        name=defn["name"],
        instructions=instructions,
        model=model,
        tools=tools,
        handoffs=handoffs,
    )


def _make_lazy_handoff(
    target_slug: str,
    description: str,
    tenant_id: str,
) -> Handoff[Any, Any]:
    """Create a Handoff whose target agent is loaded from the registry on demand.

    The target is resolved at invocation time, not at build time, so:
    * Circular / mutual handoff graphs work.
    * Hot-updated agent definitions are picked up on the next invocation.
    """

    async def _on_invoke(ctx: RunContextWrapper[Any], _input: str) -> Agent[Any]:
        from .registry import get_agent_def

        target_defn = await get_agent_def(tenant_id, target_slug)
        if target_defn is None:
            raise ValueError(
                f"Handoff target agent '{target_slug}' not found for tenant '{tenant_id}'."
            )
        return build_agent(target_defn, tenant_id)

    safe_name = target_slug.replace("-", "_")
    return Handoff(
        tool_name=f"transfer_to_{safe_name}",
        tool_description=description,
        input_json_schema={"type": "object", "properties": {}, "additionalProperties": False},
        on_invoke_handoff=_on_invoke,
        agent_name=target_slug,
    )
