# Use Cases — Multi-Agent Framework

A practical guide to the five production-ready use cases built on top of this framework.
Each use case is self-contained: copy the example file, wire up your API key, and run.

---

## Provider Setup (One API Key for All Use Cases)

The fastest way to run any use case against any LLM is **OpenRouter** — a single OpenAI-compatible
endpoint that routes to 200+ models (OpenAI, Anthropic, Mistral, Meta, Google, etc.) under one key.

```bash
export OPENAI_API_KEY=sk-or-v1-...           # your OpenRouter key
export OPENAI_BASE_URL=https://openrouter.ai/api/v1

# Pick any models OpenRouter supports:
export DEFAULT_MODEL=anthropic/claude-sonnet-4-6
export DEFAULT_MODEL_FAST=anthropic/claude-haiku-4-5
```

Run any example:

```bash
uv run python -m product.examples.customer_support
uv run python -m product.examples.research_assistant
uv run python -m product.examples.content_pipeline
uv run python -m product.examples.code_review
uv run python -m product.examples.sales_pipeline
```

**Via LiteLLM** (if you want native provider keys without OpenRouter):

```bash
uv sync --extra litellm
export ANTHROPIC_API_KEY=sk-ant-...
export DEFAULT_MODEL=litellm/anthropic/claude-sonnet-4-6
export DEFAULT_MODEL_FAST=litellm/anthropic/claude-haiku-4-5-20251001
```

---

## Use Case 1 — Customer Support

**File:** `product/examples/customer_support.py`

A triage agent classifies inbound support requests and routes them to the appropriate specialist
(billing or technical). The same pipeline handles white-labelled deployments via per-run template
var overrides, so a single agent definition serves multiple brands.

### Agents

| Slug | Role | Model tier |
|------|------|-----------|
| `cs-triage` | Classifies the issue and routes to the right specialist | Fast |
| `cs-billing` | Handles billing disputes, refunds, plan changes | Standard |
| `cs-tech` | Troubleshoots technical issues, escalates if needed | Standard |

### Tools

| Tool | What it does |
|------|-------------|
| `lookup_order` | Returns mock order details for a given order ID |
| `check_account` | Returns account status, plan, and billing info |
| `create_ticket` | Logs an escalation ticket and returns a ticket ID |

### Agent Config (JSON)

```json
{
  "slug": "cs-triage",
  "name": "Support Triage",
  "instructions": "You are a support agent for {brand_name}. Classify and route...",
  "model": "gpt-4o-mini",
  "tools": [],
  "handoffs": [
    { "target_slug": "cs-billing", "description": "Route billing issues here" },
    { "target_slug": "cs-tech",    "description": "Route technical issues here" }
  ],
  "config": {
    "max_turns": 6,
    "template_vars": { "brand_name": "Acme SaaS", "support_email": "help@acme.io" }
  }
}
```

### Example Input → Output

**Input:** "My order #1042 was charged twice last month."

**Pipeline:** cs-triage → cs-billing → (calls `lookup_order`, `check_account`) → resolution

**Output:**
```
I've reviewed order #1042. There was indeed a duplicate charge on 14 March. I've initiated
a full refund of $49.00 — please allow 3–5 business days. Ticket #TKT-8821 has been raised
for your records.
```

### White-Label Override

Run the same pipeline for a different brand at call time:

```python
await run_support(tenant_id, "My invoice is wrong.", brand_overrides={
    "brand_name": "FinFlow",
    "support_email": "support@finflow.io",
})
```

---

## Use Case 2 — Research Assistant

**File:** `product/examples/research_assistant.py`

A coordinator delegates research to a specialist web researcher, then passes collected notes
to an analyst who produces a structured executive report. Replace the mocked search tools with
Brave Search, Tavily, or any retrieval API for production use.

### Agents

| Slug | Role | Model tier |
|------|------|-----------|
| `research-coordinator` | Receives the question, orchestrates handoffs | Fast |
| `researcher` | Searches, fetches articles, saves notes | Fast |
| `analyst` | Retrieves notes, synthesises findings, writes report | Standard |

### Tools

| Tool | What it does |
|------|-------------|
| `search_web` | Keyword search returning titles, URLs, snippets (mocked) |
| `fetch_article` | Fetches full article text by URL (mocked) |
| `save_note` | Saves a keyed research note to the shared store |
| `get_notes` | Returns all saved notes for the analyst to synthesise |

### Agent Config (JSON)

```json
{
  "slug": "analyst",
  "name": "Research Analyst",
  "instructions": "You are a senior research analyst. Retrieve notes with get_notes, identify 3–5 key findings, and produce a structured report...",
  "model": "gpt-4o",
  "tools": ["get_notes"],
  "handoffs": [],
  "config": { "max_turns": 6 }
}
```

