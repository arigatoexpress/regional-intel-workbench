"""Admin auth + helpers for the dedicated admin frontend.

The admin surface is gated by an ``X-Admin-Token`` header that must match the
``ADMIN_TOKEN`` env var. This is a stub designed to be replaced by WebAuthn
before any wider rollout.

If ``ADMIN_TOKEN`` is unset (typical in dev / tests), the gate is
permissive — the page renders, the API endpoints return 200. If
``ADMIN_TOKEN`` is set in the environment the header MUST match for any
``/admin*`` route.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import Header, HTTPException


ADMIN_TOKEN_HEADER = "x-admin-token"


def get_configured_admin_token() -> Optional[str]:
    """Return the admin token configured via env var, if any.

    Reading on every call (not at module import) lets tests rebind
    the env var with ``unittest.mock.patch.dict(os.environ, ...)`` and
    have the next request reflect the change without reloading the app.
    """

    token = os.environ.get("ADMIN_TOKEN")
    if token is None:
        return None
    token = token.strip()
    return token or None


def require_admin(
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
) -> None:
    """FastAPI dependency that enforces the admin token gate.

    When ``ADMIN_TOKEN`` is unset the gate is open (dev mode). When set, the
    request header must match exactly. We use a constant-time-ish compare to
    deter timing oracles even though this is a placeholder before WebAuthn.
    """

    expected = get_configured_admin_token()
    if expected is None:
        return  # dev mode: gate is open
    received = (x_admin_token or "").strip()
    if not _constant_time_eq(received, expected):
        raise HTTPException(
            status_code=401,
            detail="admin token required (X-Admin-Token header)",
        )


def _constant_time_eq(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    result = 0
    for ca, cb in zip(a, b):
        result |= ord(ca) ^ ord(cb)
    return result == 0
