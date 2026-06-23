"""
Shared pytest fixtures: async DB, test client, auth helpers.
Uses an in-memory SQLite-compatible setup via SQLAlchemy async.
For PostgreSQL-specific features (GIN, upsert), integration tests require a real DB.
"""
from __future__ import annotations

import asyncio
import base64
import os
import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

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


# ── Env setup before any import of app ────────────────────────────────────────
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/1")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("JWT_PRIVATE_KEY_B64", base64.b64encode(_PRIV_PEM).decode())
os.environ.setdefault("JWT_PUBLIC_KEY_B64", base64.b64encode(_PUB_PEM).decode())


# ── Async engine for tests ─────────────────────────────────────────────────────
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

_test_engine = create_async_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_test_session_factory = async_sessionmaker(_test_engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture(scope="session")
async def setup_db():
    from app.database import Base
    import app.auth.models  # noqa
    import app.assets.models  # noqa
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session(setup_db) -> AsyncGenerator[AsyncSession, None]:
    async with _test_session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(setup_db) -> AsyncGenerator[AsyncClient, None]:
    from app.main import app
    from app.database import get_db

    async def override_get_db():
        async with _test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
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
