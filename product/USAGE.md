# Multi-Agent Platform — Practical Usage Guide

A walkthrough of the `product/` framework using a real-world scenario: a
customer-support product that routes conversations across three specialised
agents with no code changes required between deployments.

---

## Prerequisites

```bash
# Install dependencies
make sync

# Set your OpenAI key
export OPENAI_API_KEY=sk-...

# Optional overrides (defaults shown)
export PRODUCT_DB_PATH=product.db
export DEFAULT_MODEL=gpt-4o
export MAX_TURNS_DEFAULT=10
export ADMIN_KEY=changeme          # change this in production

# Start the server
uv run uvicorn product.api:app --reload
```

The interactive API docs are at `http://localhost:8000/docs`.

---

## Scenario: Customer Support for "Acme SaaS"

Three agents, each with a focused role:

```
User message
     │
     ▼
 [triage]  ──────── handoff ──────► [billing]
     │
     └─────────── handoff ──────► [tech-support]
```

The triage agent reads the message and either answers directly or hands off.
Billing and tech-support agents handle specialised queries and can escalate back
if needed.

---

## Step 1 — Provision a tenant

The `X-Admin-Key` header authenticates this one-time setup call.

```bash
curl -s -X POST http://localhost:8000/v1/admin/tenants \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: changeme" \
  -d '{"name": "Acme SaaS"}' | tee tenant.json
```

```json
{
  "id": "a1b2c3d4-...",
  "name": "Acme SaaS",
  "api_key": "sk-abcdefg...",
  "created_at": "2026-04-25T10:00:00+00:00"
}
```

Save the `api_key` — it's shown only once. All subsequent calls use:

```bash
export API_KEY="sk-abcdefg..."
AUTH="Authorization: Bearer $API_KEY"
```

---

## Step 2 — Register the three agents

### 2a. Billing agent

```bash
curl -s -X POST http://localhost:8000/v1/agents \
  -H "Content-Type: application/json" \
  -H "$AUTH" \
  -d '{
    "slug": "billing",
    "name": "Billing Agent",
    "instructions": "You are the billing specialist for {company_name}. Help users with invoices, refunds, and subscription changes. Be concise and empathetic.",
    "model": "gpt-4o",
    "tools": ["get_current_datetime"],
    "handoffs": [],
    "config": {
      "max_turns": 8,
      "template_vars": {"company_name": "Acme SaaS"}
    }
  }'
```

### 2b. Tech-support agent

```bash
curl -s -X POST http://localhost:8000/v1/agents \
  -H "Content-Type: application/json" \
  -H "$AUTH" \
  -d '{
    "slug": "tech-support",
    "name": "Tech Support Agent",
    "instructions": "You are the technical support engineer for {company_name}. Diagnose bugs, guide users through troubleshooting steps, and escalate if you cannot resolve the issue.",
    "model": "gpt-4o",
    "tools": ["get_current_datetime", "calculate"],
    "handoffs": [],
    "config": {
      "max_turns": 12,
      "template_vars": {"company_name": "Acme SaaS"}
    }
  }'
```

### 2c. Triage agent (references the two above by slug)

```bash
curl -s -X POST http://localhost:8000/v1/agents \
  -H "Content-Type: application/json" \
  -H "$AUTH" \
  -d '{
    "slug": "triage",
    "name": "Triage Agent",
    "instructions": "You are the first point of contact for {company_name} customer support. Greet the user, understand their issue, and either resolve it yourself or transfer to the right specialist. Transfer billing questions to billing, and technical/product bugs to tech-support.",
    "model": "gpt-4o-mini",
    "tools": [],
    "handoffs": [
      {
        "target_slug": "billing",
        "description": "Transfer to billing for invoice, refund, or subscription questions."
      },
      {
        "target_slug": "tech-support",
        "description": "Transfer to tech support for bugs, errors, or product issues."
      }
    ],
    "config": {
      "max_turns": 5,
      "template_vars": {"company_name": "Acme SaaS"}
    }
  }'
```

