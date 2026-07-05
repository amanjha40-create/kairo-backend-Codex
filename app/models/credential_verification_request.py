"""Generic credential confirmation request — magic-link verification for non-employment credentials.

Polymorphic: one row points at any verifiable subject (internship, freelance contract)
via (subject_type, subject_id). No FK because the target table varies by subject_type.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.employment.enums import EmployerVerificationDecision


class CredentialVerificationRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Outbound credential confirmation — one active row per (subject_type, subject_id)."""

    __tablename__ = "credential_verification_requests"
    __table_args__ = (
        UniqueConstraint("subject_type", "subject_id", name="uq_credential_verif_subject"),
    )

    subject_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    subject_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
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
