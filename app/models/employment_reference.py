"""Private, versioned employment references, separate from verification and scoring."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class EmploymentReference(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "employment_references"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('hr_reference', 'reporting_manager_reference')", name="reference_kind"
        ),
        CheckConstraint(
            "status IN ('pending', 'cannot_confirm', 'awaiting_hr_validation', "
            "'ready_to_invite', 'invitation_sent', 'opened', 'completed', 'declined', "
            "'expired', 'needs_review')",
            name="reference_status",
        ),
        Index(
            "uq_employment_reference_active",
            "employment_id",
            "kind",
            unique=True,
            postgresql_where=text("active"),
        ),
        Index(
            "uq_employment_reference_hr",
            "employment_id",
            unique=True,
            postgresql_where=text("kind = 'hr_reference'"),
        ),
    )

    employment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employments.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    status: Mapped[str] = mapped_column(String(32))
    nomination: Mapped[dict] = mapped_column(JSONB, default=dict)
    validation: Mapped[dict] = mapped_column(JSONB, default=dict)
    answers: Mapped[dict] = mapped_column(JSONB, default=dict)
    hr_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employer_verification_requests.id", ondelete="SET NULL")
    )
    nominated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmploymentReferenceInvitation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "employment_reference_invitations"
    __table_args__ = (
        UniqueConstraint("reference_id", "idempotency_key", name="uq_reference_send_key"),
        Index(
            "uq_reference_live_token",
            "reference_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    reference_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employment_references.id", ondelete="CASCADE"), index=True
    )
    idempotency_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_status: Mapped[str] = mapped_column(String(32), default="pending")


class EmploymentReferenceEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "employment_reference_events"

    reference_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employment_references.id", ondelete="CASCADE"), index=True
    )
    event: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
