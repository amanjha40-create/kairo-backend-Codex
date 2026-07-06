"""Add verification request engine.

Revision ID: 028
Revises: 027
Create Date: 2026-07-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.verification_requests.enums import (
    VerificationRequestEventSource,
    VerificationRequestStatus,
    VerificationRequestType,
)

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def _enum(name: str, members: tuple[str, ...]) -> postgresql.ENUM:
    return postgresql.ENUM(*members, name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()

    verification_request_type_enum = _enum(
        "verification_request_type_enum",
        tuple(member.value for member in VerificationRequestType),
    )
    verification_request_status_enum = _enum(
        "verification_request_status_enum",
        tuple(member.value for member in VerificationRequestStatus),
    )
    verification_request_event_source_enum = _enum(
        "verification_request_event_source_enum",
        tuple(member.value for member in VerificationRequestEventSource),
    )

    verification_request_type_enum.create(bind, checkfirst=True)
    verification_request_status_enum.create(bind, checkfirst=True)
    verification_request_event_source_enum.create(bind, checkfirst=True)

    op.create_table(
        "verification_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("trust_invitation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject_name", sa.String(length=255), nullable=False),
        sa.Column("subject_email", sa.String(length=320), nullable=False),
        sa.Column("request_type", verification_request_type_enum, nullable=False),
        sa.Column("status", verification_request_status_enum, nullable=False),
        sa.Column("requested_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_to_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column(
            "trust_context",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["assigned_to_user_id"],
            ["users.id"],
            name=op.f("fk_verification_requests_assigned_to_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_verification_requests_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name=op.f("fk_verification_requests_requested_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subject_user_id"],
            ["users.id"],
            name=op.f("fk_verification_requests_subject_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["trust_invitation_id"],
            ["trust_invitations.id"],
            name=op.f("fk_verification_requests_trust_invitation_id_trust_invitations"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_verification_requests")),
        sa.UniqueConstraint("public_id", name=op.f("uq_verification_requests_public_id")),
    )
    op.create_index(op.f("ix_verification_requests_assigned_to_user_id"), "verification_requests", ["assigned_to_user_id"])
    op.create_index(op.f("ix_verification_requests_due_date"), "verification_requests", ["due_date"])
    op.create_index(op.f("ix_verification_requests_organization_id"), "verification_requests", ["organization_id"])
    op.create_index(op.f("ix_verification_requests_request_type"), "verification_requests", ["request_type"])
    op.create_index(op.f("ix_verification_requests_requested_by_user_id"), "verification_requests", ["requested_by_user_id"])
    op.create_index(op.f("ix_verification_requests_status"), "verification_requests", ["status"])
    op.create_index(op.f("ix_verification_requests_subject_email"), "verification_requests", ["subject_email"])
    op.create_index(op.f("ix_verification_requests_subject_user_id"), "verification_requests", ["subject_user_id"])
    op.create_index(op.f("ix_verification_requests_trust_invitation_id"), "verification_requests", ["trust_invitation_id"])

    op.create_table(
        "verification_request_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("verification_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("event_source", verification_request_event_source_enum, nullable=False),
        sa.Column("previous_status", verification_request_status_enum, nullable=True),
        sa.Column("new_status", verification_request_status_enum, nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_verification_request_events_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["verification_request_id"],
            ["verification_requests.id"],
            name=op.f("fk_verification_request_events_verification_request_id_verification_requests"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_verification_request_events")),
        sa.UniqueConstraint("public_id", name=op.f("uq_verification_request_events_public_id")),
    )
    op.create_index(op.f("ix_verification_request_events_actor_user_id"), "verification_request_events", ["actor_user_id"])
    op.create_index(op.f("ix_verification_request_events_created_at"), "verification_request_events", ["created_at"])
    op.create_index(op.f("ix_verification_request_events_event_source"), "verification_request_events", ["event_source"])
    op.create_index(op.f("ix_verification_request_events_verification_request_id"), "verification_request_events", ["verification_request_id"])


def downgrade() -> None:
    bind = op.get_bind()

    verification_request_event_source_enum = _enum(
        "verification_request_event_source_enum",
        tuple(member.value for member in VerificationRequestEventSource),
    )
    verification_request_status_enum = _enum(
        "verification_request_status_enum",
        tuple(member.value for member in VerificationRequestStatus),
    )
    verification_request_type_enum = _enum(
        "verification_request_type_enum",
        tuple(member.value for member in VerificationRequestType),
    )

    op.drop_index(op.f("ix_verification_request_events_verification_request_id"), table_name="verification_request_events")
    op.drop_index(op.f("ix_verification_request_events_event_source"), table_name="verification_request_events")
    op.drop_index(op.f("ix_verification_request_events_created_at"), table_name="verification_request_events")
    op.drop_index(op.f("ix_verification_request_events_actor_user_id"), table_name="verification_request_events")
    op.drop_table("verification_request_events")

    op.drop_index(op.f("ix_verification_requests_trust_invitation_id"), table_name="verification_requests")
    op.drop_index(op.f("ix_verification_requests_subject_user_id"), table_name="verification_requests")
    op.drop_index(op.f("ix_verification_requests_subject_email"), table_name="verification_requests")
    op.drop_index(op.f("ix_verification_requests_status"), table_name="verification_requests")
    op.drop_index(op.f("ix_verification_requests_requested_by_user_id"), table_name="verification_requests")
    op.drop_index(op.f("ix_verification_requests_request_type"), table_name="verification_requests")
    op.drop_index(op.f("ix_verification_requests_organization_id"), table_name="verification_requests")
    op.drop_index(op.f("ix_verification_requests_due_date"), table_name="verification_requests")
    op.drop_index(op.f("ix_verification_requests_assigned_to_user_id"), table_name="verification_requests")
    op.drop_table("verification_requests")

    verification_request_event_source_enum.drop(bind, checkfirst=True)
    verification_request_status_enum.drop(bind, checkfirst=True)
    verification_request_type_enum.drop(bind, checkfirst=True)
