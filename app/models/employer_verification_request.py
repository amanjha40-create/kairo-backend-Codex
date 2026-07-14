"""Employer confirmation request — magic-link verification without document upload."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.employment.enums import EmployerVerificationDecision

if TYPE_CHECKING:
    from app.models.employment import Employment


class EmployerVerificationRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Outbound employer confirmation — one active row per employment case."""

    __tablename__ = "employer_verification_requests"

    public_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
        unique=True,
        index=True,
        nullable=False,
    )

    employment_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("employments.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    verification_request_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("verification_requests.id", ondelete="RESTRICT"),
        unique=True,
        index=True,
        nullable=True,
    )
    contact_name: Mapped[str] = mapped_column(String(255), nullable=False)
    verifier_email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    relationship_to_subject: Mapped[str] = mapped_column(String(128), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=EmployerVerificationDecision.PENDING.value,
    )
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    employment: Mapped["Employment"] = relationship("Employment", back_populates="employer_verification_request")
