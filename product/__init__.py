"""Multi-agent product framework built on the OpenAI Agents SDK.

Quick start:
    uv run uvicorn product.api:app --reload

Environment variables:
    PRODUCT_DB_PATH   Path to SQLite database file (default: product.db)
    DEFAULT_MODEL     Default model for agents (default: gpt-4o)
    MAX_TURNS_DEFAULT Max turns per run (default: 10)
    ADMIN_KEY         Secret key for tenant provisioning (default: changeme)
    HOST              API host (default: 0.0.0.0)
    PORT              API port (default: 8000)
"""
