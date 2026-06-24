"""Initial database schema — all tables, enums, indexes."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from alembic import op


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Enums (idempotent — safe to re-run) ────────────────────────────────
    for stmt in [
        "DO $$ BEGIN CREATE TYPE user_role_enum AS ENUM ('admin', 'analyst', 'readonly'); EXCEPTION WHEN duplicate_object THEN NULL; END $$",
        "DO $$ BEGIN CREATE TYPE asset_type_enum AS ENUM ('domain', 'subdomain', 'ip_address', 'service', 'certificate', 'technology'); EXCEPTION WHEN duplicate_object THEN NULL; END $$",
        "DO $$ BEGIN CREATE TYPE asset_status_enum AS ENUM ('active', 'stale', 'archived'); EXCEPTION WHEN duplicate_object THEN NULL; END $$",
        "DO $$ BEGIN CREATE TYPE asset_source_enum AS ENUM ('scan', 'import', 'manual'); EXCEPTION WHEN duplicate_object THEN NULL; END $$",
        "DO $$ BEGIN CREATE TYPE job_status_enum AS ENUM ('queued', 'running', 'done', 'failed'); EXCEPTION WHEN duplicate_object THEN NULL; END $$",
    ]:
        op.execute(stmt)

    # ── organizations ──────────────────────────────────────────────────────
    op.create_table(
        "organizations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("db_url", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("slug", name="uq_org_slug"),
    )
    op.create_index("ix_org_slug", "organizations", ["slug"])

    # ── users ──────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.Text, nullable=False),
        sa.Column("role", sa.Enum("admin", "analyst", "readonly", name="user_role_enum", create_type=False), nullable=False, server_default="readonly"),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("email", name="uq_user_email"),
    )
    op.create_index("ix_user_org", "users", ["org_id"])
    op.create_index("ix_user_email", "users", ["email"])

    # ── assets ─────────────────────────────────────────────────────────────
    op.create_table(
        "assets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.Enum(*["domain","subdomain","ip_address","service","certificate","technology"], name="asset_type_enum", create_type=False), nullable=False),
        sa.Column("value", sa.String(512), nullable=False),
        sa.Column("status", sa.Enum("active","stale","archived", name="asset_status_enum", create_type=False), nullable=False, server_default="active"),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("source", sa.Enum("scan","import","manual", name="asset_source_enum", create_type=False), nullable=False),
        sa.Column("tags", ARRAY(sa.Text), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("metadata", JSONB, server_default=sa.text("'{}'"), nullable=False),
        sa.UniqueConstraint("org_id", "type", "value", name="uq_asset_org_type_value"),
    )
    op.create_index("ix_asset_org_id", "assets", ["org_id"])
    op.create_index("ix_asset_org_type", "assets", ["org_id", "type"])
    op.create_index("ix_asset_org_status", "assets", ["org_id", "status"])
    op.create_index("ix_asset_org_last_seen", "assets", ["org_id", "last_seen"])
    op.create_index("ix_asset_tags_gin", "assets", ["tags"], postgresql_using="gin")
    op.create_index("ix_asset_metadata_gin", "assets", ["metadata"], postgresql_using="gin")

    # ── asset_relationships ────────────────────────────────────────────────
    op.create_table(
        "asset_relationships",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", UUID(as_uuid=True), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_id", UUID(as_uuid=True), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rel_type", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("org_id","source_id","target_id","rel_type", name="uq_relationship_org_src_tgt_type"),
    )
    op.create_index("ix_rel_org", "asset_relationships", ["org_id"])
    op.create_index("ix_rel_source", "asset_relationships", ["source_id"])
    op.create_index("ix_rel_target", "asset_relationships", ["target_id"])

    # ── import_jobs ────────────────────────────────────────────────────────
    op.create_table(
        "import_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.Enum("queued","running","done","failed", name="job_status_enum", create_type=False), nullable=False, server_default="queued"),
        sa.Column("total", sa.Integer, server_default="0"),
        sa.Column("imported", sa.Integer, server_default="0"),
        sa.Column("error_count", sa.Integer, server_default="0"),
        sa.Column("errors", JSONB, server_default=sa.text("'[]'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_job_org", "import_jobs", ["org_id"])


def downgrade() -> None:
    op.drop_table("import_jobs")
    op.drop_table("asset_relationships")
    op.drop_table("assets")
    op.drop_table("users")
    op.drop_table("organizations")
    op.execute("DROP TYPE IF EXISTS job_status_enum")
    op.execute("DROP TYPE IF EXISTS asset_source_enum")
    op.execute("DROP TYPE IF EXISTS asset_status_enum")
    op.execute("DROP TYPE IF EXISTS asset_type_enum")
    op.execute("DROP TYPE IF EXISTS user_role_enum")
