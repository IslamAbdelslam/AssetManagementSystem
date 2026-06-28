"""
Assets router — all /assets/* endpoints and /jobs/{job_id}.
Rate limiting applied to write and bulk endpoints.
"""
from __future__ import annotations

import json
import uuid
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets import schemas
from app.assets.repository import AssetRepository
from app.assets.service import AssetService
from app.auth.models import User
from app.auth.service import get_current_user, require_role
from app.core.exceptions import NotFoundError
from app.core.pagination import PageParams, PagedResponse
from app.core.rate_limit import limiter, RATE_WRITE, RATE_BULK
from app.database import get_db, get_redis
from app.jobs.tasks import bulk_import_task, _progress_key

router = APIRouter()


def _svc(db: AsyncSession, user: User) -> AssetService:
    return AssetService(db, user.org_id)


# ── List ───────────────────────────────────────────────────────────────────────
@router.get("/assets", response_model=PagedResponse[schemas.AssetResponse], summary="List assets")
async def list_assets(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    type: str | None = Query(None),
    status: str | None = Query(None),
    tag: list[str] = Query(default=[]),
    value_contains: str | None = Query(None, max_length=200),
    source: str | None = Query(None),
    sort: str = Query("last_seen", pattern=r"^(last_seen|first_seen|value|type|status)$"),
    order: str = Query("desc", pattern=r"^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PagedResponse[schemas.AssetResponse]:
    params = PageParams(page=page, page_size=page_size)
    filters = {
        "type": type, "status": status, "tags": tag,
        "value_contains": value_contains, "source": source,
        "sort": sort, "order": order,
    }
    assets, total = await _svc(db, current_user).list_assets(filters, params)
    return PagedResponse.create(
        [schemas.AssetResponse.model_validate(a) for a in assets], total, params
    )


# ── Stats ──────────────────────────────────────────────────────────────────────
@router.get("/assets/stats", response_model=schemas.AssetStatsResponse, summary="Get asset statistics")
async def get_stats(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> schemas.AssetStatsResponse:
    stats = await _svc(db, current_user).get_stats()
    return schemas.AssetStatsResponse(**stats)


# ── Create ─────────────────────────────────────────────────────────────────────
@router.post(
    "/assets",
    response_model=schemas.AssetResponse,
    status_code=201,
    summary="Create asset",
    dependencies=[Depends(require_role("admin", "analyst"))],
)
@limiter.limit(RATE_WRITE)
async def create_asset(
    request: Request,
    body: schemas.AssetCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> schemas.AssetResponse:
    asset = await _svc(db, current_user).create(body)
    return schemas.AssetResponse.model_validate(asset)


# ── Get by ID ──────────────────────────────────────────────────────────────────
@router.get("/assets/{asset_id}", response_model=schemas.AssetResponse, summary="Get asset")
async def get_asset(
    asset_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> schemas.AssetResponse:
    asset = await _svc(db, current_user).get(asset_id)
    return schemas.AssetResponse.model_validate(asset)


# ── Update ─────────────────────────────────────────────────────────────────────
@router.patch(
    "/assets/{asset_id}",
    response_model=schemas.AssetResponse,
    summary="Update asset",
    dependencies=[Depends(require_role("admin", "analyst"))],
)
@limiter.limit(RATE_WRITE)
async def update_asset(
    request: Request,
    asset_id: uuid.UUID,
    body: schemas.AssetUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> schemas.AssetResponse:
    asset = await _svc(db, current_user).update(asset_id, body)
    return schemas.AssetResponse.model_validate(asset)


# ── Delete (soft) ──────────────────────────────────────────────────────────────
@router.delete(
    "/assets/{asset_id}",
    status_code=204,
    summary="Archive asset",
    dependencies=[Depends(require_role("admin"))],
)
@limiter.limit(RATE_WRITE)
async def delete_asset(
    request: Request,
    asset_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await _svc(db, current_user).delete(asset_id)


# ── Bulk Import ────────────────────────────────────────────────────────────────
@router.post(
    "/assets/bulk-import",
    response_model=schemas.BulkImportResponse,
    status_code=202,
    summary="Bulk import assets (async job)",
    dependencies=[Depends(require_role("admin", "analyst"))],
)
@limiter.limit(RATE_BULK)
async def bulk_import(
    request: Request,
    body: schemas.BulkImportRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> schemas.BulkImportResponse:
    repo = AssetRepository(db, current_user.org_id)
    job = await repo.create_job(len(body.records))

    records_raw = [r.model_dump() for r in body.records]
    bulk_import_task.delay(str(current_user.org_id), str(job.id), records_raw)

    return schemas.BulkImportResponse(
        job_id=job.id,
        status="queued",
        total=len(body.records),
        message=f"Import job queued. Poll GET /api/v1/jobs/{job.id} for status.",
    )


# ── Job Status ─────────────────────────────────────────────────────────────────
@router.get("/jobs/{job_id}", response_model=schemas.JobStatusResponse, summary="Import job status")
async def job_status(
    job_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
) -> schemas.JobStatusResponse:
    # Try Redis first (live progress)
    progress = await redis.hgetall(_progress_key(str(job_id)))
    if progress:
        return schemas.JobStatusResponse(
            job_id=job_id,
            status=progress.get("status", "queued"),
            total=int(progress.get("total", 0)),
            imported=int(progress.get("imported", 0)),
            error_count=int(progress.get("error_count", 0)),
            errors=json.loads(progress.get("errors", "[]")),
            progress_pct=float(progress.get("progress_pct", 0)),
        )

    # Fallback to DB
    repo = AssetRepository(db, current_user.org_id)
    job = await repo.get_job(job_id)
    if not job:
        raise NotFoundError("Job", str(job_id))

    progress_pct = (job.imported / job.total * 100) if job.total else 0
    return schemas.JobStatusResponse(
        job_id=job.id,
        status=job.status,
        total=job.total,
        imported=job.imported,
        error_count=job.error_count,
        errors=job.errors or [],
        progress_pct=round(progress_pct, 1),
    )


# ── Mark Stale ─────────────────────────────────────────────────────────────────
@router.post(
    "/assets/mark-stale",
    summary="Manually mark stale assets",
    dependencies=[Depends(require_role("admin"))],
)
@limiter.limit(RATE_WRITE)
async def mark_stale(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    threshold_days: int = Query(default=30, ge=1, le=365),
) -> dict:
    count = await _svc(db, current_user).mark_stale(threshold_days)
    return {"marked_stale": count, "threshold_days": threshold_days}


# ── Relationships ──────────────────────────────────────────────────────────────
@router.post(
    "/assets/{asset_id}/relationships",
    response_model=schemas.RelationshipResponse,
    status_code=201,
    summary="Create relationship",
    dependencies=[Depends(require_role("admin", "analyst"))],
)
@limiter.limit(RATE_WRITE)
async def create_relationship(
    request: Request,
    asset_id: uuid.UUID,
    body: schemas.RelationshipCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> schemas.RelationshipResponse:
    repo = AssetRepository(db, current_user.org_id)
    # Verify both assets belong to this org
    src = await repo.get_by_id(asset_id)
    tgt = await repo.get_by_id(body.target_id)
    if not src:
        raise NotFoundError("Asset", str(asset_id))
    if not tgt:
        raise NotFoundError("Asset", str(body.target_id))
    rel = await repo.create_relationship(asset_id, body.target_id, body.rel_type)
    return schemas.RelationshipResponse.model_validate(rel)


@router.get(
    "/assets/{asset_id}/relationships",
    response_model=list[schemas.RelationshipResponse],
    summary="List relationships",
)
async def list_relationships(
    asset_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[schemas.RelationshipResponse]:
    repo = AssetRepository(db, current_user.org_id)
    rels = await repo.get_relationships(asset_id)
    return [schemas.RelationshipResponse.model_validate(r) for r in rels]


@router.delete(
    "/relationships/{rel_id}",
    status_code=204,
    summary="Delete relationship",
    dependencies=[Depends(require_role("admin"))],
)
@limiter.limit(RATE_WRITE)
async def delete_relationship(
    request: Request,
    rel_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    repo = AssetRepository(db, current_user.org_id)
    deleted = await repo.delete_relationship(rel_id)
    if not deleted:
        raise NotFoundError("Relationship", str(rel_id))
