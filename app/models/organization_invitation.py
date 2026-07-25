"""Pending organization invitations for workspace access."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.db.pg_enums import organization_invitation_status_enum, organization_role_enum
from app.organization.enums import OrganizationInvitationStatus, OrganizationRole

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.user import User


class OrganizationInvitation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Invitation for a user to join an organization workspace."""

    __tablename__ = "organization_invitations"

    public_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, default=uuid.uuid4, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    invited_by_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    invitee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    invitee_email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    role: Mapped[OrganizationRole] = mapped_column(organization_role_enum, nullable=False)
    status: Mapped[OrganizationInvitationStatus] = mapped_column(
        organization_invitation_status_enum,
        nullable=False,
        default=OrganizationInvitationStatus.PENDING,
        server_default=OrganizationInvitationStatus.PENDING.value,
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    declined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped["Organization"] = relationship("Organization", back_populates="invitations")
    invited_by_user: Mapped["User"] = relationship("User", foreign_keys=[invited_by_user_id])
    invitee_user: Mapped["User | None"] = relationship("User", foreign_keys=[invitee_user_id])

    def __repr__(self) -> str:
        return (
            "OrganizationInvitation("
            f"id={self.id}, public_id={self.public_id}, organization_id={self.organization_id}, "
            f"invitee_email={self.invitee_email!r}, status={self.status!r})"
        )
