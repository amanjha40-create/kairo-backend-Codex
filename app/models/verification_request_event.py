"""Verification request event model."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import UUIDPrimaryKeyMixin
from app.db.pg_enums import verification_request_event_source_enum, verification_request_status_enum
from app.verification_requests.enums import VerificationRequestEventSource, VerificationRequestStatus

if TYPE_CHECKING:
    from app.models.verification_request import VerificationRequest


class VerificationRequestEvent(UUIDPrimaryKeyMixin, Base):
    """Immutable timeline event for a verification request."""

    __tablename__ = "verification_request_events"

    public_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, default=uuid.uuid4, unique=True)
    verification_request_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("verification_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    event_source: Mapped[VerificationRequestEventSource] = mapped_column(verification_request_event_source_enum, nullable=False)
    previous_status: Mapped[VerificationRequestStatus | None] = mapped_column(verification_request_status_enum, nullable=True)
    new_status: Mapped[VerificationRequestStatus | None] = mapped_column(verification_request_status_enum, nullable=True)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(tz=UTC),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    verification_request: Mapped["VerificationRequest"] = relationship("VerificationRequest", back_populates="events")

    def __repr__(self) -> str:
        return f"VerificationRequestEvent(id={self.id}, event_type={self.event_type!r})"
