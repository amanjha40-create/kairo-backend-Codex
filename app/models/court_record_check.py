"""Truthfully scoped court-record searches and private evidence associations."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class CourtRecordCheck(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "court_record_checks"

    public_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, default=uuid.uuid4, unique=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    organization_person_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organization_people.id", ondelete="CASCADE"), index=True
    )
    subject_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    searched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    jurisdiction: Mapped[str] = mapped_column(String(255), nullable=False)
    coverage: Mapped[str] = mapped_column(String(1000), nullable=False)
    search_period: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(String(512), nullable=False)
    finding: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    limitations: Mapped[str] = mapped_column(String(2000), nullable=False)
    reviewer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)

    evidence_items: Mapped[list["CourtRecordCheckEvidence"]] = relationship(
        "CourtRecordCheckEvidence", back_populates="check", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_court_record_checks_organization_id_idempotency_key",
        ),
    )


class CourtRecordCheckEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "court_record_check_evidence"
    __table_args__ = (
        UniqueConstraint(
            "court_record_check_id",
            "document_id",
            name="uq_court_record_check_evidence_check_document",
        ),
    )

    court_record_check_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("court_record_checks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("user_documents.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    attached_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    check: Mapped["CourtRecordCheck"] = relationship(
        "CourtRecordCheck", back_populates="evidence_items"
    )