> **Note:** `triage` references `billing` and `tech-support` by slug. The
> target agents are resolved lazily at handoff time, so registration order
> doesn't matter and you can update a target agent's instructions without
> touching the triage config.

---

## Step 3 — Run a conversation (sync)

```bash
curl -s -X POST http://localhost:8000/v1/agents/triage/run \
  -H "Content-Type: application/json" \
  -H "$AUTH" \
  -d '{
    "input": "Hi, I was charged twice for my subscription this month.",
    "session_id": "user-123-session-1"
  }'
```

```json
{
  "run_id": "r-...",
  "agent_slug": "triage",
  "session_id": "user-123-session-1",
  "status": "completed",
  "output": "I'm sorry to hear that! I'm transferring you to our billing team right away — they'll get this sorted out for you.",
  "tokens_used": 312,
  "error": null,
  "created_at": "2026-04-25T10:05:00+00:00",
  "completed_at": "2026-04-25T10:05:03+00:00"
}
```

### Continue the conversation

Pass the same `session_id` on follow-up messages. The SDK's `SQLiteSession`
replays the full history so the agent has context:

```bash
curl -s -X POST http://localhost:8000/v1/agents/triage/run \
  -H "Content-Type: application/json" \
  -H "$AUTH" \
  -d '{
    "input": "The double charge was on April 3rd.",
    "session_id": "user-123-session-1"
  }'
```

---

## Step 4 — Stream a response (SSE)

Use the `/run/stream` endpoint for real-time output, e.g. in a chat UI.

```bash
curl -s -X POST http://localhost:8000/v1/agents/triage/run/stream \
  -H "Content-Type: application/json" \
  -H "$AUTH" \
  -N \
  -d '{
    "input": "My dashboard stopped loading after the latest update.",
    "session_id": "user-456-session-1"
  }'
```

The server sends [Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events):

```
event: agent_start
data: {"agent": "Triage Agent"}

event: text_delta
data: {"text": "I'm sorry"}

event: text_delta
data: {"text": " to hear that. Let me"}

event: handoff
data: {"target_agent": "tech-support"}

event: agent_start
data: {"agent": "Tech Support Agent"}

event: text_delta
data: {"text": "Thanks for reaching out! Could you tell me which browser"}

event: done
data: {"run_id": "r-...", "session_id": "user-456-session-1", "output": "...", "tokens_used": 445}
```

### Consuming SSE in JavaScript

```javascript
const response = await fetch('/v1/agents/triage/run/stream', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${apiKey}`,
  },
  body: JSON.stringify({ input: userMessage, session_id: sessionId }),
});

const reader = response.body.getReader();
const decoder = new TextDecoder();
let buffer = '';

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  buffer += decoder.decode(value, { stream: true });

  for (const line of buffer.split('\n\n')) {
    const eventLine = line.match(/^event: (\w+)/)?.[1];
    const dataLine = line.match(/^data: (.+)/s)?.[1];
    if (!eventLine || !dataLine) continue;

    const payload = JSON.parse(dataLine);
    if (eventLine === 'text_delta') appendToChat(payload.text);
    if (eventLine === 'done')      finaliseMessage(payload);
    if (eventLine === 'error')     showError(payload.message);
  }
  buffer = '';
}
```

---

## Step 5 — Override branding at runtime

`template_vars` in the request body override the agent definition's defaults.
This lets a single agent definition serve multiple brands with no schema changes:

```bash
# Same triage agent, different company name
curl -s -X POST http://localhost:8000/v1/agents/triage/run \
  -H "Content-Type: application/json" \
  -H "$AUTH" \
  -d '{
    "input": "I need help with my account.",
    "template_vars": {"company_name": "Beta Corp"}
  }'
```

The agent will greet as "Beta Corp support" without any DB update.

---

## Step 6 — Update an agent without downtime

Swap out instructions or model for a live agent — the next run picks up the
change immediately:

```bash
curl -s -X PUT http://localhost:8000/v1/agents/tech-support \
  -H "Content-Type: application/json" \
  -H "$AUTH" \
  -d '{
    "instructions": "You are a senior technical support engineer for {company_name}. Always ask for the user'\''s browser and OS before diagnosing. Escalate P0 bugs to the engineering channel.",
    "model": "gpt-4o"
  }'
