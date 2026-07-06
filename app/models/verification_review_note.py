"""Verification review note model."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.admin_review.enums import VerificationReviewNoteType, VerificationReviewNoteVisibility
from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.db.pg_enums import verification_review_note_type_enum, verification_review_note_visibility_enum

if TYPE_CHECKING:
    from app.models.verification_request_review import VerificationRequestReview


class VerificationReviewNote(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only note attached to an admin review cycle."""

    __tablename__ = "verification_review_notes"

    public_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, default=uuid.uuid4, unique=True)
    verification_request_review_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("verification_request_reviews.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    visibility: Mapped[VerificationReviewNoteVisibility] = mapped_column(
        verification_review_note_visibility_enum,
        nullable=False,
    )
    note_type: Mapped[VerificationReviewNoteType] = mapped_column(
        verification_review_note_type_enum,
        nullable=False,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    review: Mapped["VerificationRequestReview"] = relationship(
        "VerificationRequestReview",
        back_populates="notes",
    )
