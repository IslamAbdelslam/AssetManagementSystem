"""
Asset repository — all DB queries live here.
Service layer calls these; no SQL outside this module.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset, AssetRelationship, ImportJob
from app.core.pagination import PageParams


class AssetRepository:
    def __init__(self, db: AsyncSession, org_id: uuid.UUID) -> None:
        self.db = db
        self.org_id = org_id

    # ── CRUD ──────────────────────────────────────────────────────────────────
    async def create(self, data: dict) -> Asset:
        asset = Asset(org_id=self.org_id, **data)
        self.db.add(asset)
        await self.db.flush()
        await self.db.refresh(asset)
        return asset

    async def get_by_id(self, asset_id: uuid.UUID) -> Asset | None:
        result = await self.db.execute(
            select(Asset).where(Asset.id == asset_id, Asset.org_id == self.org_id)
        )
        return result.scalar_one_or_none()

    async def get_by_type_value(self, asset_type: str, value: str) -> Asset | None:
        result = await self.db.execute(
            select(Asset).where(
                Asset.org_id == self.org_id,
                Asset.type == asset_type,
                Asset.value == value,
            )
        )
        return result.scalar_one_or_none()

    async def update(self, asset_id: uuid.UUID, data: dict) -> Asset | None:
        await self.db.execute(
            update(Asset)
            .where(Asset.id == asset_id, Asset.org_id == self.org_id)
            .values(**data)
        )
        return await self.get_by_id(asset_id)

    async def soft_delete(self, asset_id: uuid.UUID) -> bool:
        result = await self.db.execute(
            update(Asset)
            .where(Asset.id == asset_id, Asset.org_id == self.org_id)
            .values(status="archived")
        )
        return result.rowcount > 0

    async def list_assets(
        self,
        filters: dict,
        params: PageParams,
    ) -> tuple[list[Asset], int]:
        q = select(Asset).where(Asset.org_id == self.org_id)

        if filters.get("type"):
            q = q.where(Asset.type == filters["type"])
        if filters.get("status"):
            q = q.where(Asset.status == filters["status"])
        if filters.get("source"):
            q = q.where(Asset.source == filters["source"])
        if filters.get("value_contains"):
            q = q.where(Asset.value.ilike(f"%{filters['value_contains']}%"))
        if filters.get("tags"):
            for tag in filters["tags"]:
                q = q.where(Asset.tags.contains([tag]))

        # Sort
        sort_col = getattr(Asset, filters.get("sort", "last_seen"), Asset.last_seen)
        if filters.get("order", "desc") == "desc":
            q = q.order_by(sort_col.desc())
        else:
            q = q.order_by(sort_col.asc())

        # Count
        count_q = select(func.count()).select_from(q.subquery())
        total = (await self.db.execute(count_q)).scalar_one()

        # Paginate
        q = q.offset(params.offset).limit(params.limit)
        result = await self.db.execute(q)
        return list(result.scalars().all()), total

    async def upsert(self, data: dict) -> tuple[Asset, bool]:
        """
        Insert or update on conflict (org_id, type, value).
        Returns (asset, created).
        Merge strategy: incoming metadata wins per-key; tags are union-ed.
        """
        now = datetime.now(timezone.utc)
        stmt = (
            pg_insert(Asset)
            .values(
                id=uuid.uuid4(),
                org_id=self.org_id,
                first_seen=now,
                last_seen=now,
                **data,
            )
            .on_conflict_do_update(
                constraint="uq_asset_org_type_value",
                set_={
                    "last_seen": now,
                    # Re-activate stale assets
                    "status": text(
                        "CASE WHEN excluded.status = 'active' THEN 'active' "
                        "ELSE assets.status END"
                    ),
                    # Tags: union (pg array distinct)
                    "tags": text(
                        "ARRAY(SELECT DISTINCT unnest(assets.tags || excluded.tags))"
                    ),
                    # Metadata: merge, incoming wins per key
                    "metadata": text("assets.metadata || excluded.metadata"),
                },
            )
            .returning(Asset)
        )
        result = await self.db.execute(stmt)
        asset = result.scalar_one()
        # Detect if it was an insert or update via first_seen == last_seen
        created = asset.first_seen == asset.last_seen
        return asset, created

    async def mark_stale(self, threshold_days: int) -> int:
        cutoff = datetime.now(timezone.utc)
        result = await self.db.execute(
            update(Asset)
            .where(
                Asset.org_id == self.org_id,
                Asset.status == "active",
                Asset.last_seen < text(f"NOW() - INTERVAL '{threshold_days} days'"),
            )
            .values(status="stale")
        )
        return result.rowcount

    async def mark_all_stale(self, threshold_days: int) -> int:
        """Mark stale across ALL orgs (used by scheduler)."""
        result = await self.db.execute(
            update(Asset)
            .where(
                Asset.status == "active",
                Asset.last_seen < text(f"NOW() - INTERVAL '{threshold_days} days'"),
            )
            .values(status="stale")
        )
        return result.rowcount

    # ── Relationships ─────────────────────────────────────────────────────────
    async def create_relationship(
        self, source_id: uuid.UUID, target_id: uuid.UUID, rel_type: str
    ) -> AssetRelationship:
        rel = AssetRelationship(
            org_id=self.org_id,
            source_id=source_id,
            target_id=target_id,
            rel_type=rel_type,
        )
        self.db.add(rel)
        await self.db.flush()
        await self.db.refresh(rel)
        return rel

    async def get_relationships(self, asset_id: uuid.UUID) -> list[AssetRelationship]:
        result = await self.db.execute(
            select(AssetRelationship).where(
                AssetRelationship.org_id == self.org_id,
                or_(
                    AssetRelationship.source_id == asset_id,
                    AssetRelationship.target_id == asset_id,
                ),
            )
        )
        return list(result.scalars().all())

    async def delete_relationship(self, rel_id: uuid.UUID) -> bool:
        result = await self.db.execute(
            delete(AssetRelationship).where(
                AssetRelationship.id == rel_id,
                AssetRelationship.org_id == self.org_id,
            )
        )
        return result.rowcount > 0

    # ── Import Jobs ───────────────────────────────────────────────────────────
    async def create_job(self, total: int) -> ImportJob:
        job = ImportJob(org_id=self.org_id, total=total, status="queued")
        self.db.add(job)
        await self.db.flush()
        await self.db.refresh(job)
        return job

    async def get_job(self, job_id: uuid.UUID) -> ImportJob | None:
        result = await self.db.execute(
            select(ImportJob).where(
                ImportJob.id == job_id, ImportJob.org_id == self.org_id
            )
        )
        return result.scalar_one_or_none()
