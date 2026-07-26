"""Data access for institution people projections."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.institution_people import (
    InstitutionPersonConsent,
    InstitutionPersonProfile,
    OrganizationCredentialRecord,
)
from app.models.organization_person import OrganizationPerson


class InstitutionPeopleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_profiles(self, organization_id: UUID) -> list[InstitutionPersonProfile]:
        result = await self._session.execute(
            select(InstitutionPersonProfile)
            .where(InstitutionPersonProfile.organization_id == organization_id)
            .options(
                selectinload(InstitutionPersonProfile.organization_person),
                selectinload(InstitutionPersonProfile.organization_person).selectinload(
                    OrganizationPerson.verification_requests
                ),
                selectinload(InstitutionPersonProfile.credentials).selectinload(
                    OrganizationCredentialRecord.events
                ),
                selectinload(InstitutionPersonProfile.lifecycle_events),
            )
            .order_by(InstitutionPersonProfile.updated_at.desc())
        )
        return list(result.scalars().unique().all())

    async def get_profile(
        self, organization_id: UUID, person_public_id: UUID
    ) -> InstitutionPersonProfile | None:
        result = await self._session.execute(
            select(InstitutionPersonProfile)
            .join(
                OrganizationPerson,
                OrganizationPerson.id == InstitutionPersonProfile.organization_person_id,
            )
            .where(
                InstitutionPersonProfile.organization_id == organization_id,
                OrganizationPerson.public_id == person_public_id,
            )
            .options(
                selectinload(InstitutionPersonProfile.organization_person),
                selectinload(InstitutionPersonProfile.organization_person).selectinload(
                    OrganizationPerson.verification_requests
                ),
                selectinload(InstitutionPersonProfile.credentials).selectinload(
                    OrganizationCredentialRecord.events
                ),
                selectinload(InstitutionPersonProfile.lifecycle_events),
            )
        )
        return result.scalar_one_or_none()

    async def get_consent(
        self, organization_id: UUID, person_id: UUID
    ) -> InstitutionPersonConsent | None:
        return await self._session.scalar(
            select(InstitutionPersonConsent).where(
                InstitutionPersonConsent.organization_id == organization_id,
                InstitutionPersonConsent.organization_person_id == person_id,
            )
        )
