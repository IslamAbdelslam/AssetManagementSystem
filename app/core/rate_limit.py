"""
Rate limiting via slowapi (Redis-backed).
Provides a shared limiter instance and common rate-limit strings.
"""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings

settings = get_settings()

# Use client IP for rate-limit key; overridable per-route
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200/minute"],
    storage_uri=settings.REDIS_URL,
)

# ── Rate-limit presets ─────────────────────────────────────────────────────────
RATE_WRITE = "30/minute"
RATE_BULK = "500/minute"
RATE_AUTH = "10/minute"
RATE_AI = "10/minute"
