"""
Async SQLAlchemy engine + session factory.
Supports both TENANT_ISOLATION modes: row and database.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import AsyncGenerator

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import DateTime
from datetime import datetime, timezone

from app.config import get_settings

settings = get_settings()

# ── Base ORM class ─────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


# ── Primary engine (row mode: main DB; database mode: meta DB) ─────────────────
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _make_engine(url: str) -> AsyncEngine:
    return create_async_engine(
        url,
        echo=settings.APP_DEBUG,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        db_url = (
            settings.META_DATABASE_URL
            if settings.TENANT_ISOLATION == "database"
            else settings.DATABASE_URL
        )
        _engine = _make_engine(db_url)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _session_factory


# ── Tenant Connection Manager (database isolation mode) ────────────────────────
class TenantConnectionManager:
    """LRU cache of per-org AsyncEngines for database isolation mode."""

    MAX_ENGINES = 50

    def __init__(self) -> None:
        self._engines: OrderedDict[str, AsyncEngine] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get_engine(self, org_db_url: str) -> AsyncEngine:
        async with self._lock:
            if org_db_url in self._engines:
                self._engines.move_to_end(org_db_url)
                return self._engines[org_db_url]

            if len(self._engines) >= self.MAX_ENGINES:
                _, evicted = self._engines.popitem(last=False)
                await evicted.dispose()

            engine = _make_engine(org_db_url)
            self._engines[org_db_url] = engine
            return engine

    async def dispose_all(self) -> None:
        async with self._lock:
            for engine in self._engines.values():
                await engine.dispose()
            self._engines.clear()


tenant_connection_manager = TenantConnectionManager()


# ── Session dependency ─────────────────────────────────────────────────────────
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an async DB session."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_tenant_db(org_db_url: str) -> AsyncGenerator[AsyncSession, None]:
    """Yields session for a specific tenant DB (database isolation mode)."""
    engine = await tenant_connection_manager.get_engine(org_db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── Redis client ───────────────────────────────────────────────────────────────
_redis_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def close_redis() -> None:
    global _redis_client
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None
