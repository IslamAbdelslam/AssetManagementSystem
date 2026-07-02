"""
Celery tasks — bulk import processor.
Chunks records into batches of 5000 for high-throughput upsert.
Progress is written to Redis so GET /jobs/{id} can report live status.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import redis as sync_redis

from app.config import get_settings
from app.jobs.celery_app import celery_app

settings = get_settings()
CHUNK_SIZE = 5_000


def _get_sync_redis():
    return sync_redis.from_url(settings.REDIS_URL, decode_responses=True)


def _progress_key(job_id: str) -> str:
    return f"job_progress:{job_id}"


@celery_app.task(bind=True, name="app.jobs.tasks.bulk_import_task")
def bulk_import_task(
    self,
    org_id: str,
    job_id: str,
    records: list[dict[str, Any]],
) -> dict:
    """
    Processes bulk import records in async chunks.
    Updates progress in Redis after each chunk.
    """
    return asyncio.run(
        _run_bulk_import(org_id, job_id, records)
    )


async def _run_bulk_import(
    org_id_str: str,
    job_id_str: str,
    records: list[dict[str, Any]],
) -> dict:
    from app.assets.schemas import BulkImportRecord
    from app.assets.service import AssetService
    from app.database import get_session_factory

    org_id = uuid.UUID(org_id_str)
    job_id = uuid.UUID(job_id_str)
    r = _get_sync_redis()
    factory = get_session_factory()

    total = len(records)
    imported = 0
    error_count = 0
    errors: list[dict] = []

    # Update job status to running
    r.hset(_progress_key(job_id_str), mapping={
        "status": "running", "total": total, "imported": 0,
        "error_count": 0, "progress_pct": 0,
    })

    # Process in chunks
    temp_id_to_uuid = {}
    pending_relationships = []

    for chunk_start in range(0, total, CHUNK_SIZE):
        chunk = records[chunk_start: chunk_start + CHUNK_SIZE]
        async with factory() as db:
            svc = AssetService(db, org_id)
            for idx, raw in enumerate(chunk):
                global_idx = chunk_start + idx
                try:
                    record = BulkImportRecord(**raw)
                    asset, err = await svc.ingest_record(record)
                    if asset:
                        imported += 1
                        if raw.get("id"):
                            temp_id_to_uuid[str(raw["id"])] = asset.id
                        
                        if record.parent:
                            pending_relationships.append((str(raw.get("id")), record.parent, "subdomain_of"))
                        if record.covers:
                            # If A covers B, then B is covered_by A. So source=B, target=A.
                            pending_relationships.append((record.covers, str(raw.get("id")), "covered_by"))
                    else:
                        error_count += 1
                        errors.append({
                            "index": global_idx,
                            "record_id": raw.get("id"),
                            "reason": err,
                        })
                except Exception as exc:
                    error_count += 1
                    errors.append({
                        "index": global_idx,
                        "record_id": raw.get("id"),
                        "reason": str(exc),
                    })
            await db.commit()

        # Update progress after each chunk
        progress_pct = round((chunk_start + len(chunk)) / total * 100, 1)
        r.hset(_progress_key(job_id_str), mapping={
            "imported": imported,
            "error_count": error_count,
            "progress_pct": progress_pct,
        })

    # Process pending relationships
    if pending_relationships:
        async with factory() as db:
            from app.assets.models import AssetRelationship
            for source_temp, target_temp, rel_type in pending_relationships:
                source_id = temp_id_to_uuid.get(source_temp)
                target_id = temp_id_to_uuid.get(target_temp)
                if source_id and target_id:
                    # Upsert relationship
                    from sqlalchemy.dialects.postgresql import insert as pg_insert
                    stmt = pg_insert(AssetRelationship).values(
                        id=uuid.uuid4(),
                        org_id=org_id,
                        source_id=source_id,
                        target_id=target_id,
                        rel_type=rel_type,
                    ).on_conflict_do_nothing()
                    await db.execute(stmt)
            await db.commit()

    # Final status
    final_status = "done" if error_count < total else "failed"
    r.hset(_progress_key(job_id_str), mapping={
        "status": final_status,
        "imported": imported,
        "error_count": error_count,
        "progress_pct": 100.0,
        "errors": json.dumps(errors[:500]),  # cap stored errors
    })
    r.expire(_progress_key(job_id_str), 86400)  # TTL 24h

    # Update DB job record
    async with factory() as db:
        from sqlalchemy import update
        from app.assets.models import ImportJob
        await db.execute(
            update(ImportJob)
            .where(ImportJob.id == job_id)
            .values(
                status=final_status,
                imported=imported,
                error_count=error_count,
                errors=errors[:500],
            )
        )
        await db.commit()

    return {"job_id": job_id_str, "status": final_status, "imported": imported}
