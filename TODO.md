# TODO

Tracked work items for the multi-agent framework product layer (`product/`).

---

## Active

- [ ] Wire `model_settings` from `AgentConfig` through `builder.py` to SDK `ModelSettings` — currently stored in DB but ignored at build time.
- [ ] Safe template var expansion in `builder.py` — catch `KeyError` when `{var}` is in instructions but missing from `template_vars`; surface a clear error instead of crashing.
- [ ] Eager handoff target validation — validate that all `HandoffConfig.target_slug` values exist in the registry at `create_agent_def` time, not at call time.
- [ ] Robust SSE text delta detection in `api.py` — current `getattr(raw, "type") == "response.output_text.delta"` string match is fragile; use a proper SDK type check.

---

## Tests

- [ ] Unit tests for `product/registry.py` — CRUD for tenants, agent defs, runs.
- [ ] Unit tests for `product/builder.py` — template var expansion, tool resolution, lazy handoff wiring.
- [ ] Unit tests for `product/auth.py` — Bearer token lookup, admin key check, missing/invalid cases.
- [ ] Integration test for the sync run endpoint (`POST /v1/agents/{slug}/run`).
- [ ] Integration test for the SSE stream endpoint (`POST /v1/agents/{slug}/run/stream`).

---

## Features

- [ ] Pagination on `GET /v1/agents` — return `limit`/`offset` + total count.
- [ ] Run history per agent — `GET /v1/agents/{slug}/runs`.
- [ ] Agent versioning — allow publishing a new version of an agent def without overwriting the live version.
- [ ] Input/output guardrails — pluggable pre/post-run validation hooks via agent config.
- [ ] Multi-tenant isolation for tool registries — tools scoped per tenant rather than globally.
- [ ] Webhook callbacks — POST to a configured URL when a run completes or errors.
- [ ] Rate limiting per tenant — configurable requests-per-minute via `AgentConfig`.

---

## Use Case Tests

End-to-end tests for each example pipeline using mocked LLM responses (no real API calls).

- [ ] **Customer support** — triage routes billing query to cs-billing; triage routes tech query to cs-tech; `lookup_order` and `check_account` tools called with correct args; `create_ticket` fires on escalation.
- [ ] **Research assistant** — coordinator hands off to researcher; researcher calls `search_web` at least twice; `save_note` persists notes; analyst calls `get_notes` and produces a report with Executive Summary section.
- [ ] **Content pipeline** — briefer saves a brief via `save_content('brief', ...)`; writer retrieves it and saves a draft; editor retrieves draft and saves final; `estimate_reading_time` called on final content.
- [ ] **Code review** — security reviewer runs `scan_for_vulnerabilities` on sample code containing SQL injection and logs at least one CRITICAL finding; quality reviewer runs `measure_complexity`; coordinator calls `get_findings` and emits a BLOCK verdict.
- [ ] **Sales pipeline** — high-score lead (confirmed budget, senior title) flows through all three stages and produces an outreach email + objection prep in the CRM; low-score lead is rejected at qualification and does not reach the outreach writer.

---

## Infrastructure

- [ ] Docker Compose setup — FastAPI + SQLite for local dev, swap to Postgres for production.
- [ ] Postgres support — swap aiosqlite for asyncpg, migrate schema.
- [ ] Structured logging — replace `print()` in examples with proper `logging` calls.
- [ ] Health check endpoint — `GET /v1/health` returning DB connectivity status.

---

## Documentation

- [ ] Docstrings on all `product/` modules.
- [ ] API reference — auto-generate from FastAPI OpenAPI schema.
- [ ] Deployment guide — Railway / Render / Fly.io one-click deploy.

---

## Completed

- [x] Core framework: config, database, models, tools registry, builder, registry, auth, API.
- [x] Customer support use case example.
- [x] Research assistant use case example.
- [x] Content pipeline use case example.
- [x] Code review pipeline use case example.
- [x] Sales pipeline use case example.
- [x] USAGE.md end-to-end walkthrough.
- [x] USE_CASES.md consolidated use-case guide.
- [x] Provider-agnostic model config via `DEFAULT_MODEL` / `DEFAULT_MODEL_FAST` env vars.
- [x] OpenRouter single-key setup documented.
