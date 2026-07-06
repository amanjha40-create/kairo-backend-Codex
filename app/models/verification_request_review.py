"""Verification request admin review cycle model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.db.pg_enums import verification_request_review_status_enum
from app.admin_review.enums import VerificationRequestReviewStatus

if TYPE_CHECKING:
    from app.models.verification_request import VerificationRequest
    from app.models.verification_review_correction import VerificationReviewCorrection
    from app.models.verification_review_note import VerificationReviewNote


class VerificationRequestReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One admin review cycle for a verification request."""

    __tablename__ = "verification_request_reviews"

    public_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, default=uuid.uuid4, unique=True)
    verification_request_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("verification_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    review_round: Mapped[int] = mapped_column(Integer, nullable=False)
    review_status: Mapped[VerificationRequestReviewStatus] = mapped_column(
        verification_request_review_status_enum,
        nullable=False,
    )
    assigned_reviewer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    assigned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    decision_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    verification_request: Mapped["VerificationRequest"] = relationship(
        "VerificationRequest",
        back_populates="reviews",
    )
    notes: Mapped[list["VerificationReviewNote"]] = relationship(
        "VerificationReviewNote",
        back_populates="review",
        cascade="all, delete-orphan",
        order_by="VerificationReviewNote.created_at.asc()",
    )
    corrections: Mapped[list["VerificationReviewCorrection"]] = relationship(
        "VerificationReviewCorrection",
        back_populates="review",
        cascade="all, delete-orphan",
        order_by="VerificationReviewCorrection.created_at.asc()",
    )
