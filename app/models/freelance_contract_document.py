"""Documents attached to a freelance contract record."""

from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class FreelanceContractDocument(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "freelance_contract_documents"

    freelance_contract_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("freelance_contracts.id", ondelete="CASCADE"), index=True, nullable=False)
    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    document_type: Mapped[str] = mapped_column(String(48), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(48), nullable=False, default="pending_review")

    def __repr__(self) -> str:
        return f"FreelanceContractDocument(id={self.id}, freelance_contract_id={self.freelance_contract_id})"
