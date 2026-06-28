"""
Shared pytest fixtures: async DB (PostgreSQL via Docker), test client, auth helpers.
Connects to the Docker Compose services for real PostgreSQL and Redis testing.
"""
from __future__ import annotations

import base64
import os
import uuid
from typing import AsyncGenerator

import pytest_asyncio
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


# ── Generate test RSA keys ─────────────────────────────────────────────────────
def _gen_rsa_pair():
    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )
    priv_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    pub_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return priv_pem, pub_pem


_PRIV_PEM, _PUB_PEM = _gen_rsa_pair()

# ── Connection details: prefer env vars already set (e.g. by CI), ─────────────
# ── fall back to local Docker Compose defaults.                    ─────────────
TEST_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://darkatlas:darkatlas_dev_only@localhost:5433/darkatlas_test",
)
TEST_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/15")

# ── Env setup BEFORE any import of app ────────────────────────────────────────
# Only set vars that aren't already provided (CI workflow sets DATABASE_URL etc.)
os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL)
os.environ.setdefault("REDIS_URL", TEST_REDIS_URL)
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/14")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/13")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ["JWT_PRIVATE_KEY_B64"] = base64.b64encode(_PRIV_PEM).decode()
os.environ["JWT_PUBLIC_KEY_B64"] = base64.b64encode(_PUB_PEM).decode()
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SEED_ON_STARTUP", "false")

# Clear cached settings so our env vars take effect
from app.config import get_settings  # noqa: E402
get_settings.cache_clear()

# Disable rate limiter for tests
from app.core.rate_limit import limiter  # noqa: E402
limiter.enabled = False


# ── Shared engine ─────────────────────────────────────────────
from sqlalchemy import NullPool  # noqa: E402

_test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
    poolclass=NullPool,
)
_test_session_factory = async_sessionmaker(
    _test_engine, expire_on_commit=False, class_=AsyncSession
)

# Monkeypatch global database objects to use test pool
import app.database  # noqa: E402
app.database._engine = _test_engine
app.database._session_factory = _test_session_factory
app.database.get_engine = lambda: _test_engine
app.database.get_session_factory = lambda: _test_session_factory


# ── Mock Redis for tests ──────────────────────────────────────────────────────
class FakeRedis:
    """In-memory Redis mock — avoids needing real Redis for unit tests."""

    def __init__(self):
        self._store: dict[str, str] = {}
        self._hashes: dict[str, dict[str, str]] = {}

    async def ping(self):
        return True

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, **kwargs):
        self._store[key] = value

    async def setex(self, key: str, ttl: int, value: str):
        self._store[key] = value

    async def delete(self, *keys: str):
        for key in keys:
            self._store.pop(key, None)

    async def hset(self, key: str, mapping: dict | None = None, **kwargs):
        if key not in self._hashes:
            self._hashes[key] = {}
        if mapping:
            self._hashes[key].update({str(k): str(v) for k, v in mapping.items()})

    async def hgetall(self, key: str) -> dict:
        return self._hashes.get(key, {})

    async def expire(self, key: str, ttl: int):
        pass

    async def aclose(self):
        pass


_fake_redis = FakeRedis()


@pytest_asyncio.fixture(scope="session")
async def setup_db():
    """Create all tables in the test DB at session start, drop at end."""
    from app.database import Base
    import app.auth.models  # noqa: F401
    import app.assets.models  # noqa: F401

    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _test_engine.dispose()


@pytest_asyncio.fixture
async def db_session(setup_db) -> AsyncGenerator[AsyncSession, None]:
    async with _test_session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(setup_db) -> AsyncGenerator[AsyncClient, None]:
    from app.main import create_app
    from app.database import get_db, get_redis

    app = create_app()

    async def override_get_db():
        async with _test_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    def override_get_redis():
        return _fake_redis

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_redis] = override_get_redis

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def org_and_token(client: AsyncClient) -> dict:
    """Register an org + admin, return access token and org info."""
    resp = await client.post("/api/v1/auth/register", json={
        "org": {"name": "Test Corp", "slug": f"testcorp-{uuid.uuid4().hex[:6]}"},
        "email": f"admin-{uuid.uuid4().hex[:6]}@test.com",
        "password": "SecurePass123!",
    })
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return {"access_token": data["access_token"], "token_type": "bearer"}


@pytest_asyncio.fixture
def auth_headers(org_and_token: dict) -> dict:
    return {"Authorization": f"Bearer {org_and_token['access_token']}"}
