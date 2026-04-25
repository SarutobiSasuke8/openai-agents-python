# Deployment Guide

How to get this multi-agent framework running in production.

**Honest difficulty rating:**
- Local → working API on Railway/Render: **~1–2 hours** (straightforward)
- Production-grade with Postgres, logging, and a custom domain: **~1 day**
- Horizontally scaled / high availability: **out of scope until Phase 3**

---

## What You're Deploying

A single FastAPI process backed by SQLite. The stack is intentionally minimal:

```
Internet → FastAPI (product/api.py)
                ↓
           SQLite DB (aiosqlite)
                ↓
        OpenAI-compatible LLM API
        (OpenRouter / OpenAI / Anthropic via LiteLLM)
```

One process, one file, no external services required to get started.

---

## Step 1 — Get an LLM API Key

The fastest path is **OpenRouter** — one key, 200+ models, no per-provider accounts needed.

1. Sign up at [openrouter.ai](https://openrouter.ai)
2. Generate an API key (`sk-or-v1-...`)
3. Add credits (pay-as-you-go, starts at $5)

You'll set this as `OPENAI_API_KEY` in your deployment environment. No code changes needed.

---

## Step 2 — Add a Start Command

The framework needs a uvicorn entrypoint. Add this to the repo root:

**`product/main.py`** (create this file):

```python
"""Production entrypoint."""
import uvicorn
from product.api import app  # noqa: F401 — imported for side effects

if __name__ == "__main__":
    from product.config import settings
    uvicorn.run("product.api:app", host=settings.host, port=settings.port, reload=False)
```

Or just use the CLI directly (no extra file needed):

```bash
uv run uvicorn product.api:app --host 0.0.0.0 --port 8000
```

---

## Step 3 — Choose a Platform

### Option A — Railway (Recommended for getting started)

**Time:** ~20 minutes. No config files required.

1. Push this repo to GitHub.
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub repo.
3. Railway auto-detects Python. Set the start command:
   ```
   uv run uvicorn product.api:app --host 0.0.0.0 --port $PORT
   ```
4. Add environment variables (see Step 4).
5. Click Deploy. Railway gives you a public HTTPS URL.

**SQLite persistence:** Railway volumes are ephemeral by default. Add a Railway Volume:
- Go to your service → Storage → Add Volume → mount at `/data`
- Set `PRODUCT_DB_PATH=/data/product.db` in env vars

---

### Option B — Render

**Time:** ~20 minutes.

1. Push to GitHub.
2. Go to [render.com](https://render.com) → New Web Service → connect your repo.
3. Set:
   - **Build command:** `pip install uv && uv sync`
   - **Start command:** `uv run uvicorn product.api:app --host 0.0.0.0 --port $PORT`
4. Add environment variables (see Step 4).
5. For persistence: create a Render Disk → mount at `/data` → set `PRODUCT_DB_PATH=/data/product.db`.

---

### Option C — Docker (deploy anywhere: Fly.io, DigitalOcean, AWS, etc.)

Add a `Dockerfile` to the repo root:

```dockerfile
FROM python:3.12-slim

WORKDIR /app
RUN pip install uv

COPY pyproject.toml uv.lock ./
COPY src/ src/
COPY product/ product/
COPY agents/ agents/ 2>/dev/null || true

RUN uv sync --no-dev

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "product.api:app", "--host", "0.0.0.0", "--port", "8000"]
```

Build and run locally to verify:

```bash
docker build -t agents-framework .
docker run -p 8000:8000 \
  -e OPENAI_API_KEY=sk-or-v1-... \
  -e OPENAI_BASE_URL=https://openrouter.ai/api/v1 \
  -e ADMIN_KEY=change-me \
  agents-framework
```

Deploy to **Fly.io**:

```bash
fly launch          # generates fly.toml
fly volumes create data --size 1   # persistent SQLite
fly secrets set OPENAI_API_KEY=sk-or-v1-... ADMIN_KEY=change-me
fly deploy
```

---

## Step 4 — Environment Variables

Set these in your platform's environment/secrets panel:

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | Your OpenRouter (or OpenAI) API key |
| `OPENAI_BASE_URL` | OpenRouter only | `https://openrouter.ai/api/v1` |
| `DEFAULT_MODEL` | No | Default: `gpt-4o`. Recommend: `anthropic/claude-sonnet-4-6` |
| `DEFAULT_MODEL_FAST` | No | Default: `gpt-4o-mini`. Recommend: `anthropic/claude-haiku-4-5` |
| `ADMIN_KEY` | Yes | Secret for provisioning tenants — pick something strong |
| `PRODUCT_DB_PATH` | No | Default: `product.db`. Set to `/data/product.db` with a volume. |
| `HOST` | No | Default: `0.0.0.0` |
| `PORT` | No | Default: `8000`. Railway/Render inject `$PORT` automatically. |

---

## Step 5 — First Run Checklist

Once deployed, verify everything works with three curl commands:

**1. Create a tenant:**
```bash
curl -X POST https://your-app.railway.app/v1/admin/tenants \
  -H "X-Admin-Key: change-me" \
  -H "Content-Type: application/json" \
  -d '{"name": "My Team"}'
# → {"id": "...", "api_key": "sk-prod-..."}
```

**2. Create an agent:**
```bash
curl -X POST https://your-app.railway.app/v1/agents \
  -H "Authorization: Bearer sk-prod-..." \
  -H "Content-Type: application/json" \
  -d '{
    "slug": "hello",
    "name": "Hello Agent",
    "instructions": "You are a helpful assistant. Answer concisely.",
    "model": "anthropic/claude-haiku-4-5",
    "tools": [],
    "handoffs": []
  }'
```

**3. Run it:**
```bash
curl -X POST https://your-app.railway.app/v1/agents/hello/run \
  -H "Authorization: Bearer sk-prod-..." \
  -H "Content-Type: application/json" \
  -d '{"input": "What is 2 + 2?"}'
# → {"output": "4.", "run_id": "..."}
```

If all three work, the deployment is healthy.

---

## Step 6 — Load One of the Use Case Examples

Each example in `product/examples/` is self-contained. To load a pipeline into your
deployed instance via the API, replicate what the example's `setup()` function does —
call `POST /v1/agents` for each agent definition in the pipeline.

For example, to deploy the research assistant:

```bash
# Researcher agent
curl -X POST https://your-app.railway.app/v1/agents \
  -H "Authorization: Bearer sk-prod-..." \
  -H "Content-Type: application/json" \
  -d '{
    "slug": "researcher",
    "name": "Web Researcher",
    "instructions": "You are a thorough web researcher...",
    "model": "anthropic/claude-haiku-4-5",
    "tools": ["search_web", "fetch_article", "save_note"],
    "handoffs": []
  }'

# ... repeat for analyst and research-coordinator
```

Or write a small provisioning script that calls the API for each agent in the pipeline —
the same pattern as the `setup()` functions in the examples.

---

## Known Limitations Before You Scale

These are fine for an MVP but will need addressing under load:

| Limitation | Impact | Fix |
|------------|--------|-----|
| SQLite single-file DB | No horizontal scaling (one instance only) | Swap to Postgres (Phase 2) |
| Global tool registry | All tenants share the same tools | Per-tenant tool scoping (Phase 2) |
| No rate limiting | One tenant can monopolise the process | Add per-tenant rate limiting (Phase 2) |
| No structured logging | Hard to debug production issues | Add `logging` + log aggregator (Phase 1) |
| model_settings ignored | Temperature/top_p not passed through | Wire in builder.py (Phase 1) |

For a single team or low-traffic product, none of these are blockers.

---

## What Good Production Looks Like (Later)

Once the MVP is validated:

1. **Swap SQLite → Postgres** — enables multiple instances, proper backups, connection pooling.
2. **Add structured logging** — ship logs to Datadog / Logtail / CloudWatch.
3. **Set up a custom domain** — add to Railway/Render, configure DNS.
4. **Enable rate limiting** — protect against runaway agent loops burning LLM credits.
5. **Add a health check** — `GET /v1/health` for uptime monitoring.
6. **CI/CD** — GitHub Actions runs `make lint && make typecheck && make tests` on every PR, deploys on merge to main.

See `ROADMAP.md` for the full phased plan.
