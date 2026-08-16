"""
Minimal shared-secret gate for mutating routes, until Clerk lands in P3
(CLAUDE.md P3: multi-user foundation). AUDIT.md §1 flagged POST /scrape,
POST /scrape/bulk, and POST /jobs as unauthenticated mutating endpoints —
this is the "some gate, not a full auth system" fix that section asks for.

Fails closed: if ADMIN_API_KEY isn't set, every gated route 503s rather
than silently staying open. Set a real value in Railway to protect prod;
local dev has a clearly-fake default in .env.
"""

import os
import secrets

from fastapi import Header, HTTPException, status


def require_admin_key(x_admin_key: str | None = Header(default=None)) -> None:
    configured = os.getenv("ADMIN_API_KEY")
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin auth is not configured (ADMIN_API_KEY unset) — this route is disabled until it is.",
        )
    if not x_admin_key or not secrets.compare_digest(x_admin_key, configured):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-Admin-Key header.",
        )
