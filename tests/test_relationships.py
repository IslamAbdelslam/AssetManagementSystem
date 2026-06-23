"""Tests: relationship CRUD and graph BFS traversal."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _create_asset(client, headers, type_, value):
    resp = await client.post("/api/v1/assets", json={
        "type": type_, "value": value, "source": "scan"
    }, headers=headers)
    assert resp.status_code == 201
    return resp.json()["id"]


async def test_create_relationship(client: AsyncClient, auth_headers: dict):
    domain_id = await _create_asset(client, auth_headers, "domain", "rel-domain.com")
    subdomain_id = await _create_asset(client, auth_headers, "subdomain", "api.rel-domain.com")

    resp = await client.post(
        f"/api/v1/assets/{subdomain_id}/relationships",
        json={"target_id": domain_id, "rel_type": "subdomain_of"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["source_id"] == subdomain_id
    assert data["target_id"] == domain_id
    assert data["rel_type"] == "subdomain_of"


async def test_list_relationships(client: AsyncClient, auth_headers: dict):
    domain_id = await _create_asset(client, auth_headers, "domain", "list-rel-domain.com")
    sub_id = await _create_asset(client, auth_headers, "subdomain", "www.list-rel-domain.com")
    ip_id = await _create_asset(client, auth_headers, "ip_address", "10.0.1.1")

    await client.post(f"/api/v1/assets/{sub_id}/relationships", json={"target_id": domain_id, "rel_type": "subdomain_of"}, headers=auth_headers)
    await client.post(f"/api/v1/assets/{sub_id}/relationships", json={"target_id": ip_id, "rel_type": "resolves_to"}, headers=auth_headers)

    resp = await client.get(f"/api/v1/assets/{sub_id}/relationships", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_delete_relationship(client: AsyncClient, auth_headers: dict):
    d_id = await _create_asset(client, auth_headers, "domain", "del-rel-domain.com")
    s_id = await _create_asset(client, auth_headers, "subdomain", "x.del-rel-domain.com")

    rel = await client.post(f"/api/v1/assets/{s_id}/relationships", json={"target_id": d_id, "rel_type": "subdomain_of"}, headers=auth_headers)
    rel_id = rel.json()["id"]

    del_resp = await client.delete(f"/api/v1/relationships/{rel_id}", headers=auth_headers)
    assert del_resp.status_code == 204

    list_resp = await client.get(f"/api/v1/assets/{s_id}/relationships", headers=auth_headers)
    assert len(list_resp.json()) == 0


async def test_invalid_rel_type(client: AsyncClient, auth_headers: dict):
    d_id = await _create_asset(client, auth_headers, "domain", "invalid-rel-type.com")
    s_id = await _create_asset(client, auth_headers, "subdomain", "x.invalid-rel-type.com")
    resp = await client.post(f"/api/v1/assets/{s_id}/relationships", json={"target_id": d_id, "rel_type": "invented_type"}, headers=auth_headers)
    assert resp.status_code == 422


async def test_graph_bfs(client: AsyncClient, auth_headers: dict):
    """BFS graph should return root + 1-hop neighbors."""
    domain_id = await _create_asset(client, auth_headers, "domain", "graph-bfs.com")
    sub1 = await _create_asset(client, auth_headers, "subdomain", "a.graph-bfs.com")
    sub2 = await _create_asset(client, auth_headers, "subdomain", "b.graph-bfs.com")

    await client.post(f"/api/v1/assets/{sub1}/relationships", json={"target_id": domain_id, "rel_type": "subdomain_of"}, headers=auth_headers)
    await client.post(f"/api/v1/assets/{sub2}/relationships", json={"target_id": domain_id, "rel_type": "subdomain_of"}, headers=auth_headers)

    resp = await client.get(f"/api/v1/assets/{domain_id}/graph?depth=1", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    node_ids = [n["id"] for n in data["nodes"]]
    assert domain_id in node_ids
    assert sub1 in node_ids
    assert sub2 in node_ids
    assert len(data["edges"]) == 2


async def test_graph_cross_org_isolation(client: AsyncClient):
    """Graph BFS must not traverse into another org's assets."""
    import uuid

    slug_a = f"graph-orga-{uuid.uuid4().hex[:6]}"
    resp_a = await client.post("/api/v1/auth/register", json={
        "org": {"name": "Graph Org A", "slug": slug_a},
        "email": f"ga-{uuid.uuid4().hex[:8]}@test.com",
        "password": "SecurePass123!",
    })
    headers_a = {"Authorization": f"Bearer {resp_a.json()['access_token']}"}
    d_id = await _create_asset(client, headers_a, "domain", "graph-isolated.com")

    slug_b = f"graph-orgb-{uuid.uuid4().hex[:6]}"
    resp_b = await client.post("/api/v1/auth/register", json={
        "org": {"name": "Graph Org B", "slug": slug_b},
        "email": f"gb-{uuid.uuid4().hex[:8]}@test.com",
        "password": "SecurePass123!",
    })
    headers_b = {"Authorization": f"Bearer {resp_b.json()['access_token']}"}

    # Org B tries to fetch org A's asset graph
    resp = await client.get(f"/api/v1/assets/{d_id}/graph", headers=headers_b)
    # Either 404 (asset not found in org B) or empty graph
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        assert len(resp.json()["nodes"]) == 0
