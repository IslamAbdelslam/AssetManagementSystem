"""Asset business logic: dedup, lifecycle, merge strategy, seed."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset
from app.assets.repository import AssetRepository
from app.assets.schemas import AssetCreate, AssetUpdate, BulkImportRecord
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.core.security import sanitize_string, validate_metadata, validate_tags

log = get_logger(__name__)


class AssetService:
    def __init__(self, db: AsyncSession, org_id: uuid.UUID) -> None:
        self.repo = AssetRepository(db, org_id)

    async def create(self, body: AssetCreate) -> Asset:
        data = body.model_dump(by_alias=False)
        # Attempt upsert (idempotent by design)
        asset, _ = await self.repo.upsert(data)
        return asset

    async def _get_or_404(self, asset_id: uuid.UUID) -> Asset:
        asset = await self.repo.get_by_id(asset_id)
        if not asset:
            raise NotFoundError("Asset", str(asset_id))
        return asset

    async def get(self, asset_id: uuid.UUID) -> Asset:
        return await self._get_or_404(asset_id)

    async def update(self, asset_id: uuid.UUID, body: AssetUpdate) -> Asset:
        await self._get_or_404(asset_id)
        data = {k: v for k, v in body.model_dump(by_alias=False).items() if v is not None}
        updated = await self.repo.update(asset_id, data)
        return updated  # type: ignore[return-value]

    async def delete(self, asset_id: uuid.UUID) -> None:
        deleted = await self.repo.soft_delete(asset_id)
        if not deleted:
            raise NotFoundError("Asset", str(asset_id))

    async def list_assets(self, filters: dict, params: Any) -> tuple[list[Asset], int]:
        return await self.repo.list_assets(filters, params)

    async def get_stats(self) -> dict:
        return await self.repo.get_stats()

    async def mark_stale(self, threshold_days: int) -> int:
        return await self.repo.mark_stale(threshold_days)

    async def ingest_record(self, record: BulkImportRecord) -> tuple[Asset | None, str | None]:
        """
        Validate and upsert a single record. Returns (asset, error_msg).
        Never raises — errors are collected and returned.
        """
        try:
            if not record.type or record.type not in (
                "domain", "subdomain", "ip_address", "service", "certificate", "technology"
            ):
                return None, f"Invalid or missing 'type': {record.type!r}"
            if not record.value or not record.value.strip():
                return None, "Missing 'value' field"
            if record.source not in ("scan", "import", "manual"):
                record.source = "import"
            if record.status not in ("active", "stale", "archived"):
                record.status = "active"

            value = sanitize_string(record.value, max_length=512)
            tags = validate_tags(record.tags or [])
            metadata = validate_metadata(record.metadata or {})

            data = {
                "type": record.type,
                "value": value,
                "status": record.status,
                "source": record.source,
                "tags": tags,
                "metadata_": metadata,
            }
            asset, _ = await self.repo.upsert(data)
            return asset, None
        except Exception as exc:
            log.warning("asset.ingest.record_failed", error=str(exc))
            return None, str(exc)


async def seed_sample_data() -> None:
    """Load sample_dataset.json into the first organization (dev convenience)."""
    dataset_path = Path("data/sample_dataset.json")
    if not dataset_path.exists():
        log.warning("seed.dataset_not_found", path=str(dataset_path))
        return

    from app.database import get_session_factory
    from app.auth.models import Organization
    from sqlalchemy import select

    factory = get_session_factory()
    async with factory() as db:
        result = await db.execute(select(Organization).limit(1))
        org = result.scalar_one_or_none()
        if not org:
            log.warning("seed.no_org_found")
            return

        records_raw = json.loads(dataset_path.read_text())
        svc = AssetService(db, org.id)
        imported, errors = 0, 0
        for raw in records_raw:
            record = BulkImportRecord(**raw)
            asset, err = await svc.ingest_record(record)
            if asset:
                imported += 1
            else:
                errors += 1
        await db.commit()
        log.info("seed.complete", imported=imported, errors=errors)
