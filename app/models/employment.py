"""Employment case — one verification request for a subject's employment period."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.pg_enums import employment_type_enum, verification_status_enum
from app.employment.enums import EmploymentType, VerificationMethod, VerificationStatus

if TYPE_CHECKING:
    from app.models.employer_verification_request import EmployerVerificationRequest
    from app.models.employment_document import EmploymentDocument
    from app.models.verification_audit import VerificationAuditEvent


class Employment(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A single verifiable employment period with workflow state and reviewer metadata."""

    __tablename__ = "employments"
    __table_args__ = (
        CheckConstraint(
            "end_date IS NULL OR start_date <= end_date",
            name="ck_employments_start_before_end",
        ),
    )

    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    subject_full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    subject_email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    employer_legal_name: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    employer_trade_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    job_title: Mapped[str] = mapped_column(String(255), nullable=False)
    employment_type: Mapped[str] = mapped_column(
        employment_type_enum,
        nullable=False,
        default=EmploymentType.FULL_TIME.value,
        index=True,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    work_location_country: Mapped[str] = mapped_column(String(2), nullable=False)
    work_location_region: Mapped[str | None] = mapped_column(String(128), nullable=True)
    verification_method: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=VerificationMethod.DOCUMENT.value,
        index=True,
    )

    verification_status: Mapped[str] = mapped_column(
        verification_status_enum,
        nullable=False,
        default=VerificationStatus.DRAFT.value,
        index=True,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    assigned_reviewer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewer_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    pending_info_request: Mapped[str | None] = mapped_column(Text, nullable=True)

    extraction_preview: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    employer_verification_request: Mapped["EmployerVerificationRequest | None"] = relationship(
        "EmployerVerificationRequest",
        back_populates="employment",
        uselist=False,
        cascade="all, delete-orphan",
    )
    documents: Mapped[list["EmploymentDocument"]] = relationship(
        "EmploymentDocument",
        back_populates="employment",
        cascade="all, delete-orphan",
    )
    audit_events: Mapped[list["VerificationAuditEvent"]] = relationship(
        "VerificationAuditEvent",
        back_populates="employment",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"Employment(id={self.id}, status={self.verification_status!r})"
