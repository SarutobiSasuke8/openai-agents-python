# Roadmap — Multi-Agent Framework

A phased plan for maturing the `product/` framework from a working prototype to a
production-grade multi-agent platform.

---

## Phase 0 — Foundation ✅ (Complete)

**Goal:** Prove the "variable application" model works end-to-end.

- [x] Core framework: config, database, models, tool registry, builder, registry, auth, REST API.
- [x] Five production-ready example use cases (customer support, research, content, code review, sales).
- [x] Provider-agnostic model config via env vars (OpenRouter single key, LiteLLM).
- [x] Session continuity via `SQLiteSession`.
- [x] Template vars + per-run overrides for white-labelling.
- [x] Lazy handoffs enabling hot agent config updates without restart.

---

## Phase 1 — Hardening (Next)

**Goal:** Make the framework production-safe — no silent failures, proper validation, test coverage.

### Bug Fixes

- [ ] Wire `model_settings` from `AgentConfig` into SDK `ModelSettings` in `builder.py`.
- [ ] Safe template var expansion — catch missing vars, surface clear errors.
- [ ] Eager handoff target validation at `create_agent_def` time.
- [ ] Robust SSE text delta type check.

### Tests

- [ ] Unit tests: registry CRUD, builder, auth (target ≥80% coverage on `product/`).
- [ ] Integration tests: sync run, SSE stream endpoints.

### Developer Experience

- [ ] Structured logging (`logging` module, configurable log level via env var).
- [ ] Health check endpoint (`GET /v1/health`).
- [ ] Pagination on list endpoints.
- [ ] Run history per agent (`GET /v1/agents/{slug}/runs`).

**Exit criteria:** All tests pass, `make lint` + `make typecheck` clean, zero silent failures.

---

## Phase 2 — Multi-Tenancy & Scale

**Goal:** Support multiple teams/customers on a shared instance with proper isolation.

- [ ] Per-tenant tool registries — tools scoped to a tenant, not global.
- [ ] Rate limiting per tenant (requests/minute, configurable via `AgentConfig`).
- [ ] Agent versioning — publish new version without overwriting live config.
- [ ] Webhook callbacks on run complete/error.
- [ ] Input/output guardrails as pluggable hooks.
- [ ] Postgres backend (asyncpg) alongside SQLite for dev.

**Exit criteria:** Two tenants can run isolated pipelines on the same instance with no data bleed.

---

## Phase 3 — Observability & Operations

**Goal:** Make production incidents diagnosable and the system self-healing.

- [ ] OpenTelemetry traces per run and per agent turn.
- [ ] Metrics endpoint (Prometheus-compatible): run count, error rate, latency p95.
- [ ] Run replay — rerun a stored run input against the current agent config.
- [ ] Alerting hooks — POST to Slack/PagerDuty on critical errors.
- [ ] Admin dashboard — basic web UI for tenant management and run history.

---

## Phase 4 — Ecosystem & Distribution

**Goal:** Make it easy to build new use cases and deploy anywhere.

- [ ] Plugin system — load tool modules dynamically from a config path (no code deploy for new tools).
- [ ] One-click deploy targets: Railway, Render, Fly.io with `Dockerfile` + `docker-compose.yml`.
- [ ] MCP server integration — expose agents as MCP tools consumable by other agents.
- [ ] Agent marketplace — shareable agent definition YAML/JSON with a registry.
- [ ] Python SDK — `pip install agents-product` with a client library for the REST API.
- [ ] Auto-generated API docs from FastAPI OpenAPI schema.

---

## Long-Term Vision

A self-serve platform where:
- Non-engineers define agents in a web UI (YAML/JSON editor).
- Teams deploy multi-agent pipelines without writing Python.
- A library of pre-built agents (support, research, content, sales, code review) ships out of the box.
- Providers swap in/out via a single env var — no vendor lock-in.

---

## Version History

| Version | Milestone | Status |
|---------|-----------|--------|
| v0.1 | Core framework + 5 examples | ✅ Done |
| v0.2 | Phase 1 hardening | Planned |
| v0.3 | Phase 2 multi-tenancy | Planned |
| v1.0 | Phase 3 observability | Planned |
