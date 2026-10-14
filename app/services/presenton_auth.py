"""Presenton API key that survives Presenton restarts.

Presenton keeps its users and API keys in a database inside its own
container, so every time its Cloud Run service scales to zero and starts
again, every previously minted key stops working (401). Instead of a human
re-minting a key each time (see CLAUDE.md), the backend logs in as
Presenton's bootstrap admin (created from AUTH_USERNAME/AUTH_PASSWORD on
every boot) and mints a fresh key whenever the current one is rejected.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()
_current_key: str | None = None


def current_key() -> str:
    """The key to send right now: the last one minted here, else the configured one."""
    return _current_key or get_settings().presenton_api_key


def is_unauthorized(exc: BaseException) -> bool:
    """True if `exc` (or anything nested in it, e.g. an anyio ExceptionGroup
    from the MCP client) is an HTTP 401 from Presenton."""
    seen: set[int] = set()
    stack: list[BaseException] = [exc]
    while stack:
        e = stack.pop()
        if id(e) in seen:
            continue
        seen.add(id(e))
        if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 401:
            return True
        if "401" in str(e) and "nauthorized" in str(e):
            return True
        stack.extend(getattr(e, "exceptions", ()) or ())
        for nested in (e.__cause__, e.__context__):
            if nested is not None:
                stack.append(nested)
    return False


async def refresh_key(rejected_key: str) -> str:
    """Mint a new key unless another caller already replaced `rejected_key`."""
    global _current_key
    async with _lock:
        if current_key() != rejected_key:
            return current_key()
        settings = get_settings()
        if not settings.presenton_admin_password:
            raise RuntimeError(
                "Presenton rejected its API key and PRESENTON_ADMIN_PASSWORD isn't set, "
                "so a new key can't be minted automatically."
            )
        base = settings.presenton_url.rstrip("/")
        async with httpx.AsyncClient(timeout=60) as client:
            login = await client.post(
                f"{base}/api/v1/auth/login",
                json={"username": settings.presenton_admin_username, "password": settings.presenton_admin_password},
            )
            login.raise_for_status()
            user_id = login.json().get("id")
            minted = await client.post(
                f"{base}/api/v1/admin/api-keys",
                json={"user_id": user_id, "label": "marketing-agent-backend", "expiry_days": 365},
            )
            minted.raise_for_status()
            token = minted.json().get("token")
        if not token:
            raise RuntimeError(f"Presenton returned no token when minting a key: {minted.json()}")
        _current_key = token
        logger.info("Minted a new Presenton API key (the previous one was rejected)")
        return token
