"""User notification preference model."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class NotificationPreference(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Per-user preference settings for notification event subscriptions."""

    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "event_type", name="uq_notification_preferences_user_id_event_type"),
    )

    public_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, default=uuid.uuid4, unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    preferred_channels: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    quiet_hours: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    def __repr__(self) -> str:
        return f"NotificationPreference(id={self.id}, user_id={self.user_id}, event_type={self.event_type!r})"
