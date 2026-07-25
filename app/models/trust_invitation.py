"""Trust invitation model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.db.pg_enums import (
    trust_invitation_delivery_method_enum,
    trust_invitation_delivery_state_enum,
    trust_invitation_status_enum,
)
from app.trust_invitations.enums import (
    TrustInvitationDeliveryMethod,
    TrustInvitationDeliveryState,
    TrustInvitationStatus,
)

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.organization_person import OrganizationPerson
    from app.models.trust_invitation_event import TrustInvitationEvent
    from app.models.user import User
    from app.models.verification_request import VerificationRequest


class TrustInvitation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Generic trust invitation issued by an organization."""

    __tablename__ = "trust_invitations"

    public_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, default=uuid.uuid4, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_person_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organization_people.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    subject_name: Mapped[str] = mapped_column(String(255), nullable=False)
    subject_email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    subject_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    purpose: Mapped[str | None] = mapped_column(String(255), nullable=True)
    requested_verification_types: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    status: Mapped[TrustInvitationStatus] = mapped_column(trust_invitation_status_enum, nullable=False)
    delivery_method: Mapped[TrustInvitationDeliveryMethod] = mapped_column(
        trust_invitation_delivery_method_enum,
        nullable=False,
        default=TrustInvitationDeliveryMethod.EMAIL,
        server_default=TrustInvitationDeliveryMethod.EMAIL.value,
    )
    delivery_state: Mapped[TrustInvitationDeliveryState] = mapped_column(
        trust_invitation_delivery_state_enum,
        nullable=False,
        default=TrustInvitationDeliveryState.QUEUED,
        server_default=TrustInvitationDeliveryState.QUEUED.value,
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    accepted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped["Organization"] = relationship("Organization", back_populates="trust_invitations")
    organization_person: Mapped["OrganizationPerson | None"] = relationship(
        "OrganizationPerson",
        back_populates="trust_invitations",
    )
    created_by_user: Mapped["User"] = relationship("User", foreign_keys=[created_by_user_id])
    accepted_by_user: Mapped["User | None"] = relationship("User", foreign_keys=[accepted_by_user_id])
    verification_requests: Mapped[list["VerificationRequest"]] = relationship(
        "VerificationRequest",
        back_populates="trust_invitation",
    )
    events: Mapped[list["TrustInvitationEvent"]] = relationship(
        "TrustInvitationEvent",
        back_populates="invitation",
        cascade="all, delete-orphan",
        order_by="TrustInvitationEvent.occurred_at",
    )

    def __repr__(self) -> str:
        return (
            "TrustInvitation("
            f"id={self.id}, public_id={self.public_id}, organization_id={self.organization_id}, status={self.status})"
        )
