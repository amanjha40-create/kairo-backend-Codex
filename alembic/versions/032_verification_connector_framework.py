"""Add verification connector framework tables.

Revision ID: 032
Revises: 031
Create Date: 2026-07-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "verification_connectors",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connector_key", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("connector_type", sa.String(length=64), nullable=False),
        sa.Column(
            "supported_capabilities",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "supported_registry_types",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("health_status", sa.String(length=32), nullable=False, server_default="healthy"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("last_health_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_verification_connectors")),
        sa.UniqueConstraint("public_id", name=op.f("uq_verification_connectors_public_id")),
        sa.UniqueConstraint("connector_key", name=op.f("uq_verification_connectors_connector_key")),
    )
    op.create_index(op.f("ix_verification_connectors_connector_key"), "verification_connectors", ["connector_key"], unique=False)
    op.create_index(op.f("ix_verification_connectors_connector_type"), "verification_connectors", ["connector_type"], unique=False)
    op.create_index(op.f("ix_verification_connectors_enabled"), "verification_connectors", ["enabled"], unique=False)
    op.create_index(op.f("ix_verification_connectors_health_status"), "verification_connectors", ["health_status"], unique=False)
    op.create_index(op.f("ix_verification_connectors_priority"), "verification_connectors", ["priority"], unique=False)

    op.create_table(
        "verification_connector_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connector_key", sa.String(length=64), nullable=False),
        sa.Column("verification_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("registry_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_time_ms", sa.Integer(), nullable=True),
        sa.Column(
            "normalized_result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "raw_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "evidence_references",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "error",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["connector_key"],
            ["verification_connectors.connector_key"],
            name="fk_ver_connector_runs_connector_key",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["verification_request_id"],
            ["verification_requests.id"],
            name="fk_ver_connector_runs_request",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["registry_record_id"],
            ["trust_registry_records.id"],
            name="fk_ver_connector_runs_registry",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_verification_connector_runs")),
        sa.UniqueConstraint("public_id", name=op.f("uq_verification_connector_runs_public_id")),
    )
    op.create_index(
        op.f("ix_verification_connector_runs_connector_key"),
        "verification_connector_runs",
        ["connector_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_verification_connector_runs_verification_request_id"),
        "verification_connector_runs",
        ["verification_request_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_verification_connector_runs_registry_record_id"),
        "verification_connector_runs",
        ["registry_record_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_verification_connector_runs_status"),
        "verification_connector_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_verification_connector_runs_connector_key_started_at",
        "verification_connector_runs",
        ["connector_key", "started_at"],
        unique=False,
    )
    op.create_index(
        "ix_verification_connector_runs_request_started_at",
        "verification_connector_runs",
        ["verification_request_id", "started_at"],
        unique=False,
    )

    op.execute(
        sa.text(
            """
            INSERT INTO verification_connectors (
                id,
                public_id,
                connector_key,
                display_name,
                connector_type,
                supported_capabilities,
                supported_registry_types,
                version,
                health_status,
                enabled,
                priority,
                config
            ) VALUES (
                gen_random_uuid(),
                gen_random_uuid(),
                'mock_connector',
                'Mock Verification Connector',
                'custom',
                '["employment","education","identity","document","license","medical","reference","platform","certification","custom"]'::jsonb,
                '["*"]'::jsonb,
                'v1',
                'healthy',
                true,
                100,
                '{"default_mode":"success"}'::jsonb
            )
            ON CONFLICT (connector_key) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_verification_connector_runs_request_started_at", table_name="verification_connector_runs")
    op.drop_index("ix_verification_connector_runs_connector_key_started_at", table_name="verification_connector_runs")
    op.drop_index(op.f("ix_verification_connector_runs_status"), table_name="verification_connector_runs")
    op.drop_index(op.f("ix_verification_connector_runs_registry_record_id"), table_name="verification_connector_runs")
    op.drop_index(op.f("ix_verification_connector_runs_verification_request_id"), table_name="verification_connector_runs")
    op.drop_index(op.f("ix_verification_connector_runs_connector_key"), table_name="verification_connector_runs")
    op.drop_table("verification_connector_runs")

    op.drop_index(op.f("ix_verification_connectors_priority"), table_name="verification_connectors")
    op.drop_index(op.f("ix_verification_connectors_health_status"), table_name="verification_connectors")
    op.drop_index(op.f("ix_verification_connectors_enabled"), table_name="verification_connectors")
    op.drop_index(op.f("ix_verification_connectors_connector_type"), table_name="verification_connectors")
    op.drop_index(op.f("ix_verification_connectors_connector_key"), table_name="verification_connectors")
    op.drop_table("verification_connectors")
