"""Independent, immutable selected-file shares. No Passport permissions."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import UUIDPrimaryKeyMixin


class DocumentSharePack(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "document_share_packs"
    __table_args__ = (
        CheckConstraint("char_length(trim(purpose)) BETWEEN 1 AND 120", name="purpose_length"),
        CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        CheckConstraint("view_count >= 0", name="nonnegative_views"),
        Index("ix_document_share_packs_owner_created", "owner_user_id", "created_at"),
    )

    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), default=uuid.uuid4, unique=True
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(String(120))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    view_count: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    items: Mapped[list[DocumentSharePackItem]] = relationship(
        back_populates="pack",
        cascade="all, delete-orphan",
        lazy="raise",
    )


class DocumentSharePackItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "document_share_pack_items"
    __table_args__ = (
        UniqueConstraint("pack_id", "source_type", "source_id", name="uq_pack_source"),
        CheckConstraint(
            "source_type IN ('vault','employment','education','certification','portfolio')",
            name="source_type",
        ),
        CheckConstraint("byte_size > 0 AND byte_size <= 52428800", name="file_size"),
    )

    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), default=uuid.uuid4, unique=True
    )
    pack_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_share_packs.id", ondelete="CASCADE"), index=True
    )
    source_type: Mapped[str] = mapped_column(String(32))
    # Historical provenance, deliberately not cascading with source detach/deletion.
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    category: Mapped[str] = mapped_column(String(48))
    title: Mapped[str] = mapped_column(String(512))
    context: Mapped[str | None] = mapped_column(String(512))
    filename: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(128))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    object_key: Mapped[str] = mapped_column(String(1024), index=True)
    object_version: Mapped[str | None] = mapped_column(String(1024))
    object_etag: Mapped[str] = mapped_column(String(128))
    owns_snapshot: Mapped[bool] = mapped_column(Boolean, default=False)
    cleaned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    pack: Mapped[DocumentSharePack] = relationship(back_populates="items")
