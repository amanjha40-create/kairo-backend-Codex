"""Versioned contact submitted for a verification request."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.db.pg_enums import verification_contact_review_status_enum, verification_contact_type_enum
from app.verification_requests.enums import VerificationContactReviewStatus, VerificationContactType

if TYPE_CHECKING:
    from app.models.verification_request import VerificationRequest


class VerificationContact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An auditable version of the person authorized to verify a subject."""

    __tablename__ = "verification_contacts"

    public_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    verification_request_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("verification_requests.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_email: Mapped[str] = mapped_column(String(320), index=True, nullable=False)
    contact_role: Mapped[str | None] = mapped_column(String(128), nullable=True)
    contact_type: Mapped[VerificationContactType] = mapped_column(verification_contact_type_enum, nullable=False)
    candidate_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_by_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    review_status: Mapped[VerificationContactReviewStatus] = mapped_column(
        verification_contact_review_status_enum,
        default=VerificationContactReviewStatus.PENDING,
        nullable=False,
    )
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    verification_request: Mapped["VerificationRequest"] = relationship(
        "VerificationRequest",
        back_populates="verification_contacts",
    )
