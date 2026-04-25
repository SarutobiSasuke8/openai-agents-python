# Session Log — 2026-04-25

## Session Summary

**Branch:** `claude/multi-agent-framework-PzBLB`
**Goal:** Build a production-ready multi-agent framework product on top of the OpenAI Agents Python SDK.

---

## Work Completed This Session

### Core Framework (`product/`)

- **`product/config.py`** — Settings dataclass reading from env vars (`DEFAULT_MODEL`, `DEFAULT_MODEL_FAST`, `PRODUCT_DB_PATH`, etc.). Added OpenRouter + LiteLLM setup docs in module docstring.
- **`product/database.py`** — aiosqlite schema: `tenants`, `agent_definitions`, `runs` tables.
- **`product/models.py`** — Pydantic v2 models: `AgentDefCreate`, `HandoffConfig`, `AgentConfig`, `RunRequest`, `RunResponse`, `ToolInfo`.
- **`product/tools.py`** — Global named tool registry (`@register_tool`). Built-in tools: `get_current_datetime`, `calculate`.
- **`product/builder.py`** — Core "variable application" logic. `build_agent()` expands `{template_vars}` in instructions, resolves tools by name, creates lazy handoffs.
- **`product/registry.py`** — Async CRUD for tenants, agent definitions, runs.
- **`product/auth.py`** — Bearer token auth per tenant, X-Admin-Key for admin routes.
- **`product/api.py`** — FastAPI app: 14 routes including sync run, SSE streaming run, CRUD on agents.

### Examples (`product/examples/`)

| File | Use Case | Key Agents | Status |
|------|----------|-----------|--------|
| `customer_support.py` | CS triage + routing | cs-triage, cs-billing, cs-tech | ✅ Complete |
| `research_assistant.py` | Research + synthesis | research-coordinator, researcher, analyst | ✅ Complete |
| `content_pipeline.py` | Content creation pipeline | content-briefer, content-writer, content-editor | ✅ Complete |
| `code_review.py` | PR code review | review-coordinator, security-reviewer, quality-reviewer | ✅ Complete |
| `sales_pipeline.py` | B2B sales automation | sales-coordinator, lead-qualifier, outreach-writer, objection-handler | ✅ Complete |

### Documentation

- **`product/USAGE.md`** — End-to-end walkthrough: curl commands, session continuity, template var overrides, live agent updates.
- **`product/USE_CASES.md`** — Consolidated guide for all 5 use cases: agent configs, tool tables, example I/O, provider setup.

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Agents stored as JSON in SQLite | "Variable application" — agents are data, not code. Hot-update without redeploy. |
| Lazy handoffs | Target agents loaded from registry at call time. Allows circular graphs and live updates. |
| Named tool registry | Tools registered globally by name; agent JSON references by string. Decouples tool code from agent config. |
| Template vars in instructions | `{var}` placeholders expanded at build time. Per-run overrides enable white-labelling without new agent defs. |
| `DEFAULT_MODEL` / `DEFAULT_MODEL_FAST` env vars | All examples provider-agnostic. OpenRouter enables single API key across 200+ models. |

---

## Known Gaps (Deferred)

- `model_settings` in `AgentConfig` stored in DB but not wired through `builder.py` to SDK `ModelSettings`.
- SSE text delta detection relies on `event.type == "response.output_text.delta"` string match — fragile.
- No eager validation of handoff target slugs at agent creation time (fail-late).
- `str.format_map()` in builder raises `KeyError` if a `{var}` is used in instructions but missing from `template_vars`.
- No tests for the `product/` layer.

---

## Commits This Session

| Hash | Message |
|------|---------|
| `957a830` | feat: add product/ multi-agent platform framework |
| `0ad7a98` | chore: update uv.lock after environment sync |
| `51b1c21` | docs: add USAGE.md with end-to-end customer support walkthrough |
| `f45b148` | feat: add three real use case examples to product/examples/ |
| `b650b83` | feat: make examples provider-agnostic via DEFAULT_MODEL env vars |
| *(pending)* | feat: add code review + sales pipeline examples, USE_CASES.md, TODO, ROADMAP |

---

## Next Session Priorities

See `ROADMAP.md` for the full plan. Immediate next steps:
1. Wire `model_settings` through `builder.py`.
2. Add safe template var expansion (catch `KeyError`, return helpful error).
3. Write tests for `product/` layer (registry CRUD, builder, auth).
4. Eager handoff target validation at `create_agent_def` time.