```

---

## Step 7 — Register a custom tool

Add a new tool in code and it's immediately available to any agent by name:

```python
# product/tools.py  (add to the bottom)
from agents import function_tool
from .tools import register_tool

@register_tool
@function_tool
def lookup_order(order_id: str) -> str:
    """Retrieve order status from the internal system."""
    # Replace with a real DB/API call.
    return f"Order {order_id}: shipped on 2026-04-20, arriving 2026-04-27."
```

Then reference it in any agent definition:

```bash
curl -s -X PUT http://localhost:8000/v1/agents/billing \
  -H "Content-Type: application/json" \
  -H "$AUTH" \
  -d '{"tools": ["get_current_datetime", "lookup_order"]}'
```

---

## Step 8 — Inspect run history

```bash
curl -s http://localhost:8000/v1/runs/<run_id> \
  -H "$AUTH"
```

```json
{
  "run_id": "r-...",
  "agent_slug": "triage",
  "session_id": "user-123-session-1",
  "status": "completed",
  "output": "...",
  "tokens_used": 312,
  "error": null,
  "created_at": "...",
  "completed_at": "..."
}
```

---

## Environment reference

| Variable            | Default       | Description                            |
|---------------------|---------------|----------------------------------------|
| `OPENAI_API_KEY`    | —             | Required. Your OpenAI API key.         |
| `PRODUCT_DB_PATH`   | `product.db`  | SQLite file path.                      |
| `DEFAULT_MODEL`     | `gpt-4o`      | Fallback model when agent omits one.   |
| `MAX_TURNS_DEFAULT` | `10`          | Fallback max turns per run.            |
| `ADMIN_KEY`         | `changeme`    | Secret for `/v1/admin/tenants`.        |
| `HOST`              | `0.0.0.0`     | Bind host for uvicorn.                 |
| `PORT`              | `8000`        | Bind port for uvicorn.                 |

---

## Agent definition reference

```jsonc
{
  "slug": "my-agent",           // URL-safe identifier; unique per tenant
  "name": "My Agent",           // Display name shown in traces
  "instructions": "You are a helpful agent for {company}.",
                                // {var} placeholders expanded at run time
  "model": "gpt-4o",            // null → falls back to DEFAULT_MODEL
  "tools": [                    // Names from the tool registry
    "get_current_datetime",
    "calculate"
  ],
  "handoffs": [                 // Other agents this one can transfer to
    {
      "target_slug": "billing",
      "description": "Transfer for payment questions."
    }
  ],
  "config": {
    "max_turns": 10,            // null → MAX_TURNS_DEFAULT
    "template_vars": {          // Default values for {var} placeholders
      "company": "Acme"
    },
    "model_settings": {}        // Reserved; not yet wired to ModelSettings
  }
}
```

---

## Architecture overview

```
┌─────────────────────────────────────────────────────┐
│                   product/api.py                    │
│  REST endpoints + SSE streaming (FastAPI)           │
└────────────────────────┬────────────────────────────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
   product/         product/       product/
   registry.py      builder.py     tools.py
   (SQLite CRUD)    (JSON→Agent)   (named registry)
          │              │
          ▼              ▼
   product/         agents SDK
   database.py      Runner, Agent,
   (aiosqlite)      SQLiteSession,
                    Handoff, …
```

**Data flow for a run:**
1. Request arrives at `POST /v1/agents/{slug}/run`.
2. `registry.py` loads the agent definition from SQLite.
3. `builder.py` expands template vars, resolves tool names, and wires lazy handoffs.
4. `Runner.run()` (or `run_streamed()`) executes the agent graph.
5. If a handoff fires, `builder.py` loads the target agent from the registry at that moment.
6. Result is written back to the `runs` table and returned to the caller.
