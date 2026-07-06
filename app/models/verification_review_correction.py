"""Verification review correction request model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.admin_review.enums import VerificationReviewCorrectionStatus
from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.db.pg_enums import verification_review_correction_status_enum

if TYPE_CHECKING:
    from app.models.verification_request_evidence import VerificationRequestEvidence
    from app.models.verification_request_review import VerificationRequestReview


class VerificationReviewCorrection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Structured correction request raised during admin review."""

    __tablename__ = "verification_review_corrections"

    public_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, default=uuid.uuid4, unique=True)
    verification_request_review_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("verification_request_reviews.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    verification_request_evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("verification_request_evidence.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[VerificationReviewCorrectionStatus] = mapped_column(
        verification_review_correction_status_enum,
        nullable=False,
    )
    field_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    request_text: Mapped[str] = mapped_column(Text, nullable=False)
    guidance: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    review: Mapped["VerificationRequestReview"] = relationship(
        "VerificationRequestReview",
        back_populates="corrections",
    )
    evidence_item: Mapped["VerificationRequestEvidence | None"] = relationship("VerificationRequestEvidence")
