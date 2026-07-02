"""Tests: AI NL query and summarize with mocked Gemini LLM."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

MOCK_FILTER = {
    "type": "certificate",
    "status": None,
    "tags": ["prod"],
    "value_contains": None,
    "source": None,
    "metadata_filter": {"expires": "past"},
    "explanation": "Filtering certificates tagged prod with past expiry",
}


async def test_nl_query_returns_db_data(client: AsyncClient, auth_headers: dict):
    """NL query must return real DB records, not LLM-invented data."""
    # Create a real asset
    await client.post("/api/v1/assets", json={
        "type": "certificate",
        "value": "cn=test-expired.com",
        "source": "scan",
        "tags": ["prod"],
        "metadata_": {"issuer": "Let's Encrypt", "expires": "2024-01-01"},
    }, headers=auth_headers)

    with patch("app.ai.chains.run_nl_query_chain", new_callable=AsyncMock) as mock_chain:
        from app.ai.schemas import AssetFilterSchema
        mock_chain.return_value = AssetFilterSchema(**MOCK_FILTER)

        resp = await client.post("/api/v1/ai/query", json={
            "query": "show me all expired certificates on production subdomains"
        }, headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert "query" in data
    assert "results" in data
    assert "interpretation" in data
    # All results must come from DB (no hallucinated assets)
    for item in data["results"]:
        assert "id" in item
        assert "value" in item
        assert "type" in item


async def test_nl_query_unauthenticated(client: AsyncClient):
    resp = await client.post("/api/v1/ai/query", json={"query": "show all assets"})
    assert resp.status_code == 401


async def test_nl_query_llm_parse_failure(client: AsyncClient, auth_headers: dict):
    """LLM returning unparseable output must yield 422, not 500."""
    with patch("app.ai.chains.run_nl_query_chain", new_callable=AsyncMock) as mock_chain:
        from app.core.exceptions import ValidationError as AppValidationError
        mock_chain.side_effect = AppValidationError("Could not parse your query.")

        resp = await client.post("/api/v1/ai/query", json={"query": "gibberish????"}, headers=auth_headers)

    assert resp.status_code == 422


async def test_nl_query_empty_input(client: AsyncClient, auth_headers: dict):
    resp = await client.post("/api/v1/ai/query", json={"query": "ab"}, headers=auth_headers)
    assert resp.status_code == 422  # min_length=3


async def test_summarize_endpoint(client: AsyncClient, auth_headers: dict):
    """Summarize must call LLM with real data, return structured response."""
    with patch("app.ai.chains.run_summarize_chain", new_callable=AsyncMock) as mock_sum:
        mock_sum.return_value = "The organization has 5 active domains and 2 expired certificates. Recommend renewing certificates immediately."

        resp = await client.post("/api/v1/ai/summarize", json={"focus": "certificates"}, headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert "summary" in data
    assert "asset_counts" in data
    assert len(data["summary"]) > 10  # not empty


async def test_nl_query_too_long(client: AsyncClient, auth_headers: dict):
    resp = await client.post("/api/v1/ai/query", json={"query": "x" * 501}, headers=auth_headers)
    assert resp.status_code == 422  # max_length=500


async def test_nl_query_expired_certs(client: AsyncClient, auth_headers: dict):
    """metadata_filter expires=past should only return certs with past expiry dates."""
    from datetime import date
    # Create an expired cert
    await client.post("/api/v1/assets", json={
        "type": "certificate",
        "value": "cn=expired.example.com",
        "source": "scan",
        "tags": ["prod"],
        "metadata_": {"issuer": "Let's Encrypt", "expires": "2020-01-01"},
    }, headers=auth_headers)

    with patch("app.ai.chains.run_nl_query_chain", new_callable=AsyncMock) as mock_chain:
        from app.ai.schemas import AssetFilterSchema
        mock_chain.return_value = AssetFilterSchema(
            type="certificate",
            tags=["prod"],
            metadata_filter={"expires": "past"},
            explanation="Filtering expired production certificates",
        )
        resp = await client.post("/api/v1/ai/query", json={
            "query": "show me all expired certificates on production subdomains"
        }, headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    # All returned certs must have a past expiry date
    today = date.today().isoformat()
    for item in data["results"]:
        assert item["metadata"].get("expires", "9999") < today
