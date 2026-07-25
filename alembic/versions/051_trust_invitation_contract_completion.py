"""Complete HR trust invitation contract.

Revision ID: 051
Revises: 050
Create Date: 2026-07-24
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.trust_invitations.enums import (
    TrustInvitationDeliveryMethod,
    TrustInvitationDeliveryState,
    TrustInvitationEventType,
)

revision = "051"
down_revision = "050"
branch_labels = None
depends_on = None


def _enum(name: str, members: tuple[str, ...]) -> postgresql.ENUM:
    return postgresql.ENUM(*members, name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()

    op.execute("ALTER TYPE trust_invitation_status_enum ADD VALUE IF NOT EXISTS 'draft'")
    op.execute("ALTER TYPE trust_invitation_status_enum ADD VALUE IF NOT EXISTS 'expired'")

    delivery_method_enum = _enum(
        "trust_invitation_delivery_method_enum",
        tuple(member.value for member in TrustInvitationDeliveryMethod),
    )
    delivery_state_enum = _enum(
        "trust_invitation_delivery_state_enum",
        tuple(member.value for member in TrustInvitationDeliveryState),
    )
    delivery_method_enum.create(bind, checkfirst=True)
    delivery_state_enum.create(bind, checkfirst=True)

    op.add_column("trust_invitations", sa.Column("subject_phone", sa.String(length=32), nullable=True))
    op.add_column("trust_invitations", sa.Column("purpose", sa.String(length=255), nullable=True))
    op.add_column(
        "trust_invitations",
        sa.Column(
            "requested_verification_types",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column("trust_invitations", sa.Column("message", sa.Text(), nullable=True))
    op.add_column(
        "trust_invitations",
        sa.Column(
            "delivery_method",
            delivery_method_enum,
            nullable=False,
            server_default=TrustInvitationDeliveryMethod.EMAIL.value,
        ),
    )
    op.add_column(
        "trust_invitations",
        sa.Column(
            "delivery_state",
            delivery_state_enum,
            nullable=False,
            server_default=TrustInvitationDeliveryState.QUEUED.value,
        ),
    )
    op.add_column("trust_invitations", sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("trust_invitations", sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "trust_invitation_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invitation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("metadata_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_trust_invitation_events_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["invitation_id"],
            ["trust_invitations.id"],
            name=op.f("fk_trust_invitation_events_invitation_id_trust_invitations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trust_invitation_events")),
    )
    op.create_index(op.f("ix_trust_invitation_events_actor_user_id"), "trust_invitation_events", ["actor_user_id"])
    op.create_index(op.f("ix_trust_invitation_events_event_type"), "trust_invitation_events", ["event_type"])
    op.create_index(op.f("ix_trust_invitation_events_invitation_id"), "trust_invitation_events", ["invitation_id"])
    op.create_index(op.f("ix_trust_invitation_events_occurred_at"), "trust_invitation_events", ["occurred_at"])

    op.execute(
        sa.text(
            """
            UPDATE trust_invitations
            SET delivery_method = CAST(:delivery_method AS trust_invitation_delivery_method_enum),
                delivery_state = CASE
                    WHEN accepted_at IS NOT NULL THEN CAST(:opened_state AS trust_invitation_delivery_state_enum)
                    ELSE CAST(:delivered_state AS trust_invitation_delivery_state_enum)
                END,
                sent_at = COALESCE(sent_at, created_at),
                opened_at = CASE
                    WHEN accepted_at IS NOT NULL THEN COALESCE(opened_at, accepted_at)
                    ELSE opened_at
                END
            """
        ).bindparams(
            delivery_method=TrustInvitationDeliveryMethod.EMAIL.value,
            delivered_state=TrustInvitationDeliveryState.DELIVERED.value,
            opened_state=TrustInvitationDeliveryState.OPENED.value,
        )
    )

    invitation_table = sa.table(
        "trust_invitations",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("created_by_user_id", postgresql.UUID(as_uuid=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("sent_at", sa.DateTime(timezone=True)),
        sa.column("opened_at", sa.DateTime(timezone=True)),
        sa.column("accepted_at", sa.DateTime(timezone=True)),
        sa.column("cancelled_at", sa.DateTime(timezone=True)),
        sa.column("status", sa.String()),
    )
    event_table = sa.table(
        "trust_invitation_events",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("invitation_id", postgresql.UUID(as_uuid=True)),
        sa.column("event_type", sa.String()),
        sa.column("actor_user_id", postgresql.UUID(as_uuid=True)),
        sa.column("metadata_payload", postgresql.JSONB(astext_type=sa.Text())),
        sa.column("occurred_at", sa.DateTime(timezone=True)),
    )

    rows = bind.execute(sa.select(invitation_table)).mappings().all()
    for row in rows:
        payloads: list[dict[str, object]] = [
            {
                "id": uuid.uuid4(),
                "invitation_id": row["id"],
                "event_type": TrustInvitationEventType.CREATED.value,
                "actor_user_id": row["created_by_user_id"],
                "metadata_payload": {},
                "occurred_at": row["created_at"],
            },
            {
                "id": uuid.uuid4(),
                "invitation_id": row["id"],
                "event_type": TrustInvitationEventType.SENT.value,
                "actor_user_id": row["created_by_user_id"],
                "metadata_payload": {},
                "occurred_at": row["sent_at"] or row["created_at"],
            },
        ]
        if row["opened_at"] is not None:
            payloads.append(
                {
                    "id": uuid.uuid4(),
                    "invitation_id": row["id"],
                    "event_type": TrustInvitationEventType.OPENED.value,
                    "actor_user_id": None,
                    "metadata_payload": {},
                    "occurred_at": row["opened_at"],
                }
            )
        if row["accepted_at"] is not None:
            payloads.append(
                {
                    "id": uuid.uuid4(),
                    "invitation_id": row["id"],
                    "event_type": TrustInvitationEventType.ACCEPTED.value,
                    "actor_user_id": None,
                    "metadata_payload": {},
                    "occurred_at": row["accepted_at"],
                }
            )
        if row["cancelled_at"] is not None:
            payloads.append(
                {
                    "id": uuid.uuid4(),
                    "invitation_id": row["id"],
                    "event_type": TrustInvitationEventType.CANCELLED.value,
                    "actor_user_id": None,
                    "metadata_payload": {},
                    "occurred_at": row["cancelled_at"],
                }
            )
        if row["status"] == "expired":
            payloads.append(
                {
                    "id": uuid.uuid4(),
                    "invitation_id": row["id"],
                    "event_type": TrustInvitationEventType.EXPIRED.value,
                    "actor_user_id": None,
                    "metadata_payload": {},
                    "occurred_at": row["accepted_at"] or row["cancelled_at"] or row["sent_at"] or row["created_at"] or datetime.now(tz=UTC),
                }
            )
        bind.execute(sa.insert(event_table), payloads)

    op.alter_column("trust_invitations", "requested_verification_types", server_default=None)
    op.alter_column("trust_invitations", "delivery_method", server_default=None)
    op.alter_column("trust_invitations", "delivery_state", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    delivery_method_enum = _enum(
        "trust_invitation_delivery_method_enum",
        tuple(member.value for member in TrustInvitationDeliveryMethod),
    )
    delivery_state_enum = _enum(
        "trust_invitation_delivery_state_enum",
        tuple(member.value for member in TrustInvitationDeliveryState),
    )

    op.drop_index(op.f("ix_trust_invitation_events_occurred_at"), table_name="trust_invitation_events")
    op.drop_index(op.f("ix_trust_invitation_events_invitation_id"), table_name="trust_invitation_events")
    op.drop_index(op.f("ix_trust_invitation_events_event_type"), table_name="trust_invitation_events")
    op.drop_index(op.f("ix_trust_invitation_events_actor_user_id"), table_name="trust_invitation_events")
    op.drop_table("trust_invitation_events")

    op.drop_column("trust_invitations", "opened_at")
    op.drop_column("trust_invitations", "sent_at")
    op.drop_column("trust_invitations", "delivery_state")
    op.drop_column("trust_invitations", "delivery_method")
    op.drop_column("trust_invitations", "message")
    op.drop_column("trust_invitations", "requested_verification_types")
    op.drop_column("trust_invitations", "purpose")
    op.drop_column("trust_invitations", "subject_phone")

    delivery_state_enum.drop(bind, checkfirst=True)
    delivery_method_enum.drop(bind, checkfirst=True)
