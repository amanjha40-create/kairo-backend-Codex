"""Introduce the organization person registry.

Revision ID: 053
Revises: 052
Create Date: 2026-07-24
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.organization_people.enums import (
    OrganizationPersonIdentifierType,
    OrganizationPersonInvitationStatusSummary,
    OrganizationPersonLifecycleStatus,
    OrganizationPersonPassportAccessState,
    OrganizationPersonPassportStatusSummary,
    OrganizationPersonRelationship,
    OrganizationPersonTrustState,
    OrganizationPersonVerificationStatusSummary,
)

revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None


def _enum(name: str, members: tuple[str, ...]) -> postgresql.ENUM:
    return postgresql.ENUM(*members, name=name, create_type=False)


def _normalize_email(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def _normalize_phone(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = "".join(ch for ch in value.strip() if ch.isdigit() or ch == "+")
    return normalized or None


def _relationship_from_employment(row) -> str:  # noqa: ANN001
    employment_type = str(row["employment_type"] or "")
    today = datetime.now(tz=UTC).date()
    if row["end_date"] is not None and row["end_date"] < today:
        return OrganizationPersonRelationship.FORMER_EMPLOYEE.value
    if employment_type in {"contract", "freelance", "gig"}:
        return OrganizationPersonRelationship.CONTRACTOR.value
    return OrganizationPersonRelationship.EMPLOYEE.value


def _merge_relationship(current: str | None, incoming: str) -> str:
    priority = {
        OrganizationPersonRelationship.CANDIDATE.value: 1,
        OrganizationPersonRelationship.FUTURE_EMPLOYEE.value: 2,
        OrganizationPersonRelationship.CONTRACTOR.value: 3,
        OrganizationPersonRelationship.EMPLOYEE.value: 4,
        OrganizationPersonRelationship.FORMER_EMPLOYEE.value: 5,
    }
    if current is None:
        return incoming
    return incoming if priority[incoming] >= priority[current] else current


def _ensure_identifier(
    bind,
    identifier_table,
    *,
    organization_person_id,
    organization_id,
    identifier_type: str,
    normalized_value: str,
    raw_value: str | None,
    is_primary: bool,
) -> None:
    existing = bind.execute(
        sa.select(identifier_table.c.id).where(
            identifier_table.c.organization_person_id == organization_person_id,
            identifier_table.c.identifier_type == identifier_type,
            identifier_table.c.normalized_value == normalized_value,
        )
    ).first()
    if existing is not None:
        bind.execute(
            sa.update(identifier_table)
            .where(identifier_table.c.id == existing.id)
            .values(raw_value=raw_value, is_primary=is_primary or identifier_table.c.is_primary)
        )
        return
    bind.execute(
        sa.insert(identifier_table).values(
            id=uuid4(),
            public_id=uuid4(),
            organization_person_id=organization_person_id,
            organization_id=organization_id,
            identifier_type=identifier_type,
            normalized_value=normalized_value,
            raw_value=raw_value,
            is_primary=is_primary,
        )
    )


def _build_resolution_metadata(*, source_type: str, source_public_id, actor_user_id) -> dict[str, str]:
    payload = {
        "source_type": source_type,
        "source_public_id": str(source_public_id),
    }
    if actor_user_id is not None:
        payload["actor_user_id"] = str(actor_user_id)
    return payload


def _resolve_person(
    bind,
    person_table,
    identifier_table,
    *,
    organization_id,
    existing_person_id,
    linked_user_id,
    full_name: str,
    email: str | None,
    phone: str | None,
    relationship: str,
    added_by_user_id,
    added_at,
    last_activity_at,
    source_type: str,
    source_public_id,
    actor_user_id,
):
    normalized_email = _normalize_email(email)
    normalized_phone = _normalize_phone(phone)
    person = None
    resolution_method = "created"
    confidence = Decimal("0.70")

    if existing_person_id is not None:
        person = bind.execute(
            sa.select(person_table).where(person_table.c.id == existing_person_id)
        ).mappings().first()
        if person is not None:
            resolution_method = "existing_link"
            confidence = Decimal("1.00")

    if person is None and linked_user_id is not None:
        person = bind.execute(
            sa.select(person_table).where(
                person_table.c.organization_id == organization_id,
                person_table.c.linked_user_id == linked_user_id,
            )
        ).mappings().first()
        if person is not None:
            resolution_method = "linked_user"
            confidence = Decimal("1.00")

    if person is None and normalized_email is not None:
        person = bind.execute(
            sa.select(person_table).where(
                person_table.c.organization_id == organization_id,
                person_table.c.primary_email == normalized_email,
            )
        ).mappings().first()
        if person is None:
            person = bind.execute(
                sa.select(person_table)
                .join(identifier_table, identifier_table.c.organization_person_id == person_table.c.id)
                .where(
                    person_table.c.organization_id == organization_id,
                    identifier_table.c.organization_id == organization_id,
                    identifier_table.c.identifier_type == OrganizationPersonIdentifierType.EMAIL.value,
                    identifier_table.c.normalized_value == normalized_email,
                )
            ).mappings().first()
        if person is not None:
            resolution_method = "email"
            confidence = Decimal("0.95")

    if person is None and normalized_phone is not None:
        person = bind.execute(
            sa.select(person_table).where(
                person_table.c.organization_id == organization_id,
                person_table.c.primary_phone == normalized_phone,
            )
        ).mappings().first()
        if person is None:
            person = bind.execute(
                sa.select(person_table)
                .join(identifier_table, identifier_table.c.organization_person_id == person_table.c.id)
                .where(
                    person_table.c.organization_id == organization_id,
                    identifier_table.c.organization_id == organization_id,
                    identifier_table.c.identifier_type == OrganizationPersonIdentifierType.PHONE.value,
                    identifier_table.c.normalized_value == normalized_phone,
                )
            ).mappings().first()
        if person is not None:
            resolution_method = "phone"
            confidence = Decimal("0.90")

    if person is None:
        person_id = uuid4()
        bind.execute(
            sa.insert(person_table).values(
                id=person_id,
                public_id=uuid4(),
                organization_id=organization_id,
                linked_user_id=linked_user_id,
                full_name=full_name,
                primary_email=normalized_email,
                primary_phone=normalized_phone,
                relationship=relationship,
                lifecycle_status=OrganizationPersonLifecycleStatus.ACTIVE.value,
                trust_state=OrganizationPersonTrustState.UNKNOWN.value,
                invitation_status_summary=OrganizationPersonInvitationStatusSummary.NOT_INVITED.value,
                verification_status_summary=OrganizationPersonVerificationStatusSummary.NOT_STARTED.value,
                passport_status_summary=OrganizationPersonPassportStatusSummary.NOT_SHARED.value,
                added_by_user_id=added_by_user_id,
                added_at=added_at or datetime.now(tz=UTC),
                last_activity_at=last_activity_at,
                resolution_state="resolved",
                resolution_method=resolution_method,
                resolution_confidence=confidence,
                resolution_metadata=_build_resolution_metadata(
                    source_type=source_type,
                    source_public_id=source_public_id,
                    actor_user_id=actor_user_id,
                ),
            )
        )
    else:
        person_id = person["id"]
        bind.execute(
            sa.update(person_table)
            .where(person_table.c.id == person_id)
            .values(
                linked_user_id=linked_user_id if person["linked_user_id"] is None else person["linked_user_id"],
                full_name=full_name or person["full_name"],
                primary_email=normalized_email if person["primary_email"] is None else person["primary_email"],
                primary_phone=normalized_phone if person["primary_phone"] is None else person["primary_phone"],
                relationship=_merge_relationship(person["relationship"], relationship),
                added_by_user_id=person["added_by_user_id"] or added_by_user_id,
                added_at=added_at if person["added_at"] is None or (added_at is not None and added_at < person["added_at"]) else person["added_at"],
                last_activity_at=max(
                    [value for value in (person["last_activity_at"], last_activity_at) if value is not None],
                    default=person["last_activity_at"] or last_activity_at,
                ),
                resolution_state="resolved",
                resolution_method=resolution_method,
                resolution_confidence=confidence,
                resolution_metadata=_build_resolution_metadata(
                    source_type=source_type,
                    source_public_id=source_public_id,
                    actor_user_id=actor_user_id,
                ),
            )
        )

    if normalized_email is not None:
        _ensure_identifier(
            bind,
            identifier_table,
            organization_person_id=person_id,
            organization_id=organization_id,
            identifier_type=OrganizationPersonIdentifierType.EMAIL.value,
            normalized_value=normalized_email,
            raw_value=email,
            is_primary=True,
        )
    if normalized_phone is not None:
        _ensure_identifier(
            bind,
            identifier_table,
            organization_person_id=person_id,
            organization_id=organization_id,
            identifier_type=OrganizationPersonIdentifierType.PHONE.value,
            normalized_value=normalized_phone,
            raw_value=phone,
            is_primary=True,
        )
    return person_id


def _latest_invitation_status(bind, invitation_table, person_id) -> str:
    invitation = bind.execute(
        sa.select(invitation_table)
        .where(invitation_table.c.organization_person_id == person_id)
        .order_by(invitation_table.c.updated_at.desc(), invitation_table.c.created_at.desc())
        .limit(1)
    ).mappings().first()
    if invitation is None:
        return OrganizationPersonInvitationStatusSummary.NOT_INVITED.value
    status = invitation["status"]
    if status == "pending" and invitation["opened_at"] is not None:
        return OrganizationPersonInvitationStatusSummary.OPENED.value
    return {
        "draft": OrganizationPersonInvitationStatusSummary.DRAFT.value,
        "pending": OrganizationPersonInvitationStatusSummary.SENT.value,
        "accepted": OrganizationPersonInvitationStatusSummary.ACCEPTED.value,
        "expired": OrganizationPersonInvitationStatusSummary.EXPIRED.value,
        "cancelled": OrganizationPersonInvitationStatusSummary.CANCELLED.value,
    }.get(status, OrganizationPersonInvitationStatusSummary.NOT_INVITED.value)


def _latest_verification_status(bind, verification_table, person_id) -> str:
    request = bind.execute(
        sa.select(verification_table)
        .where(verification_table.c.organization_person_id == person_id)
        .order_by(verification_table.c.updated_at.desc(), verification_table.c.created_at.desc())
        .limit(1)
    ).mappings().first()
    if request is None:
        return OrganizationPersonVerificationStatusSummary.NOT_STARTED.value
    return {
        "draft": OrganizationPersonVerificationStatusSummary.NOT_STARTED.value,
        "pending_subject_acceptance": OrganizationPersonVerificationStatusSummary.WAITING_FOR_CANDIDATE.value,
        "pending_subject_submission": OrganizationPersonVerificationStatusSummary.WAITING_FOR_CANDIDATE.value,
        "pending_admin_review": OrganizationPersonVerificationStatusSummary.IN_VERIFICATION.value,
        "awaiting_subject_corrections": OrganizationPersonVerificationStatusSummary.CLARIFICATION_REQUIRED.value,
        "pending_admin_re_review": OrganizationPersonVerificationStatusSummary.IN_VERIFICATION.value,
        "approved_for_organization_verification": OrganizationPersonVerificationStatusSummary.IN_VERIFICATION.value,
        "pending_organization_resolution": OrganizationPersonVerificationStatusSummary.IN_VERIFICATION.value,
        "pending_organization_acceptance": OrganizationPersonVerificationStatusSummary.IN_VERIFICATION.value,
        "in_progress": OrganizationPersonVerificationStatusSummary.IN_VERIFICATION.value,
        "awaiting_information": OrganizationPersonVerificationStatusSummary.CLARIFICATION_REQUIRED.value,
        "verified": OrganizationPersonVerificationStatusSummary.COMPLETED.value,
        "rejected": OrganizationPersonVerificationStatusSummary.UNABLE_TO_VERIFY.value,
        "cancelled": OrganizationPersonVerificationStatusSummary.CANCELLED.value,
        "expired": OrganizationPersonVerificationStatusSummary.UNABLE_TO_VERIFY.value,
    }.get(request["status"], OrganizationPersonVerificationStatusSummary.NOT_STARTED.value)


def _derive_trust_state(
    invitation_status: str,
    verification_status: str,
    passport_status: str,
) -> str:
    if passport_status == OrganizationPersonPassportStatusSummary.ACCESS_REVOKED.value:
        return OrganizationPersonTrustState.REVOKED.value
    if verification_status == OrganizationPersonVerificationStatusSummary.COMPLETED.value:
        return OrganizationPersonTrustState.VERIFIED.value
    if passport_status in {
        OrganizationPersonPassportStatusSummary.ACTIVE.value,
        OrganizationPersonPassportStatusSummary.EXPIRING_SOON.value,
        OrganizationPersonPassportStatusSummary.EXPIRED.value,
    } or invitation_status == OrganizationPersonInvitationStatusSummary.ACCEPTED.value:
        return OrganizationPersonTrustState.PARTIALLY_VERIFIED.value
    if invitation_status in {
        OrganizationPersonInvitationStatusSummary.DRAFT.value,
        OrganizationPersonInvitationStatusSummary.SENT.value,
        OrganizationPersonInvitationStatusSummary.OPENED.value,
    } or verification_status in {
        OrganizationPersonVerificationStatusSummary.WAITING_FOR_CANDIDATE.value,
        OrganizationPersonVerificationStatusSummary.IN_VERIFICATION.value,
        OrganizationPersonVerificationStatusSummary.CLARIFICATION_REQUIRED.value,
    }:
        return OrganizationPersonTrustState.PENDING.value
    return OrganizationPersonTrustState.UNKNOWN.value


def upgrade() -> None:
    bind = op.get_bind()

    relationship_enum = _enum(
        "organization_person_relationship_enum",
        tuple(member.value for member in OrganizationPersonRelationship),
    )
    lifecycle_enum = _enum(
        "organization_person_lifecycle_status_enum",
        tuple(member.value for member in OrganizationPersonLifecycleStatus),
    )
    trust_state_enum = _enum(
        "organization_person_trust_state_enum",
        tuple(member.value for member in OrganizationPersonTrustState),
    )
    invitation_summary_enum = _enum(
        "organization_person_invitation_status_summary_enum",
        tuple(member.value for member in OrganizationPersonInvitationStatusSummary),
    )
    verification_summary_enum = _enum(
        "organization_person_verification_status_summary_enum",
        tuple(member.value for member in OrganizationPersonVerificationStatusSummary),
    )
    passport_summary_enum = _enum(
        "organization_person_passport_status_summary_enum",
        tuple(member.value for member in OrganizationPersonPassportStatusSummary),
    )
    passport_access_enum = _enum(
        "organization_person_passport_access_state_enum",
        tuple(member.value for member in OrganizationPersonPassportAccessState),
    )
    identifier_type_enum = _enum(
        "organization_person_identifier_type_enum",
        tuple(member.value for member in OrganizationPersonIdentifierType),
    )
    for enum in (
        relationship_enum,
        lifecycle_enum,
        trust_state_enum,
        invitation_summary_enum,
        verification_summary_enum,
        passport_summary_enum,
        passport_access_enum,
        identifier_type_enum,
    ):
        enum.create(bind, checkfirst=True)

    op.create_table(
        "organization_people",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("linked_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("primary_email", sa.String(length=320), nullable=True),
        sa.Column("primary_phone", sa.String(length=32), nullable=True),
        sa.Column("relationship", relationship_enum, nullable=False, server_default=OrganizationPersonRelationship.CANDIDATE.value),
        sa.Column("lifecycle_status", lifecycle_enum, nullable=False, server_default=OrganizationPersonLifecycleStatus.ACTIVE.value),
        sa.Column("trust_state", trust_state_enum, nullable=False, server_default=OrganizationPersonTrustState.UNKNOWN.value),
        sa.Column(
            "invitation_status_summary",
            invitation_summary_enum,
            nullable=False,
            server_default=OrganizationPersonInvitationStatusSummary.NOT_INVITED.value,
        ),
        sa.Column(
            "verification_status_summary",
            verification_summary_enum,
            nullable=False,
            server_default=OrganizationPersonVerificationStatusSummary.NOT_STARTED.value,
        ),
        sa.Column(
            "passport_status_summary",
            passport_summary_enum,
            nullable=False,
            server_default=OrganizationPersonPassportStatusSummary.NOT_SHARED.value,
        ),
        sa.Column("added_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_state", sa.String(length=32), nullable=False, server_default="unresolved"),
        sa.Column("resolution_method", sa.String(length=32), nullable=True),
        sa.Column("resolution_confidence", sa.Numeric(5, 2), nullable=True),
        sa.Column("resolution_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["linked_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["added_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_people")),
        sa.UniqueConstraint("public_id", name=op.f("uq_organization_people_public_id")),
        sa.UniqueConstraint(
            "organization_id",
            "linked_user_id",
            name="uq_organization_people_organization_id_linked_user_id",
        ),
    )
    op.create_index(op.f("ix_organization_people_organization_id"), "organization_people", ["organization_id"])
    op.create_index(op.f("ix_organization_people_linked_user_id"), "organization_people", ["linked_user_id"])
    op.create_index(op.f("ix_organization_people_primary_email"), "organization_people", ["primary_email"])
    op.create_index(op.f("ix_organization_people_primary_phone"), "organization_people", ["primary_phone"])
    op.create_index(op.f("ix_organization_people_added_by_user_id"), "organization_people", ["added_by_user_id"])
    op.create_index(op.f("ix_organization_people_added_at"), "organization_people", ["added_at"])
    op.create_index(op.f("ix_organization_people_last_activity_at"), "organization_people", ["last_activity_at"])
    op.create_index(op.f("ix_organization_people_lifecycle_status"), "organization_people", ["lifecycle_status"])
    op.create_index(op.f("ix_organization_people_trust_state"), "organization_people", ["trust_state"])
    op.create_index(op.f("ix_organization_people_invitation_status_summary"), "organization_people", ["invitation_status_summary"])
    op.create_index(op.f("ix_organization_people_verification_status_summary"), "organization_people", ["verification_status_summary"])
    op.create_index(op.f("ix_organization_people_passport_status_summary"), "organization_people", ["passport_status_summary"])

    op.create_table(
        "organization_person_identifiers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("identifier_type", identifier_type_enum, nullable=False),
        sa.Column("normalized_value", sa.String(length=320), nullable=False),
        sa.Column("raw_value", sa.String(length=320), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_person_id"], ["organization_people.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_person_identifiers")),
        sa.UniqueConstraint("public_id", name=op.f("uq_organization_person_identifiers_public_id")),
        sa.UniqueConstraint(
            "organization_id",
            "identifier_type",
            "normalized_value",
            name="uq_organization_person_identifiers_org_type_value",
        ),
    )
    op.create_index(op.f("ix_organization_person_identifiers_organization_person_id"), "organization_person_identifiers", ["organization_person_id"])
    op.create_index(op.f("ix_organization_person_identifiers_organization_id"), "organization_person_identifiers", ["organization_id"])
    op.create_index(op.f("ix_organization_person_identifiers_identifier_type"), "organization_person_identifiers", ["identifier_type"])

    op.create_table(
        "organization_person_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_person_id"], ["organization_people.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_person_notes")),
        sa.UniqueConstraint("public_id", name=op.f("uq_organization_person_notes_public_id")),
    )
    op.create_index(op.f("ix_organization_person_notes_organization_person_id"), "organization_person_notes", ["organization_person_id"])
    op.create_index(op.f("ix_organization_person_notes_author_user_id"), "organization_person_notes", ["author_user_id"])

    op.create_table(
        "organization_person_passport_access",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("passport_share_link_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("access_state", passport_access_enum, nullable=False, server_default=OrganizationPersonPassportAccessState.ACTIVE.value),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("permissions_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("granted_via_source_type", sa.String(length=64), nullable=True),
        sa.Column("granted_via_source_public_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_person_id"], ["organization_people.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["passport_share_link_id"], ["passport_share_links.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_person_passport_access")),
        sa.UniqueConstraint("public_id", name=op.f("uq_organization_person_passport_access_public_id")),
        sa.UniqueConstraint(
            "organization_person_id",
            "passport_share_link_id",
            name="uq_organization_person_passport_access_person_share",
        ),
    )
    op.create_index(op.f("ix_organization_person_passport_access_organization_person_id"), "organization_person_passport_access", ["organization_person_id"])
    op.create_index(op.f("ix_organization_person_passport_access_passport_share_link_id"), "organization_person_passport_access", ["passport_share_link_id"])
    op.create_index(op.f("ix_organization_person_passport_access_owner_user_id"), "organization_person_passport_access", ["owner_user_id"])
    op.create_index(op.f("ix_organization_person_passport_access_access_state"), "organization_person_passport_access", ["access_state"])
    op.create_index(op.f("ix_organization_person_passport_access_granted_at"), "organization_person_passport_access", ["granted_at"])
    op.create_index(op.f("ix_organization_person_passport_access_expires_at"), "organization_person_passport_access", ["expires_at"])
    op.create_index(op.f("ix_organization_person_passport_access_revoked_at"), "organization_person_passport_access", ["revoked_at"])

    op.add_column(
        "trust_invitations",
        sa.Column("organization_person_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "verification_requests",
        sa.Column("organization_person_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "employments",
        sa.Column("organization_person_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_trust_invitations_organization_person_id_organization_people"),
        "trust_invitations",
        "organization_people",
        ["organization_person_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_verification_requests_organization_person_id_organization_people"),
        "verification_requests",
        "organization_people",
        ["organization_person_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_employments_organization_person_id_organization_people"),
        "employments",
        "organization_people",
        ["organization_person_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_trust_invitations_organization_person_id"), "trust_invitations", ["organization_person_id"])
    op.create_index(op.f("ix_verification_requests_organization_person_id"), "verification_requests", ["organization_person_id"])
    op.create_index(op.f("ix_employments_organization_person_id"), "employments", ["organization_person_id"])

    person_table = sa.table(
        "organization_people",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("public_id", postgresql.UUID(as_uuid=True)),
        sa.column("organization_id", postgresql.UUID(as_uuid=True)),
        sa.column("linked_user_id", postgresql.UUID(as_uuid=True)),
        sa.column("full_name", sa.String()),
        sa.column("primary_email", sa.String()),
        sa.column("primary_phone", sa.String()),
        sa.column("relationship", sa.String()),
        sa.column("lifecycle_status", sa.String()),
        sa.column("trust_state", sa.String()),
        sa.column("invitation_status_summary", sa.String()),
        sa.column("verification_status_summary", sa.String()),
        sa.column("passport_status_summary", sa.String()),
        sa.column("added_by_user_id", postgresql.UUID(as_uuid=True)),
        sa.column("added_at", sa.DateTime(timezone=True)),
        sa.column("last_activity_at", sa.DateTime(timezone=True)),
        sa.column("resolution_state", sa.String()),
        sa.column("resolution_method", sa.String()),
        sa.column("resolution_confidence", sa.Numeric()),
        sa.column("resolution_metadata", postgresql.JSONB(astext_type=sa.Text())),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    identifier_table = sa.table(
        "organization_person_identifiers",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("public_id", postgresql.UUID(as_uuid=True)),
        sa.column("organization_person_id", postgresql.UUID(as_uuid=True)),
        sa.column("organization_id", postgresql.UUID(as_uuid=True)),
        sa.column("identifier_type", sa.String()),
        sa.column("normalized_value", sa.String()),
        sa.column("raw_value", sa.String()),
        sa.column("is_primary", sa.Boolean()),
    )
    invitation_table = sa.table(
        "trust_invitations",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("public_id", postgresql.UUID(as_uuid=True)),
        sa.column("organization_id", postgresql.UUID(as_uuid=True)),
        sa.column("organization_person_id", postgresql.UUID(as_uuid=True)),
        sa.column("subject_name", sa.String()),
        sa.column("subject_email", sa.String()),
        sa.column("subject_phone", sa.String()),
        sa.column("status", sa.String()),
        sa.column("created_by_user_id", postgresql.UUID(as_uuid=True)),
        sa.column("accepted_by_user_id", postgresql.UUID(as_uuid=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("sent_at", sa.DateTime(timezone=True)),
        sa.column("opened_at", sa.DateTime(timezone=True)),
        sa.column("accepted_at", sa.DateTime(timezone=True)),
        sa.column("cancelled_at", sa.DateTime(timezone=True)),
    )
    verification_table = sa.table(
        "verification_requests",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("public_id", postgresql.UUID(as_uuid=True)),
        sa.column("organization_id", postgresql.UUID(as_uuid=True)),
        sa.column("organization_person_id", postgresql.UUID(as_uuid=True)),
        sa.column("subject_user_id", postgresql.UUID(as_uuid=True)),
        sa.column("trust_invitation_id", postgresql.UUID(as_uuid=True)),
        sa.column("employment_id", postgresql.UUID(as_uuid=True)),
        sa.column("subject_name", sa.String()),
        sa.column("subject_email", sa.String()),
        sa.column("requested_by_user_id", postgresql.UUID(as_uuid=True)),
        sa.column("status", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("accepted_at", sa.DateTime(timezone=True)),
        sa.column("candidate_response_submitted_at", sa.DateTime(timezone=True)),
    )
    employment_table = sa.table(
        "employments",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("organization_person_id", postgresql.UUID(as_uuid=True)),
        sa.column("created_by_user_id", postgresql.UUID(as_uuid=True)),
        sa.column("subject_full_name", sa.String()),
        sa.column("subject_email", sa.String()),
        sa.column("employment_type", sa.String()),
        sa.column("start_date", sa.Date()),
        sa.column("end_date", sa.Date()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    user_table = sa.table(
        "users",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("phone", sa.String()),
    )

    user_phone_rows = bind.execute(sa.select(user_table.c.id, user_table.c.phone)).all()
    user_phones = {row.id: row.phone for row in user_phone_rows}

    invitations = bind.execute(sa.select(invitation_table).order_by(invitation_table.c.created_at.asc())).mappings().all()
    for row in invitations:
        person_id = _resolve_person(
            bind,
            person_table,
            identifier_table,
            organization_id=row["organization_id"],
            existing_person_id=row["organization_person_id"],
            linked_user_id=row["accepted_by_user_id"],
            full_name=row["subject_name"],
            email=row["subject_email"],
            phone=row["subject_phone"],
            relationship=(
                OrganizationPersonRelationship.CANDIDATE.value
                if row["accepted_by_user_id"] is not None
                else OrganizationPersonRelationship.FUTURE_EMPLOYEE.value
            ),
            added_by_user_id=row["created_by_user_id"],
            added_at=row["created_at"],
            last_activity_at=max(
                value
                for value in (
                    row["updated_at"],
                    row["sent_at"],
                    row["opened_at"],
                    row["accepted_at"],
                    row["cancelled_at"],
                    row["created_at"],
                )
                if value is not None
            ),
            source_type="trust_invitation",
            source_public_id=row["public_id"],
            actor_user_id=row["created_by_user_id"],
        )
        bind.execute(
            sa.update(invitation_table)
            .where(invitation_table.c.id == row["id"])
            .values(organization_person_id=person_id)
        )

    verification_rows = bind.execute(sa.select(verification_table).order_by(verification_table.c.created_at.asc())).mappings().all()
    invitation_person_ids = {
        row.id: row.organization_person_id
        for row in bind.execute(sa.select(invitation_table.c.id, invitation_table.c.organization_person_id)).all()
    }
    employments = {
        row.id: row
        for row in bind.execute(sa.select(employment_table)).mappings().all()
    }
    for row in verification_rows:
        if row["organization_id"] is None:
            continue
        linked_employment = employments.get(row["employment_id"]) if row["employment_id"] is not None else None
        existing_person_id = row["organization_person_id"]
        if existing_person_id is None and row["trust_invitation_id"] is not None:
            existing_person_id = invitation_person_ids.get(row["trust_invitation_id"])
        person_id = _resolve_person(
            bind,
            person_table,
            identifier_table,
            organization_id=row["organization_id"],
            existing_person_id=existing_person_id,
            linked_user_id=row["subject_user_id"],
            full_name=row["subject_name"],
            email=row["subject_email"],
            phone=user_phones.get(row["subject_user_id"]),
            relationship=(
                _relationship_from_employment(linked_employment)
                if linked_employment is not None
                else OrganizationPersonRelationship.CANDIDATE.value
            ),
            added_by_user_id=row["requested_by_user_id"],
            added_at=row["created_at"],
            last_activity_at=max(
                value
                for value in (
                    row["updated_at"],
                    row["accepted_at"],
                    row["candidate_response_submitted_at"],
                    row["created_at"],
                )
                if value is not None
            ),
            source_type="verification_request",
            source_public_id=row["public_id"],
            actor_user_id=row["requested_by_user_id"],
        )
        bind.execute(
            sa.update(verification_table)
            .where(verification_table.c.id == row["id"])
            .values(organization_person_id=person_id)
        )

    employment_to_people: dict[object, set[object]] = {}
    for row in bind.execute(
        sa.select(verification_table.c.employment_id, verification_table.c.organization_person_id)
        .where(
            verification_table.c.employment_id.is_not(None),
            verification_table.c.organization_person_id.is_not(None),
        )
    ).all():
        employment_to_people.setdefault(row.employment_id, set()).add(row.organization_person_id)

    for employment_id, person_ids in employment_to_people.items():
        if len(person_ids) == 1:
            bind.execute(
                sa.update(employment_table)
                .where(employment_table.c.id == employment_id)
                .values(organization_person_id=next(iter(person_ids)))
            )

    people = bind.execute(sa.select(person_table)).mappings().all()
    for row in people:
        employment_rows = bind.execute(
            sa.select(employment_table).where(employment_table.c.organization_person_id == row["id"])
        ).mappings().all()
        relationship = row["relationship"]
        for employment_row in employment_rows:
            relationship = _merge_relationship(relationship, _relationship_from_employment(employment_row))

        invitation_status = _latest_invitation_status(bind, invitation_table, row["id"])
        verification_status = _latest_verification_status(bind, verification_table, row["id"])
        passport_status = OrganizationPersonPassportStatusSummary.NOT_SHARED.value
        trust_state = _derive_trust_state(invitation_status, verification_status, passport_status)

        last_activity_candidates = [row["added_at"], row["last_activity_at"], row["updated_at"]]
        invitation_updated_at = bind.execute(
            sa.select(sa.func.max(invitation_table.c.updated_at)).where(
                invitation_table.c.organization_person_id == row["id"]
            )
        ).scalar_one_or_none()
        verification_updated_at = bind.execute(
            sa.select(sa.func.max(verification_table.c.updated_at)).where(
                verification_table.c.organization_person_id == row["id"]
            )
        ).scalar_one_or_none()
        employment_updated_at = bind.execute(
            sa.select(sa.func.max(employment_table.c.updated_at)).where(
                employment_table.c.organization_person_id == row["id"]
            )
        ).scalar_one_or_none()
        last_activity_candidates.extend(
            value for value in (invitation_updated_at, verification_updated_at, employment_updated_at) if value is not None
        )

        bind.execute(
            sa.update(person_table)
            .where(person_table.c.id == row["id"])
            .values(
                relationship=relationship,
                invitation_status_summary=invitation_status,
                verification_status_summary=verification_status,
                passport_status_summary=passport_status,
                trust_state=trust_state,
                last_activity_at=max(value for value in last_activity_candidates if value is not None),
            )
        )


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_index(op.f("ix_employments_organization_person_id"), table_name="employments")
    op.drop_constraint(op.f("fk_employments_organization_person_id_organization_people"), "employments", type_="foreignkey")
    op.drop_column("employments", "organization_person_id")

    op.drop_index(op.f("ix_verification_requests_organization_person_id"), table_name="verification_requests")
    op.drop_constraint(op.f("fk_verification_requests_organization_person_id_organization_people"), "verification_requests", type_="foreignkey")
    op.drop_column("verification_requests", "organization_person_id")

    op.drop_index(op.f("ix_trust_invitations_organization_person_id"), table_name="trust_invitations")
    op.drop_constraint(op.f("fk_trust_invitations_organization_person_id_organization_people"), "trust_invitations", type_="foreignkey")
    op.drop_column("trust_invitations", "organization_person_id")

    op.drop_index(op.f("ix_organization_person_passport_access_revoked_at"), table_name="organization_person_passport_access")
    op.drop_index(op.f("ix_organization_person_passport_access_expires_at"), table_name="organization_person_passport_access")
    op.drop_index(op.f("ix_organization_person_passport_access_granted_at"), table_name="organization_person_passport_access")
    op.drop_index(op.f("ix_organization_person_passport_access_access_state"), table_name="organization_person_passport_access")
    op.drop_index(op.f("ix_organization_person_passport_access_owner_user_id"), table_name="organization_person_passport_access")
    op.drop_index(op.f("ix_organization_person_passport_access_passport_share_link_id"), table_name="organization_person_passport_access")
    op.drop_index(op.f("ix_organization_person_passport_access_organization_person_id"), table_name="organization_person_passport_access")
    op.drop_table("organization_person_passport_access")

    op.drop_index(op.f("ix_organization_person_notes_author_user_id"), table_name="organization_person_notes")
    op.drop_index(op.f("ix_organization_person_notes_organization_person_id"), table_name="organization_person_notes")
    op.drop_table("organization_person_notes")

    op.drop_index(op.f("ix_organization_person_identifiers_identifier_type"), table_name="organization_person_identifiers")
    op.drop_index(op.f("ix_organization_person_identifiers_organization_id"), table_name="organization_person_identifiers")
    op.drop_index(op.f("ix_organization_person_identifiers_organization_person_id"), table_name="organization_person_identifiers")
    op.drop_table("organization_person_identifiers")

    op.drop_index(op.f("ix_organization_people_passport_status_summary"), table_name="organization_people")
    op.drop_index(op.f("ix_organization_people_verification_status_summary"), table_name="organization_people")
    op.drop_index(op.f("ix_organization_people_invitation_status_summary"), table_name="organization_people")
    op.drop_index(op.f("ix_organization_people_trust_state"), table_name="organization_people")
    op.drop_index(op.f("ix_organization_people_lifecycle_status"), table_name="organization_people")
    op.drop_index(op.f("ix_organization_people_last_activity_at"), table_name="organization_people")
    op.drop_index(op.f("ix_organization_people_added_at"), table_name="organization_people")
    op.drop_index(op.f("ix_organization_people_added_by_user_id"), table_name="organization_people")
    op.drop_index(op.f("ix_organization_people_primary_phone"), table_name="organization_people")
    op.drop_index(op.f("ix_organization_people_primary_email"), table_name="organization_people")
    op.drop_index(op.f("ix_organization_people_linked_user_id"), table_name="organization_people")
    op.drop_index(op.f("ix_organization_people_organization_id"), table_name="organization_people")
    op.drop_table("organization_people")

    for enum in (
        _enum("organization_person_identifier_type_enum", tuple(member.value for member in OrganizationPersonIdentifierType)),
        _enum("organization_person_passport_access_state_enum", tuple(member.value for member in OrganizationPersonPassportAccessState)),
        _enum("organization_person_passport_status_summary_enum", tuple(member.value for member in OrganizationPersonPassportStatusSummary)),
        _enum("organization_person_verification_status_summary_enum", tuple(member.value for member in OrganizationPersonVerificationStatusSummary)),
        _enum("organization_person_invitation_status_summary_enum", tuple(member.value for member in OrganizationPersonInvitationStatusSummary)),
        _enum("organization_person_trust_state_enum", tuple(member.value for member in OrganizationPersonTrustState)),
        _enum("organization_person_lifecycle_status_enum", tuple(member.value for member in OrganizationPersonLifecycleStatus)),
        _enum("organization_person_relationship_enum", tuple(member.value for member in OrganizationPersonRelationship)),
    ):
        enum.drop(bind, checkfirst=True)
