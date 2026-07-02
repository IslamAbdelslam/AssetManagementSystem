"""Tests for asset service edge cases (seeding and exception handling)."""
from __future__ import annotations

import contextlib
import json
import uuid
from unittest.mock import patch

import pytest

from app.assets.schemas import BulkImportRecord
from app.assets.service import AssetService, seed_sample_data
from app.auth.models import Organization

pytestmark = pytest.mark.asyncio


async def test_seed_sample_data_success(db_session):
    # Ensure there is an org
    org = Organization(id=uuid.uuid4(), name="Test Org", slug="test-org")
    db_session.add(org)
    await db_session.commit()

    mock_dataset = [
        {"type": "domain", "value": "test1.com"},
        {"type": "subdomain", "value": "api.test1.com"}
    ]

    @contextlib.asynccontextmanager
    async def mock_factory():
        yield db_session

    with patch("app.assets.service.Path.exists", return_value=True), \
         patch("app.assets.service.Path.read_text", return_value=json.dumps(mock_dataset)), \
         patch("app.database.get_session_factory", return_value=mock_factory):
         await seed_sample_data()

    # Verify assets were created regardless of which org_id limit(1) picked
    from app.assets.models import Asset
    from sqlalchemy import select
    result = await db_session.execute(select(Asset).where(Asset.value.in_(["test1.com", "api.test1.com"])))
    assets = result.scalars().all()
    assert len(assets) == 2


async def test_seed_sample_data_no_file(db_session):
    # Should exit gracefully without raising
    with patch("app.assets.service.Path.exists", return_value=False):
        await seed_sample_data()


async def test_ingest_record_exception_handling(db_session):
    org_id = uuid.uuid4()
    svc = AssetService(db_session, org_id)

    record = BulkImportRecord(
        type="domain",
        value="crash.com",
        source="import",
        status="active"
    )

    # Force an exception during upsert
    with patch("app.assets.service.AssetRepository.upsert", side_effect=Exception("DB connection lost")):
        asset, error = await svc.ingest_record(record)
        assert asset is None
        assert error is not None
        assert "DB connection lost" in error


async def test_ingest_record_default_assignments(db_session):
    org_id = uuid.uuid4()
    svc = AssetService(db_session, org_id)

    # Record with invalid source/status gets defaulted
    record = BulkImportRecord(
        type="domain",
        value="default.com",
        source="unknown_source",
        status="unknown_status"
    )

    with patch("app.assets.service.AssetRepository.upsert", return_value=(None, True)) as mock_upsert:
        await svc.ingest_record(record)
        
        # Verify defaults were applied
        call_args = mock_upsert.call_args[0][0]
        assert call_args["source"] == "import"
        assert call_args["status"] == "active"
