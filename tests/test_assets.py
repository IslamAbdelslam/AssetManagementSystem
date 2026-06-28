"""Tests: asset CRUD, deduplication, filtering, lifecycle, pagination."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

DOMAIN = {"type": "domain", "value": "example.com", "source": "scan", "tags": ["root"]}


async def test_create_asset(client: AsyncClient, auth_headers: dict):
    resp = await client.post("/api/v1/assets", json=DOMAIN, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["value"] == "example.com"
    assert data["type"] == "domain"
    assert "id" in data
    assert "first_seen" in data
    assert "last_seen" in data


async def test_get_asset(client: AsyncClient, auth_headers: dict):
    create = await client.post("/api/v1/assets", json=DOMAIN, headers=auth_headers)
    asset_id = create.json()["id"]
    resp = await client.get(f"/api/v1/assets/{asset_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == asset_id


async def test_get_nonexistent_asset(client: AsyncClient, auth_headers: dict):
    import uuid
    resp = await client.get(f"/api/v1/assets/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "not_found"


async def test_update_asset(client: AsyncClient, auth_headers: dict):
    create = await client.post("/api/v1/assets", json=DOMAIN, headers=auth_headers)
    asset_id = create.json()["id"]
    resp = await client.patch(
        f"/api/v1/assets/{asset_id}",
        json={"status": "stale", "tags": ["root", "monitored"]},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "stale"


async def test_delete_asset(client: AsyncClient, auth_headers: dict):
    create = await client.post("/api/v1/assets", json=DOMAIN, headers=auth_headers)
    asset_id = create.json()["id"]
    resp = await client.delete(f"/api/v1/assets/{asset_id}", headers=auth_headers)
    assert resp.status_code == 204
    # Should now be archived
    get = await client.get(f"/api/v1/assets/{asset_id}", headers=auth_headers)
    assert get.json()["status"] == "archived"


async def test_deduplication(client: AsyncClient, auth_headers: dict):
    """Importing the same asset twice must create exactly one record."""
    payload = {"type": "domain", "value": "dedup-test.com", "source": "scan", "tags": ["a"]}
    r1 = await client.post("/api/v1/assets", json=payload, headers=auth_headers)
    r2 = await client.post("/api/v1/assets", json={**payload, "tags": ["b"]}, headers=auth_headers)
    assert r1.status_code == 201
    assert r2.status_code == 201
    # Same ID — not duplicated
    assert r1.json()["id"] == r2.json()["id"]
    # Tags merged: both a and b
    assert set(r2.json()["tags"]) >= {"a", "b"}


async def test_value_normalized_lowercase(client: AsyncClient, auth_headers: dict):
    payload = {"type": "domain", "value": "UPPER-CASE.COM", "source": "scan"}
    resp = await client.post("/api/v1/assets", json=payload, headers=auth_headers)
    assert resp.json()["value"] == "upper-case.com"


async def test_list_filtering_by_type(client: AsyncClient, auth_headers: dict):
    await client.post("/api/v1/assets", json={"type": "domain", "value": "filter-test.com", "source": "scan"}, headers=auth_headers)
    await client.post("/api/v1/assets", json={"type": "ip_address", "value": "1.2.3.4", "source": "scan"}, headers=auth_headers)
    resp = await client.get("/api/v1/assets?type=domain", headers=auth_headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert all(i["type"] == "domain" for i in items)


async def test_list_filtering_by_tag(client: AsyncClient, auth_headers: dict):
    await client.post("/api/v1/assets", json={"type": "domain", "value": "tagged-one.com", "source": "scan", "tags": ["special-tag"]}, headers=auth_headers)
    resp = await client.get("/api/v1/assets?tag=special-tag", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1
    assert any(i["value"] == "tagged-one.com" for i in resp.json()["items"])


async def test_list_value_contains(client: AsyncClient, auth_headers: dict):
    await client.post("/api/v1/assets", json={"type": "subdomain", "value": "api.search-me.com", "source": "scan"}, headers=auth_headers)
    resp = await client.get("/api/v1/assets?value_contains=search-me", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


async def test_pagination(client: AsyncClient, auth_headers: dict):
    # Create 5 unique assets
    for i in range(5):
        await client.post("/api/v1/assets", json={"type": "domain", "value": f"page-test-{i}.com", "source": "scan"}, headers=auth_headers)
    resp = await client.get("/api/v1/assets?page=1&page_size=2", headers=auth_headers)
    data = resp.json()
    assert len(data["items"]) <= 2
    assert "pages" in data
    assert "total" in data


async def test_page_size_capped(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/v1/assets?page_size=9999", headers=auth_headers)
    assert resp.status_code == 422  # validation error


async def test_mark_stale_endpoint(client: AsyncClient, auth_headers: dict):
    resp = await client.post("/api/v1/assets/mark-stale?threshold_days=1", headers=auth_headers)
    assert resp.status_code == 200
    assert "marked_stale" in resp.json()


async def test_metadata_size_limit(client: AsyncClient, auth_headers: dict):
    big_metadata = {"key": "x" * (65 * 1024)}
    resp = await client.post("/api/v1/assets", json={
        "type": "domain", "value": "big-meta.com", "source": "scan",
        "metadata_": big_metadata,
    }, headers=auth_headers)
    assert resp.status_code == 422

async def test_get_stats(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/v1/assets/stats", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "total_assets" in data
    assert "by_type" in data
    assert "by_status" in data
