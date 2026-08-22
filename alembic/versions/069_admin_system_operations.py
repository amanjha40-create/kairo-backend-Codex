"""Add Admin System Operations incidents.

Revision ID: 069
Revises: 068
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "069"
down_revision = "068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_incidents",
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("reference_type", sa.String(length=64), nullable=True),
        sa.Column("reference_public_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resolved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index(op.f("ix_system_incidents_category"), "system_incidents", ["category"], unique=False)
    op.create_index(op.f("ix_system_incidents_created_by_user_id"), "system_incidents", ["created_by_user_id"], unique=False)
    op.create_index(op.f("ix_system_incidents_opened_at"), "system_incidents", ["opened_at"], unique=False)
    op.create_index(op.f("ix_system_incidents_public_id"), "system_incidents", ["public_id"], unique=False)
    op.create_index(op.f("ix_system_incidents_reference_public_id"), "system_incidents", ["reference_public_id"], unique=False)
    op.create_index(op.f("ix_system_incidents_resolved_by_user_id"), "system_incidents", ["resolved_by_user_id"], unique=False)
    op.create_index(op.f("ix_system_incidents_severity"), "system_incidents", ["severity"], unique=False)
    op.create_index(op.f("ix_system_incidents_status"), "system_incidents", ["status"], unique=False)

    op.create_table(
        "system_incident_events",
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["incident_id"], ["system_incidents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index(op.f("ix_system_incident_events_actor_user_id"), "system_incident_events", ["actor_user_id"], unique=False)
    op.create_index(op.f("ix_system_incident_events_created_at"), "system_incident_events", ["created_at"], unique=False)
    op.create_index(op.f("ix_system_incident_events_event_type"), "system_incident_events", ["event_type"], unique=False)
    op.create_index(op.f("ix_system_incident_events_incident_id"), "system_incident_events", ["incident_id"], unique=False)
    op.create_index(op.f("ix_system_incident_events_public_id"), "system_incident_events", ["public_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_system_incident_events_public_id"), table_name="system_incident_events")
    op.drop_index(op.f("ix_system_incident_events_incident_id"), table_name="system_incident_events")
    op.drop_index(op.f("ix_system_incident_events_event_type"), table_name="system_incident_events")
    op.drop_index(op.f("ix_system_incident_events_created_at"), table_name="system_incident_events")
    op.drop_index(op.f("ix_system_incident_events_actor_user_id"), table_name="system_incident_events")
    op.drop_table("system_incident_events")

    op.drop_index(op.f("ix_system_incidents_status"), table_name="system_incidents")
    op.drop_index(op.f("ix_system_incidents_severity"), table_name="system_incidents")
    op.drop_index(op.f("ix_system_incidents_resolved_by_user_id"), table_name="system_incidents")
    op.drop_index(op.f("ix_system_incidents_reference_public_id"), table_name="system_incidents")
    op.drop_index(op.f("ix_system_incidents_public_id"), table_name="system_incidents")
    op.drop_index(op.f("ix_system_incidents_opened_at"), table_name="system_incidents")
    op.drop_index(op.f("ix_system_incidents_created_by_user_id"), table_name="system_incidents")
    op.drop_index(op.f("ix_system_incidents_category"), table_name="system_incidents")
    op.drop_table("system_incidents")