### Example Input → Output

**Input:** "What is the current state of quantum computing?"

**Pipeline:** research-coordinator → researcher (searches × 2, fetches articles, saves 3 notes) → analyst

**Output structure:**
```
## Executive Summary
Quantum computing reached two significant milestones in 2023–2024...

## Key Findings
1. IBM's Condor processor achieved 1121 qubits...
2. Google's Willow chip demonstrated below-threshold error correction...
3. Market projected at $450B annually by 2030...

## Implications
...

## Recommended Next Steps
...
```

### Swap in Real Search

```python
@register_tool
@function_tool
def search_web(query: str, max_results: int = 3) -> str:
    import httpx
    resp = httpx.get(
        "https://api.tavily.com/search",
        params={"query": query, "max_results": max_results},
        headers={"Authorization": f"Bearer {os.environ['TAVILY_API_KEY']}"},
    )
    results = resp.json()["results"]
    return "\n\n".join(f"{r['title']}\n{r['url']}\n{r['content'][:200]}" for r in results)
```

---

## Use Case 3 — Content Pipeline

**File:** `product/examples/content_pipeline.py`

A three-stage sequential pipeline: a briefer turns a raw request into a structured brief,
a writer produces a first draft, and an editor polishes and finalises. The same pipeline
serves multiple brands via per-run template var overrides.

### Agents

| Slug | Role | Model tier |
|------|------|-----------|
| `content-briefer` | Turns a request into a structured brief, orchestrates handoffs | Fast |
| `content-writer` | Reads the brief, writes the first draft | Standard |
| `content-editor` | Reads the draft, edits and finalises | Standard |

### Tools

| Tool | What it does |
|------|-------------|
| `save_content` | Saves content at a named pipeline stage (brief / draft / final) |
| `get_content` | Retrieves content from a named stage |
| `word_count` | Counts words in a text |
| `estimate_reading_time` | Estimates reading time at 238 wpm |

### Example Input → Output

**Input:** "Write a short blog post (300 words) explaining why small businesses should automate their invoicing."

**Pipeline:** briefer (saves brief) → writer (reads brief, saves draft, reports word count) → editor (reads draft, saves final, reports reading time)

**Output:**
```
## Why Automating Your Invoicing Is the Smartest Move You'll Make This Year

For most small business owners, invoicing is the last thing on their mind...
(300-word post following the brief exactly)

---
Editor's note: Tightened the opening hook and cut passive voice in paragraph 3.
Estimated read: ~2 minutes.
```

### Multi-Brand in One Run

```python
# Default brand (Acme SaaS)
await run_pipeline(tenant_id, "Write a blog post about AI invoicing.")

# Different brand — same agents, different voice
await run_pipeline(tenant_id, "Write a LinkedIn post about our new AI reporting feature.", brand_overrides={
    "brand_name": "FinFlow",
    "audience": "finance directors at mid-market companies",
    "tone": "authoritative and data-driven",
})
```

---

## Use Case 4 — Code Review Pipeline

**File:** `product/examples/code_review.py`

A coordinator splits a code diff into parallel review workstreams: a security reviewer scans for
vulnerability patterns and logical issues, a quality reviewer measures complexity and flags
maintainability problems. The coordinator synthesises findings into a structured PR review report
with a clear APPROVE / REQUEST CHANGES / BLOCK verdict.

### Agents

| Slug | Role | Model tier |
|------|------|-----------|
| `review-coordinator` | Orchestrates both reviewers, produces final report | Standard |
| `security-reviewer` | Scans for security vulnerabilities | Fast |
| `quality-reviewer` | Reviews maintainability, style, complexity | Fast |

### Tools

| Tool | What it does |
|------|-------------|
| `scan_for_vulnerabilities` | Pattern-matches SQL injection, hardcoded secrets, eval/exec, etc. |
| `measure_complexity` | Reports line count, function count, and nesting depth |
| `log_finding` | Records a finding (severity, category, description, fix suggestion) |
| `get_findings` | Returns all findings sorted by severity |

### Vulnerability Patterns Detected

- SQL injection (f-string query building, `execute(f`, `% sql`)
- Hardcoded secrets (`password =`, `api_key =`, `secret =`)
- Insecure randomness (`random.randint`, `Math.random()`)
- Code execution (`eval(`, `exec(`, `os.system(`, `subprocess.call(shell=True)`)
- Open redirects (`redirect(request.GET`, `redirect(request.args`)

### Example Input → Output

**Input:** Python code with `f"SELECT * FROM users WHERE username = '{username}'"` and `random.randint()` token

