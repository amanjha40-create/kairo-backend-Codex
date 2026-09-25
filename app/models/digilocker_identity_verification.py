"""File-free, Candidate-owned identity consent and latest verification provenance."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class DigiLockerIdentityVerification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "digilocker_identity_verifications"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "document_type",
            "provider_reference_fingerprint",
            name="uq_digilocker_identity_document",
        ),
        CheckConstraint("document_type IN ('PANCR','DRVLC')", name="document_type"),
        CheckConstraint("source = 'digilocker' AND source_type = 'issued_document'", name="source"),
        CheckConstraint(
            "consent_purpose = 'identity_verification' AND consent_version = 'v1'", name="consent"
        ),
        CheckConstraint("integrity_result IN ('verified','failed')", name="integrity"),
        CheckConstraint(
            "match_result IN ('VERIFIED_MATCH','PARTIAL_MATCH','MISMATCH','UNABLE_TO_VERIFY')",
            name="match_result",
        ),
        CheckConstraint(
            "(match_result = 'VERIFIED_MATCH' AND verified_at IS NOT NULL "
            "AND integrity_result = 'verified') OR "
            "(match_result != 'VERIFIED_MATCH' AND verified_at IS NULL)",
            name="verified_result",
        ),
        CheckConstraint("provider_reference_fingerprint ~ '^[0-9a-f]{64}$'", name="fingerprint"),
        CheckConstraint(
            "match_reason IS NULL OR match_reason IN ('NAME_MISMATCH','DOB_MISMATCH',"
            "'NAME_AND_DOB_MISMATCH','REQUIRED_FIELD_MISSING','OTHER',"
            "'NAME_EXACT_MATCH','FIRST_LAST_MATCH_MIDDLE_IGNORED')",
            name="match_reason",
        ),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source_connection_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("digilocker_connections.id", ondelete="SET NULL"), index=True
    )
    source: Mapped[str] = mapped_column(String(16), default="digilocker")
    source_type: Mapped[str] = mapped_column(String(24), default="issued_document")
    document_type: Mapped[str] = mapped_column(String(8))
    issuer_id: Mapped[str | None] = mapped_column(String(128))
    issuer_name: Mapped[str | None] = mapped_column(String(512))
    provider_reference_fingerprint: Mapped[str] = mapped_column(String(64))
    consent_purpose: Mapped[str] = mapped_column(String(32))
    consent_version: Mapped[str] = mapped_column(String(8))
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    integrity_result: Mapped[str] = mapped_column(String(16))
    match_result: Mapped[str] = mapped_column(String(24))
    match_reason: Mapped[str | None] = mapped_column(String(32))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    document_valid_until: Mapped[date | None] = mapped_column(Date)
    # No name/DOB snapshot. Any profile edit requires a new match before a current badge.
    profile_revision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def __repr__(self):
        return "<DigiLockerIdentityVerification>"
