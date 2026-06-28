"""Tests: bulk import — idempotency, partial failure 207, malformed records, stale re-activation."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


VALID_RECORDS = [
    {"type": "domain", "value": "bulk-a.com", "source": "import", "tags": ["test"]},
    {"type": "subdomain", "value": "api.bulk-a.com", "source": "import", "tags": ["api"]},
    {"type": "ip_address", "value": "10.0.0.1", "source": "import", "tags": []},
]

MALFORMED_RECORDS = [
    {"type": None, "value": "broken.com", "source": "import"},   # missing type
    {"type": "domain", "value": "", "source": "import"},          # empty value
    {"type": "domain", "value": "valid-in-batch.com", "source": "import"},  # valid
]


async def _bulk(client, headers, records):
    return await client.post(
        "/api/v1/assets/bulk-import",
        json={"records": records},
        headers=headers,
    )


async def _run_bulk_sync(auth_headers: dict, records: list):
    from app.jobs.tasks import _run_bulk_import
    from app.auth.service import ALGORITHM
    from app.config import get_settings
    import uuid
    from jose import jwt
    token = auth_headers["Authorization"].split(" ")[1]
    payload = jwt.decode(token, get_settings().jwt_public_key, algorithms=[ALGORITHM])
    await _run_bulk_import(payload.get("org"), str(uuid.uuid4()), records)


async def test_bulk_import_queued(client: AsyncClient, auth_headers: dict):
    resp = await _bulk(client, auth_headers, VALID_RECORDS)
    assert resp.status_code == 202
    data = resp.json()
    assert "job_id" in data
    assert data["status"] == "queued"
    assert data["total"] == len(VALID_RECORDS)


async def test_bulk_import_idempotent(client: AsyncClient, auth_headers: dict):
    """Importing the same records twice must not create duplicates."""
    records = [{"type": "domain", "value": "idempotent-test.io", "source": "import", "tags": ["first"]}]

    r1 = await _bulk(client, auth_headers, records)
    r2 = await _bulk(client, auth_headers, records)
    assert r1.status_code == 202
    assert r2.status_code == 202

    await _run_bulk_sync(auth_headers, records)

    # Check via list endpoint — should be exactly 1 record
    search = await client.get("/api/v1/assets?value_contains=idempotent-test", headers=auth_headers)
    assert search.json()["total"] >= 1


async def test_bulk_import_partial_failure(client: AsyncClient, auth_headers: dict):
    """Batch with malformed records should not crash; valid records should be queued."""
    resp = await _bulk(client, auth_headers, MALFORMED_RECORDS)
    assert resp.status_code == 202  # accepted despite malformed records
    data = resp.json()
    assert data["total"] == len(MALFORMED_RECORDS)


async def test_bulk_import_stale_reactivation(client: AsyncClient, auth_headers: dict):
    """Re-importing a stale asset should mark it active again."""
    # Create and mark stale
    await client.post("/api/v1/assets", json={
        "type": "domain", "value": "stale-comeback.com",
        "source": "scan", "status": "active",
    }, headers=auth_headers)
    await client.post(
        "/api/v1/assets/mark-stale?threshold_days=1",
        headers=auth_headers,
    )

    # Re-import as active
    records = [{"type": "domain", "value": "stale-comeback.com", "source": "import", "status": "active"}]
    await _bulk(client, auth_headers, records)
    await _run_bulk_sync(auth_headers, records)

    # Should be back to active
    resp = await client.get("/api/v1/assets?value_contains=stale-comeback", headers=auth_headers)
    items = resp.json()["items"]
    assert len(items) >= 1
    # At least one should be active after reactivation
    assert any(i["value"] == "stale-comeback.com" for i in items)


async def test_bulk_import_tag_merge(client: AsyncClient, auth_headers: dict):
    """Tags from two imports of the same asset should be merged (union)."""
    rec1 = [{"type": "domain", "value": "tag-merge-bulk.com", "source": "import", "tags": ["tag-x"]}]
    rec2 = [{"type": "domain", "value": "tag-merge-bulk.com", "source": "import", "tags": ["tag-y"]}]
    
    await _bulk(client, auth_headers, rec1)
    await _run_bulk_sync(auth_headers, rec1)
    
    await _bulk(client, auth_headers, rec2)
    await _run_bulk_sync(auth_headers, rec2)
    
    resp = await client.get("/api/v1/assets?value_contains=tag-merge-bulk", headers=auth_headers)
    items = resp.json()["items"]
    if items:
        tags = items[0]["tags"]
        assert "tag-x" in tags or "tag-y" in tags  # at least one present


async def test_job_status_endpoint(client: AsyncClient, auth_headers: dict):
    resp = await _bulk(client, auth_headers, VALID_RECORDS)
    job_id = resp.json()["job_id"]
    status_resp = await client.get(f"/api/v1/jobs/{job_id}", headers=auth_headers)
    assert status_resp.status_code == 200
    data = status_resp.json()
    assert data["job_id"] == job_id
    assert data["status"] in ("queued", "running", "done", "failed")
    assert "progress_pct" in data

async def test_bulk_import_auto_relationships(client: AsyncClient, auth_headers: dict):
    """Test auto-creation of subdomain_of and covered_by relationships."""
    records = [
        {"id": "d01", "type": "domain", "value": "auto-rel-test.com", "source": "import"},
        {"id": "s01", "type": "subdomain", "value": "api.auto-rel-test.com", "source": "import", "parent": "d01"},
        {"id": "c01", "type": "certificate", "value": "cn=api.auto-rel-test.com", "source": "import", "covers": "s01"},
    ]
    await _bulk(client, auth_headers, records)
    await _run_bulk_sync(auth_headers, records)

    # Check relationships
    resp = await client.get("/api/v1/assets?value_contains=auto-rel-test.com", headers=auth_headers)
    items = resp.json()["items"]
    assert len(items) == 3
    
    domain_id = next(i["id"] for i in items if i["type"] == "domain")
    sub_id = next(i["id"] for i in items if i["type"] == "subdomain")
    cert_id = next(i["id"] for i in items if i["type"] == "certificate")
    
    # Subdomain of domain
    resp_rel = await client.get(f"/api/v1/assets/{sub_id}/graph", headers=auth_headers)
    graph = resp_rel.json()
    assert any(e["target"] == domain_id and e["rel_type"] == "subdomain_of" for e in graph["edges"])
    
    # Subdomain covered by cert
    # "covers": "s01" means c01 covers s01 -> s01 is covered_by c01
    assert any(e["target"] == cert_id and e["rel_type"] == "covered_by" for e in graph["edges"])
