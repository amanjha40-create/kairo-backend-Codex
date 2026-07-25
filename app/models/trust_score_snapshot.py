"""Versioned, explainable Trust Score calculation snapshots."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class TrustScoreSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable-ish audit record for a calculated Version 1 score."""

    __tablename__ = "trust_score_snapshots"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    score_version: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    overall_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verification_completeness_percentage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    domain_scores: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    positive_contributors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    negative_contributors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    critical_overrides: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    manual_review_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
