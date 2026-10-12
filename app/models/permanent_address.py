"""Versioned private address targets and derived evidence; no raw GPS samples."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class PermanentAddressVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "permanent_address_versions"
    __table_args__ = (
        UniqueConstraint("user_id", "version"),
        CheckConstraint("version > 0 AND cycle > 0", name="positive_versions"),
        CheckConstraint(
            "target_source IN ('provider_geocode', 'onsite_confirmation')",
            name="target_source_allowed",
        ),
        CheckConstraint(
            "target_status IN ('active', 'confirmation_required', 'needs_review', 'superseded')",
            name="target_status_allowed",
        ),
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    claimed_address: Mapped[dict] = mapped_column(JSONB)
    address_hash: Mapped[str] = mapped_column(String(64))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    geocode_status: Mapped[str] = mapped_column(String(32), default="REQUESTED")
    target_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    target_key_id: Mapped[str | None] = mapped_column(String(64))
    target_source: Mapped[str | None] = mapped_column(String(32))
    target_status: Mapped[str | None] = mapped_column(String(32))
    target_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    target_confirmation_reason: Mapped[str | None] = mapped_column(String(64))
    geocode_metadata: Mapped[dict | None] = mapped_column(JSONB)
    geocoded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    document_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user_documents.id", ondelete="SET NULL")
    )
    document_checksum: Mapped[str | None] = mapped_column(String(64))
    evidence_binding: Mapped[dict | None] = mapped_column(JSONB)
    document_status: Mapped[str] = mapped_column(String(32), default="REQUIRED")
    cycle: Mapped[int] = mapped_column(Integer, default=1)
    window_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PermanentAddressSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "permanent_address_sessions"
    __table_args__ = (
        UniqueConstraint("address_version_id", "cycle", "counted_day"),
        CheckConstraint("counted_day IS NULL OR result = 'MATCHED'", name="counted_only_matched"),
    )
    address_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("permanent_address_versions.id", ondelete="CASCADE"),
        index=True,
    )
    cycle: Mapped[int] = mapped_column(Integer)
    challenge_hash: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[str] = mapped_column(String(32), default="CHECKING")
    counted_day: Mapped[date | None] = mapped_column(Date)
    derived_evidence: Mapped[dict | None] = mapped_column(JSONB)


class PermanentAddressReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "permanent_address_reviews"
    address_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("permanent_address_versions.id", ondelete="CASCADE"),
        index=True,
    )
    reviewer_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    document_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user_documents.id", ondelete="SET NULL")
    )
    document_checksum: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(32))


class PermanentAddressGeocodeBudget(Base):
    __tablename__ = "permanent_address_geocode_budgets"
    __table_args__ = (CheckConstraint("request_count >= 0", name="nonnegative_count"),)
    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