**Pipeline:** coordinator → security-reviewer (scan + log findings) → quality-reviewer (measure + log findings) → coordinator (get_findings → final report)

**Output:**
```
## PR Review Summary
- **Verdict:** BLOCK
- **Critical issues:** 2
- **Total findings:** 5

## Findings (by severity)
[CRITICAL] Security
  Issue: SQL injection via f-string query in get_user()
  Fix:   Use parameterised queries — conn.execute("SELECT ... WHERE username = ?", (username,))

[CRITICAL] Security
  Issue: Plaintext password storage in reset_password()
  Fix:   Hash passwords with bcrypt before storage

[HIGH] Security
  Issue: Insecure random token in generate_token()
  Fix:   Use secrets.token_hex(16) instead of random.randint()

## Recommendation
Block this PR. Address all critical and high findings before re-review.
```

### Language Override

```python
await run_review(tenant_id, javascript_code, language_override="JavaScript")
```

---

## Use Case 5 — Sales Pipeline

**File:** `product/examples/sales_pipeline.py`

An inbound lead is routed through qualification (BANT scoring), personalised outreach drafting,
and objection-handling preparation. The pipeline produces a ready-to-send email and a CRM battle
card. Leads below the score threshold are flagged for nurture and not handed off further.

### Agents

| Slug | Role | Model tier |
|------|------|-----------|
| `sales-coordinator` | Receives the lead and routes to the qualifier | Fast |
| `lead-qualifier` | Enriches company data, scores BANT, qualifies or rejects | Fast |
| `outreach-writer` | Reads CRM, writes personalised first-touch email | Standard |
| `objection-handler` | Prepares battle card with tailored objection responses | Standard |

### Tools

| Tool | What it does |
|------|-------------|
| `enrich_company` | Returns firmographic data: employees, revenue, tech stack, recent news |
| `score_lead` | Scores 0–100 via BANT (budget, authority, need, timeline) |
| `save_crm_field` | Saves any field to the lead's CRM record |
| `get_crm_record` | Retrieves the full CRM record |
| `get_objection_playbook` | Returns handling strategy for price / timing / competitor / trust / features |

### Lead Scoring Logic

| Criterion | Points |
|-----------|--------|
| Budget confirmed | +25 |
| Timeline ≤ 1 month | +25, decrement 3/month |
| Pain point match (1–5) | ×8 |
| Senior title (VP, Director, C-level) | +20 |
| Default authority | +10 |

Score ≥ 70 = HOT · Score 40–69 = WARM · Score < 40 = COLD

### Example Input → Output

**Lead:** Sarah Chen, VP of Operations, Acme Corp — confirmed Q3 budget, SAP + Salesforce data silos

**Pipeline:** coordinator → qualifier (enrich, score: 81/100 HOT) → outreach-writer (drafts personalised email) → objection-handler (produces battle card)

**Output:**
```
## Lead Battle Card
**Company:** Acme Corp
**Score:** 81/100 (HOT)
**Pain Summary:** Acme Corp struggles with disconnected SAP and Salesforce data,
preventing unified operational reporting.

## Outreach Email
Subject: Acme's digital transformation + BI

Hi Sarah,

Saw that Acme Corp is in the middle of a digital transformation push — congrats on
that. We work with a lot of operations leaders who hit the same wall: SAP and Salesforce
each tell half the story. Nexus BI stitches them together so you get one live view.

One customer in manufacturing cut their monthly close from 5 days to 6 hours.

Worth a 15-minute call this week to see if the same is possible at Acme?

[Rep name]

## Objection Preparation
**PRICE:** Acknowledge the investment...
**TIMING:** Validate the timing challenge...
```

### Qualification Threshold Override

Set a custom score threshold per run:

```python
await process_lead(tenant_id, lead, overrides={"min_score": "65"})
```

---

## Architecture Summary

All five use cases share the same runtime:

```
┌─────────────────────────────────────┐
│  REST API (FastAPI)                 │
│  POST /v1/agents/{slug}/run         │
│  POST /v1/agents/{slug}/run/stream  │
└────────────────┬────────────────────┘
                 │
         build_agent(defn)
                 │
        ┌────────▼────────┐
        │  Agent (SDK)    │  ← instructions with {template_vars}
        │  tools: [...]   │  ← resolved from global registry
        │  handoffs: [...] │  ← lazy-loaded at call time
        └────────┬────────┘
                 │
         Runner.run() / Runner.run_streamed()
                 │
        SQLiteSession (conversation memory)
```

**Adding a new use case:**

1. Define tools with `@register_tool @function_tool`.
2. Define agents as `AgentDefCreate` objects with slug references.
3. Call `create_agent_def(tenant_id, defn)` to persist them.
4. Run via the starting agent's slug — the pipeline handles itself.
