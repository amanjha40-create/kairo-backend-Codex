"""Repository for organization-scoped people registry access."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.models.employment import Employment
from app.models.organization_person import OrganizationPerson
from app.models.organization_person_identifier import OrganizationPersonIdentifier
from app.models.organization_person_note import OrganizationPersonNote
from app.models.organization_person_passport_access import OrganizationPersonPassportAccess
from app.models.trust_invitation import TrustInvitation
from app.models.trust_invitation_event import TrustInvitationEvent
from app.models.verification_request import VerificationRequest
from app.models.verification_request_event import VerificationRequestEvent


class OrganizationPersonRepository:
    """Data access for the organization people registry."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, person: OrganizationPerson) -> OrganizationPerson:
        self._session.add(person)
        await self._session.flush()
        return person

    async def get_by_id(
        self,
        person_id: UUID,
        *,
        load_related: bool = False,
    ) -> OrganizationPerson | None:
        stmt = select(OrganizationPerson).where(OrganizationPerson.id == person_id)
        if load_related:
            stmt = stmt.options(*self._person_options())
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_public_id(
        self,
        organization_id: UUID,
        person_public_id: UUID,
        *,
        load_related: bool = False,
    ) -> OrganizationPerson | None:
        stmt = select(OrganizationPerson).where(
            OrganizationPerson.organization_id == organization_id,
            OrganizationPerson.public_id == person_public_id,
        )
        if load_related:
            stmt = stmt.options(*self._person_options())
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_organization(
        self,
        organization_id: UUID,
        *,
        load_related: bool = False,
    ) -> list[OrganizationPerson]:
        stmt = select(OrganizationPerson).where(OrganizationPerson.organization_id == organization_id)
        if load_related:
            stmt = stmt.options(*self._person_options())
        stmt = stmt.order_by(
            OrganizationPerson.last_activity_at.desc().nullslast(),
            OrganizationPerson.added_at.desc(),
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())

    async def find_by_linked_user(
        self,
        organization_id: UUID,
        linked_user_id: UUID,
    ) -> OrganizationPerson | None:
        stmt = (
            select(OrganizationPerson)
            .where(
                OrganizationPerson.organization_id == organization_id,
                OrganizationPerson.linked_user_id == linked_user_id,
            )
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def find_by_primary_email(
        self,
        organization_id: UUID,
        normalized_email: str,
    ) -> OrganizationPerson | None:
        stmt = (
            select(OrganizationPerson)
            .where(
                OrganizationPerson.organization_id == organization_id,
                OrganizationPerson.primary_email == normalized_email,
            )
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def find_by_primary_phone(
        self,
        organization_id: UUID,
        normalized_phone: str,
    ) -> OrganizationPerson | None:
        stmt = (
            select(OrganizationPerson)
            .where(
                OrganizationPerson.organization_id == organization_id,
                OrganizationPerson.primary_phone == normalized_phone,
            )
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def find_by_identifier(
        self,
        organization_id: UUID,
        identifier_type: str,
        normalized_value: str,
    ) -> OrganizationPerson | None:
        stmt = (
            select(OrganizationPerson)
            .join(
                OrganizationPersonIdentifier,
                OrganizationPersonIdentifier.organization_person_id == OrganizationPerson.id,
            )
            .where(
                OrganizationPerson.organization_id == organization_id,
                OrganizationPersonIdentifier.organization_id == organization_id,
                OrganizationPersonIdentifier.identifier_type == identifier_type,
                OrganizationPersonIdentifier.normalized_value == normalized_value,
            )
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_identifier(
        self,
        organization_person_id: UUID,
        identifier_type: str,
        normalized_value: str,
    ) -> OrganizationPersonIdentifier | None:
        stmt = (
            select(OrganizationPersonIdentifier)
            .where(
                OrganizationPersonIdentifier.organization_person_id == organization_person_id,
                OrganizationPersonIdentifier.identifier_type == identifier_type,
                OrganizationPersonIdentifier.normalized_value == normalized_value,
            )
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create_identifier(self, identifier: OrganizationPersonIdentifier) -> OrganizationPersonIdentifier:
        self._session.add(identifier)
        await self._session.flush()
        return identifier

    async def add_note(self, note: OrganizationPersonNote) -> OrganizationPersonNote:
        self._session.add(note)
        await self._session.flush()
        return note

    async def get_note_by_public_id(
        self,
        organization_person_id: UUID,
        note_public_id: UUID,
    ) -> OrganizationPersonNote | None:
        stmt = (
            select(OrganizationPersonNote)
            .options(joinedload(OrganizationPersonNote.author_user))
            .where(
                OrganizationPersonNote.organization_person_id == organization_person_id,
                OrganizationPersonNote.public_id == note_public_id,
            )
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def delete_note(self, note: OrganizationPersonNote) -> None:
        await self._session.delete(note)
        await self._session.flush()

    async def add_passport_access(
        self,
        access: OrganizationPersonPassportAccess,
    ) -> OrganizationPersonPassportAccess:
        self._session.add(access)
        await self._session.flush()
        return access

    async def get_passport_access_by_share(
        self,
        organization_person_id: UUID,
        passport_share_link_id: UUID,
    ) -> OrganizationPersonPassportAccess | None:
        stmt = (
            select(OrganizationPersonPassportAccess)
            .where(
                OrganizationPersonPassportAccess.organization_person_id == organization_person_id,
                OrganizationPersonPassportAccess.passport_share_link_id == passport_share_link_id,
            )
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    @staticmethod
    def _person_options():  # noqa: ANN205
        return (
            joinedload(OrganizationPerson.organization),
            joinedload(OrganizationPerson.linked_user),
            joinedload(OrganizationPerson.added_by_user),
            selectinload(OrganizationPerson.identifiers),
            selectinload(OrganizationPerson.notes).joinedload(OrganizationPersonNote.author_user),
            selectinload(OrganizationPerson.passport_access_entries)
            .joinedload(OrganizationPersonPassportAccess.passport_share_link),
            selectinload(OrganizationPerson.passport_access_entries)
            .joinedload(OrganizationPersonPassportAccess.owner_user),
            selectinload(OrganizationPerson.trust_invitations)
            .joinedload(TrustInvitation.created_by_user),
            selectinload(OrganizationPerson.trust_invitations)
            .joinedload(TrustInvitation.accepted_by_user),
            selectinload(OrganizationPerson.trust_invitations)
            .selectinload(TrustInvitation.events)
            .joinedload(TrustInvitationEvent.actor_user),
            selectinload(OrganizationPerson.verification_requests)
            .joinedload(VerificationRequest.organization),
            selectinload(OrganizationPerson.verification_requests)
            .joinedload(VerificationRequest.trust_invitation),
            selectinload(OrganizationPerson.verification_requests)
            .selectinload(VerificationRequest.events),
            selectinload(OrganizationPerson.employments),
            selectinload(OrganizationPerson.verification_requests)
            .selectinload(VerificationRequest.evidence_items),
            selectinload(OrganizationPerson.employments)
            .joinedload(Employment.employer_verification_request),
        )
