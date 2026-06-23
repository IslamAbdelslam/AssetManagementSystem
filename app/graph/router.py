"""Graph router: BFS endpoint + D3 visualization data + static page."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.schemas import GraphResponse
from app.auth.models import User
from app.auth.service import get_current_user
from app.database import get_db
from app.graph.service import GraphService

router = APIRouter()


@router.get("/assets/{asset_id}/graph", response_model=GraphResponse, summary="Asset relationship graph")
async def get_asset_graph(
    asset_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    depth: int = Query(2, ge=1, le=5, description="BFS traversal depth"),
) -> GraphResponse:
    svc = GraphService(db, current_user.org_id)
    return await svc.get_graph(asset_id, depth)


@router.get("/graph/data", response_model=GraphResponse, summary="Full org graph data (for D3)")
async def get_full_graph_data(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GraphResponse:
    svc = GraphService(db, current_user.org_id)
    return await svc.get_all_graph_data()


@router.get("/graph", response_class=HTMLResponse, include_in_schema=False)
async def graph_visualization() -> HTMLResponse:
    """Serve D3.js graph visualization page."""
    from pathlib import Path
    html = Path("app/static/graph.html").read_text()
    return HTMLResponse(content=html)
