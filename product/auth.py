"""FastAPI authentication dependencies."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, status

from .config import settings
from .registry import get_tenant_by_key


async def require_tenant(
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    """Resolve the tenant from a Bearer API key. Raises 401 on failure."""
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header. Expected: Bearer <api_key>",
        )
    api_key = authorization.removeprefix("Bearer ").strip()
    tenant = await get_tenant_by_key(api_key)
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API key.",
        )
    return tenant


async def require_admin(
    x_admin_key: Annotated[str | None, Header()] = None,
) -> None:
    """Guard admin-only endpoints with the ADMIN_KEY env var."""
    if x_admin_key != settings.admin_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing X-Admin-Key header.",
        )


TenantDep = Annotated[dict[str, Any], Depends(require_tenant)]
AdminDep = Annotated[None, Depends(require_admin)]
