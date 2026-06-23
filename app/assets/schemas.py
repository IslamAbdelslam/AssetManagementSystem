"""Asset Pydantic schemas for CRUD, bulk import, filtering, and job status."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.assets.models import ASSET_SOURCES, ASSET_STATUSES, ASSET_TYPES
from app.core.security import sanitize_string, validate_metadata, validate_tags


# ── Base ───────────────────────────────────────────────────────────────────────
class AssetBase(BaseModel):
    type: str = Field(..., description="Asset type")
    value: str = Field(..., max_length=512)
    status: str = Field("active")
    source: str = Field(..., description="Origin of the asset")
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")

    model_config = {"populate_by_name": True}

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ASSET_TYPES:
            raise ValueError(f"type must be one of: {', '.join(ASSET_TYPES)}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in ASSET_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(ASSET_STATUSES)}")
        return v

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        if v not in ASSET_SOURCES:
            raise ValueError(f"source must be one of: {', '.join(ASSET_SOURCES)}")
        return v

    @field_validator("value")
    @classmethod
    def sanitize_value(cls, v: str) -> str:
        return sanitize_string(v, max_length=512)

    @field_validator("tags")
    @classmethod
    def sanitize_tags(cls, v: list[str]) -> list[str]:
        return validate_tags(v)

    @field_validator("metadata", mode="before")
    @classmethod
    def sanitize_metadata(cls, v: Any) -> dict:
        if v is None:
            return {}
        return validate_metadata(v)


class AssetCreate(AssetBase):
    pass


class AssetUpdate(BaseModel):
    """Partial update — all fields optional."""
    status: str | None = None
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = Field(None, alias="metadata_")
    source: str | None = None

    model_config = {"populate_by_name": True}

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in ASSET_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(ASSET_STATUSES)}")
        return v


class AssetResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    type: str
    value: str
    status: str
    first_seen: datetime
    last_seen: datetime
    source: str
    tags: list[str]
    metadata: dict[str, Any] = Field(alias="metadata_")

    model_config = {"from_attributes": True, "populate_by_name": True}


# ── Bulk Import ────────────────────────────────────────────────────────────────
class BulkImportRecord(BaseModel):
    """Lenient schema for bulk import — allows partial/legacy records."""
    id: str | None = None  # ignored; we use our own UUID
    type: str | None = None
    value: str | None = None
    status: str = "active"
    source: str = "import"
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Legacy relationship hints (processed separately)
    parent: str | None = None
    covers: str | None = None


class BulkImportRequest(BaseModel):
    records: list[BulkImportRecord] = Field(..., min_length=1)


class BulkImportResponse(BaseModel):
    job_id: uuid.UUID
    status: str
    total: int
    message: str


class JobStatusResponse(BaseModel):
    job_id: uuid.UUID
    status: str
    total: int
    imported: int
    error_count: int
    errors: list[dict]
    progress_pct: float


# ── Filtering ──────────────────────────────────────────────────────────────────
class AssetFilter(BaseModel):
    type: str | None = None
    status: str | None = None
    tags: list[str] = Field(default_factory=list)
    value_contains: str | None = None
    source: str | None = None
    sort: str = Field("last_seen", pattern=r"^(last_seen|first_seen|value|type|status)$")
    order: str = Field("desc", pattern=r"^(asc|desc)$")


# ── Relationships ──────────────────────────────────────────────────────────────
REL_TYPES = ("subdomain_of", "resolves_to", "covered_by", "runs_on", "belongs_to")


class RelationshipCreate(BaseModel):
    target_id: uuid.UUID
    rel_type: str = Field(..., description=f"One of: {', '.join(REL_TYPES)}")

    @field_validator("rel_type")
    @classmethod
    def validate_rel_type(cls, v: str) -> str:
        if v not in REL_TYPES:
            raise ValueError(f"rel_type must be one of: {', '.join(REL_TYPES)}")
        return v


class RelationshipResponse(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    target_id: uuid.UUID
    rel_type: str
    created_at: datetime

    model_config = {"from_attributes": True}


class GraphNode(BaseModel):
    id: str
    type: str
    value: str
    status: str


class GraphEdge(BaseModel):
    source: str
    target: str
    rel_type: str


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    depth: int
