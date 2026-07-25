"""Organization-scoped passport access metadata."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.db.pg_enums import organization_person_passport_access_state_enum
from app.organization_people.enums import OrganizationPersonPassportAccessState

if TYPE_CHECKING:
    from app.models.organization_person import OrganizationPerson
    from app.models.passport_share_link import PassportShareLink
    from app.models.user import User


class OrganizationPersonPassportAccess(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Organization-specific view of a candidate-owned passport share."""

    __tablename__ = "organization_person_passport_access"
    __table_args__ = (
        UniqueConstraint(
            "organization_person_id",
            "passport_share_link_id",
            name="uq_organization_person_passport_access_person_share",
        ),
    )

    public_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, default=uuid.uuid4, unique=True)
    organization_person_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organization_people.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    passport_share_link_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("passport_share_links.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    access_state: Mapped[OrganizationPersonPassportAccessState] = mapped_column(
        organization_person_passport_access_state_enum,
        nullable=False,
        default=OrganizationPersonPassportAccessState.ACTIVE,
        server_default=OrganizationPersonPassportAccessState.ACTIVE.value,
        index=True,
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        index=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    permissions_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    granted_via_source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    granted_via_source_public_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    organization_person: Mapped["OrganizationPerson"] = relationship(
        "OrganizationPerson",
        back_populates="passport_access_entries",
    )
    passport_share_link: Mapped["PassportShareLink"] = relationship("PassportShareLink")
    owner_user: Mapped["User"] = relationship("User")
