"""Durable alias history for organization people."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.db.pg_enums import organization_person_identifier_type_enum
from app.organization_people.enums import OrganizationPersonIdentifierType

if TYPE_CHECKING:
    from app.models.organization_person import OrganizationPerson


class OrganizationPersonIdentifier(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Normalized email and phone aliases for deterministic resolution."""

    __tablename__ = "organization_person_identifiers"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "identifier_type",
            "normalized_value",
            name="uq_organization_person_identifiers_org_type_value",
        ),
    )

    public_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, default=uuid.uuid4, unique=True)
    organization_person_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organization_people.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    identifier_type: Mapped[OrganizationPersonIdentifierType] = mapped_column(
        organization_person_identifier_type_enum,
        nullable=False,
        index=True,
    )
    normalized_value: Mapped[str] = mapped_column(String(320), nullable=False)
    raw_value: Mapped[str | None] = mapped_column(String(320), nullable=True)
    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )

    organization_person: Mapped["OrganizationPerson"] = relationship(
        "OrganizationPerson",
        back_populates="identifiers",
    )

