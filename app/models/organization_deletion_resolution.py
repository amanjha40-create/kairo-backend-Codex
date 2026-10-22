"""Non-content audit of ownership resolution during personal account erasure."""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class OrganizationDeletionResolution(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organization_deletion_resolutions"
    __table_args__ = (
        UniqueConstraint("deletion_id", "organization_id", name="uq_org_deletion_resolution"),
        CheckConstraint("action IN ('leave', 'transfer', 'close')", name="action"),
        CheckConstraint(
            "(action = 'transfer') = (successor_user_id IS NOT NULL)", name="successor"
        ),
    )
    deletion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("account_deletions.id", ondelete="RESTRICT")
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT")
    )
    action: Mapped[str] = mapped_column(String(16))
    successor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
