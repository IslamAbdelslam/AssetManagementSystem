"""Tests: auth register, login, refresh, RBAC, org isolation."""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_register_success(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "org": {"name": "Acme Corp", "slug": f"acme-{uuid.uuid4().hex[:6]}"},
        "email": f"user-{uuid.uuid4().hex[:8]}@acme.com",
        "password": "SecurePass123!",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


async def test_register_duplicate_slug(client: AsyncClient):
    slug = f"dupslug-{uuid.uuid4().hex[:6]}"

    def payload(email):
        return {
            "org": {"name": "Dup Org", "slug": slug},
            "email": email,
            "password": "SecurePass123!",
        }
    await client.post("/api/v1/auth/register", json=payload("first@test.com"))
    resp = await client.post("/api/v1/auth/register", json=payload("second@test.com"))
    assert resp.status_code == 409


async def test_login_success(client: AsyncClient):
    email = f"login-{uuid.uuid4().hex[:8]}@test.com"
    await client.post("/api/v1/auth/register", json={
        "org": {"name": "Login Test", "slug": f"logintest-{uuid.uuid4().hex[:6]}"},
        "email": email, "password": "SecurePass123!",
    })
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "SecurePass123!"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


async def test_login_wrong_password(client: AsyncClient):
    resp = await client.post("/api/v1/auth/login", json={
        "email": "nobody@test.com", "password": "wrongpass"
    })
    assert resp.status_code == 401
    # Must not reveal whether user exists
    assert "credentials" in resp.json()["detail"]["message"].lower()


async def test_me_endpoint(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    assert "email" in resp.json()
    assert "role" in resp.json()


async def test_protected_without_token(client: AsyncClient):
    resp = await client.post("/api/v1/assets", json={
        "type": "domain", "value": "test.com", "source": "scan"
    })
    assert resp.status_code == 401


async def test_cross_org_isolation(client: AsyncClient):
    """Assets created by org A must not be visible to org B."""
    # Register org A
    resp_a = await client.post("/api/v1/auth/register", json={
        "org": {"name": "Org A", "slug": f"orga-{uuid.uuid4().hex[:6]}"},
        "email": f"a-{uuid.uuid4().hex[:8]}@test.com",
        "password": "SecurePass123!",
    })
    token_a = resp_a.json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # Register org B
    resp_b = await client.post("/api/v1/auth/register", json={
        "org": {"name": "Org B", "slug": f"orgb-{uuid.uuid4().hex[:6]}"},
        "email": f"b-{uuid.uuid4().hex[:8]}@test.com",
        "password": "SecurePass123!",
    })
    token_b = resp_b.json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Create asset for org A
    await client.post("/api/v1/assets", json={
        "type": "domain", "value": "secret-orga.com", "source": "scan"
    }, headers=headers_a)

    # Org B should see zero assets
    resp = await client.get("/api/v1/assets?value_contains=secret-orga", headers=headers_b)
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


async def test_refresh_token_success(client: AsyncClient):
    # Register and get initial tokens
    resp = await client.post("/api/v1/auth/register", json={
        "org": {"name": "Refresh Test", "slug": f"refresh-{uuid.uuid4().hex[:6]}"},
        "email": f"refresh-{uuid.uuid4().hex[:8]}@test.com",
        "password": "SecurePass123!",
    })
    data = resp.json()
    refresh_token = data["refresh_token"]

    # Refresh
    refresh_resp = await client.post("/api/v1/auth/refresh", json={
        "refresh_token": refresh_token
    })
    assert refresh_resp.status_code == 200
    refresh_data = refresh_resp.json()
    assert "access_token" in refresh_data
    assert "refresh_token" in refresh_data
    assert refresh_data["refresh_token"] != refresh_token


async def test_refresh_token_invalid(client: AsyncClient):
    refresh_resp = await client.post("/api/v1/auth/refresh", json={
        "refresh_token": "invalid_or_expired_token"
    })
    assert refresh_resp.status_code == 401
