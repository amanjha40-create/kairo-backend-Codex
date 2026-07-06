"""Verification request model."""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING, Any

from sqlalchemy import Date, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.db.pg_enums import verification_request_status_enum, verification_request_type_enum
from app.verification_requests.enums import VerificationRequestStatus, VerificationRequestType

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.trust_invitation import TrustInvitation
    from app.models.verification_request_event import VerificationRequestEvent


class VerificationRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Canonical organization-owned verification workflow object."""

    __tablename__ = "verification_requests"

    public_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, default=uuid.uuid4, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    trust_invitation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("trust_invitations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    subject_name: Mapped[str] = mapped_column(String(255), nullable=False)
    subject_email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    request_type: Mapped[VerificationRequestType] = mapped_column(verification_request_type_enum, nullable=False)
    status: Mapped[VerificationRequestStatus] = mapped_column(verification_request_status_enum, nullable=False)
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    trust_context: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    organization: Mapped["Organization"] = relationship("Organization", back_populates="verification_requests")
    trust_invitation: Mapped["TrustInvitation | None"] = relationship("TrustInvitation", back_populates="verification_requests")
    events: Mapped[list["VerificationRequestEvent"]] = relationship(
        "VerificationRequestEvent",
        back_populates="verification_request",
        cascade="all, delete-orphan",
        order_by="VerificationRequestEvent.created_at.asc()",
    )

    def __repr__(self) -> str:
        return (
            "VerificationRequest("
            f"id={self.id}, public_id={self.public_id}, organization_id={self.organization_id}, status={self.status})"
        )
