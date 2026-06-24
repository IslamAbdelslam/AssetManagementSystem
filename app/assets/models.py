"""Asset ORM models: Asset, AssetRelationship, ImportJob."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    ARRAY, DateTime, Enum, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


ASSET_TYPES = ("domain", "subdomain", "ip_address", "service", "certificate", "technology")
ASSET_STATUSES = ("active", "stale", "archived")
ASSET_SOURCES = ("scan", "import", "manual")
JOB_STATUSES = ("queued", "running", "done", "failed")


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (
        UniqueConstraint("org_id", "type", "value", name="uq_asset_org_type_value"),
        Index("ix_asset_org_type", "org_id", "type"),
        Index("ix_asset_org_status", "org_id", "status"),
        Index("ix_asset_org_last_seen", "org_id", "last_seen"),
        Index("ix_asset_tags_gin", "tags", postgresql_using="gin"),
        Index("ix_asset_metadata_gin", "metadata", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(
        Enum(*ASSET_TYPES, name="asset_type_enum", create_type=False), nullable=False
    )
    value: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(*ASSET_STATUSES, name="asset_status_enum", create_type=False),
        nullable=False,
        default="active",
    )
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    source: Mapped[str] = mapped_column(
        Enum(*ASSET_SOURCES, name="asset_source_enum", create_type=False), nullable=False
    )
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    relationships_as_source: Mapped[list["AssetRelationship"]] = relationship(
        "AssetRelationship",
        foreign_keys="AssetRelationship.source_id",
        back_populates="source",
        cascade="all, delete-orphan",
    )
    relationships_as_target: Mapped[list["AssetRelationship"]] = relationship(
        "AssetRelationship",
        foreign_keys="AssetRelationship.target_id",
        back_populates="target",
        cascade="all, delete-orphan",
    )


class AssetRelationship(Base):
    __tablename__ = "asset_relationships"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "source_id", "target_id", "rel_type",
            name="uq_relationship_org_src_tgt_type",
        ),
        Index("ix_rel_source", "source_id"),
        Index("ix_rel_target", "target_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    rel_type: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    source: Mapped["Asset"] = relationship(
        "Asset", foreign_keys=[source_id], back_populates="relationships_as_source"
    )
    target: Mapped["Asset"] = relationship(
        "Asset", foreign_keys=[target_id], back_populates="relationships_as_target"
    )


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        Enum(*JOB_STATUSES, name="job_status_enum", create_type=False),
        nullable=False,
        default="queued",
    )
    total: Mapped[int] = mapped_column(Integer, default=0)
    imported: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
