"""One requester connection per Candidate; UUID id also identifies the encryption context."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class DigiLockerConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "digilocker_connections"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_digilocker_connections_user_id"),
        CheckConstraint(
            "status IN ('pending','active','reconnect_required','disconnected')", name="status"
        ),
        CheckConstraint(
            "status != 'active' OR (encrypted_access_token IS NOT NULL "
            "AND token_expires_at IS NOT NULL AND connected_at IS NOT NULL)",
            name="active_token",
        ),
        CheckConstraint(
            "status = 'active' OR (encrypted_access_token IS NULL "
            "AND encrypted_refresh_token IS NULL)",
            name="inactive_tokens_erased",
        ),
        CheckConstraint(
            "encrypted_access_token IS NULL OR jsonb_typeof(encrypted_access_token) = 'object'",
            name="access_envelope",
        ),
        CheckConstraint(
            "encrypted_refresh_token IS NULL OR jsonb_typeof(encrypted_refresh_token) = 'object'",
            name="refresh_envelope",
        ),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    encrypted_access_token: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    encrypted_refresh_token: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consent_valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    granted_scopes: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    pending_attempt_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    pending_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self):
        return "<DigiLockerConnection>"
