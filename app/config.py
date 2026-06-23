"""
Application settings — loaded once at startup from environment variables.
All secrets come from env; no defaults for sensitive values.
"""
from __future__ import annotations

import base64
from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ────────────────────────────────────────────────────────
    APP_ENV: Literal["development", "production"] = "development"
    APP_DEBUG: bool = False
    DOCS_ENABLED: bool = True
    SEED_ON_STARTUP: bool = False

    # ── Database ───────────────────────────────────────────────────────────
    DATABASE_URL: str
    META_DATABASE_URL: str = ""  # Only needed for TENANT_ISOLATION=database

    # ── Multi-Tenancy ──────────────────────────────────────────────────────
    TENANT_ISOLATION: Literal["row", "database"] = "row"

    # ── Auth ───────────────────────────────────────────────────────────────
    JWT_PRIVATE_KEY_B64: str
    JWT_PUBLIC_KEY_B64: str
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── Redis ──────────────────────────────────────────────────────────────
    REDIS_URL: str

    # ── Celery ─────────────────────────────────────────────────────────────
    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str

    # ── AI ─────────────────────────────────────────────────────────────────
    GEMINI_API_KEY: str
    GEMINI_MODEL: str = "gemini-2.0-flash"

    # ── Lifecycle ──────────────────────────────────────────────────────────
    STALE_THRESHOLD_DAYS: int = 30

    # ── CORS ───────────────────────────────────────────────────────────────
    CORS_ORIGINS: str = "http://localhost:3000"

    # ── Derived properties ─────────────────────────────────────────────────
    @property
    def jwt_private_key(self) -> str:
        return base64.b64decode(self.JWT_PRIVATE_KEY_B64).decode()

    @property
    def jwt_public_key(self) -> str:
        return base64.b64decode(self.JWT_PUBLIC_KEY_B64).decode()

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]

    @field_validator("TENANT_ISOLATION")
    @classmethod
    def validate_tenant_mode(cls, v: str) -> str:
        if v not in ("row", "database"):
            raise ValueError("TENANT_ISOLATION must be 'row' or 'database'")
        return v

    @model_validator(mode="after")
    def validate_database_mode_deps(self) -> "Settings":
        if self.TENANT_ISOLATION == "database" and not self.META_DATABASE_URL:
            raise ValueError(
                "META_DATABASE_URL is required when TENANT_ISOLATION=database"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
