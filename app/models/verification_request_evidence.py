"""Verification request evidence model."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.admin_review.enums import VerificationRequestEvidenceStatus
from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.db.pg_enums import verification_request_evidence_status_enum

if TYPE_CHECKING:
    from app.models.verification_request import VerificationRequest


class VerificationRequestEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """First-class subject-submitted evidence for a verification request."""

    __tablename__ = "verification_request_evidence"

    public_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, default=uuid.uuid4, unique=True)
    verification_request_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("verification_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    submitted_by_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    field_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("user_documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    employment_document_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("employment_documents.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[VerificationRequestEvidenceStatus] = mapped_column(
        verification_request_evidence_status_enum,
        nullable=False,
    )

    verification_request: Mapped["VerificationRequest"] = relationship(
        "VerificationRequest",
        back_populates="evidence_items",
    )
