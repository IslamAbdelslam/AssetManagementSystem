"""AI router: POST /ai/query, POST /ai/summarize"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import chains, schemas
from app.assets.repository import AssetRepository
from app.auth.models import User
from app.auth.service import get_current_user
from app.core.pagination import PageParams
from app.database import get_db

router = APIRouter()


def _serialize_asset(a: Any) -> dict:
    """Convert ORM Asset to JSON-safe dict (handles UUID, datetime)."""
    return {
        "id": str(a.id),
        "type": a.type,
        "value": a.value,
        "status": a.status,
        "source": a.source,
        "tags": a.tags,
        "metadata": a.metadata_,
        "first_seen": a.first_seen.isoformat(),
        "last_seen": a.last_seen.isoformat(),
    }


@router.post("/query", response_model=schemas.NLQueryResponse, summary="Natural language asset query")
async def nl_query(
    body: schemas.NLQueryRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> schemas.NLQueryResponse:
    """
    Translate plain English into a structured asset query.
    Results are grounded in real DB data — the LLM never invents assets.
    """
    # Step 1: LLM translates NL → validated filter
    asset_filter = await chains.run_nl_query_chain(body.query)

    # Step 2: Build filters dict from validated Pydantic model
    filters: dict[str, Any] = {
        "type": asset_filter.type,
        "status": asset_filter.status,
        "tags": asset_filter.tags,
        "value_contains": asset_filter.value_contains,
        "source": asset_filter.source,
        "sort": "last_seen",
        "order": "desc",
    }

    # Step 3: Execute real DB query — only real assets returned
    repo = AssetRepository(db, current_user.org_id)
    params = PageParams(page=1, page_size=100)
    assets, total = await repo.list_assets(filters, params)

    # Step 4: Post-filter for metadata conditions (e.g. expired certs)
    results = [_serialize_asset(a) for a in assets]
    if asset_filter.metadata_filter.get("expires") == "past":
        today = date.today().isoformat()
        results = [
            r for r in results
            if r.get("metadata", {}).get("expires", "9999-99-99") < today
        ]

    return schemas.NLQueryResponse(
        query=body.query,
        interpretation=asset_filter.explanation,
        filter_applied=filters,
        total_results=len(results),
        results=results,
    )


@router.post("/summarize", response_model=schemas.SummarizeResponse, summary="AI asset landscape summary")
async def summarize(
    body: schemas.SummarizeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> schemas.SummarizeResponse:
    """
    Generate a security-focused summary of the org's asset landscape.
    Data is fetched from DB first — LLM only summarizes, cannot invent.
    """
    repo = AssetRepository(db, current_user.org_id)
    params = PageParams(page=1, page_size=200)
    assets, _ = await repo.list_assets({}, params)

    # Compute counts for response
    counts: dict[str, int] = {}
    for a in assets:
        counts[a.type] = counts.get(a.type, 0) + 1

    # Provide grounded data to LLM
    asset_json = json.dumps([_serialize_asset(a) for a in assets[:100]], indent=2)
    summary_text = await chains.run_summarize_chain(asset_json, body.focus)

    return schemas.SummarizeResponse(
        focus=body.focus,
        summary=summary_text,
        asset_counts=counts,
    )
