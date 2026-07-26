"""Institution-scoped People and Alumni projections."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ForbiddenError, NotFoundError
from app.institution_people.enums import (
    InstitutionProfessionalField,
)
from app.models.employment import Employment
from app.models.organization_person import OrganizationPerson
from app.models.verification_request import VerificationRequest
from app.models.verification_request_event import VerificationRequestEvent
from app.organization.enums import OrganizationRole, OrganizationType
from app.repositories.institution_people import InstitutionPeopleRepository
from app.repositories.organization import OrganizationRepository
from app.schemas.institution_people import (
    InstitutionCredentialEventResponse,
    InstitutionCredentialResponse,
    InstitutionPeopleListQuery,
    InstitutionPeopleListResponse,
    InstitutionPeriod,
    InstitutionPersonDetailResponse,
    InstitutionPersonListItem,
    InstitutionProfessionalFieldValue,
    InstitutionVerificationEvent,
)


class InstitutionPeopleService:
    """Builds an allowlisted university projection, never a full Passport."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._organizations = OrganizationRepository(session)
        self._repo = InstitutionPeopleRepository(session)

    async def list_people(
        self, actor_user_id: UUID, org_public_id: UUID, params: InstitutionPeopleListQuery
    ) -> InstitutionPeopleListResponse:
        organization, membership = await self._require_university_access(
            actor_user_id, org_public_id
        )
        profiles = await self._repo.list_profiles(organization.id)
        items = [
            (profile, await self._to_item(profile, organization.id, membership.role, actor_user_id))
            for profile in profiles
        ]
        items = [(profile, item) for profile, item in items if self._matches(profile, item, params)]
        if params.search:
            needle = params.search.casefold().strip()
            items = [
                (profile, item)
                for profile, item in items
                if needle in item.display_name.casefold()
                or needle in (item.programme or "").casefold()
                or needle in (item.department or "").casefold()
                or needle in (profile.student_id or "").casefold()
            ]
        items = [item for _, item in items]
        total = len(items)
        start = params.slice_start
        page_items = items[start : start + (params.limit or 20)]
        page_size = params.limit or 20
        total_pages = (total + page_size - 1) // page_size if total else 0
        return InstitutionPeopleListResponse(
            items=page_items,
            total=total,
            page=params.page or 1,
            page_size=page_size,
            total_pages=total_pages,
            offset=start,
            limit=page_size,
        )

    async def get_person(
        self, actor_user_id: UUID, org_public_id: UUID, person_public_id: UUID
    ) -> InstitutionPersonDetailResponse:
        organization, membership = await self._require_university_access(
            actor_user_id, org_public_id
        )
        profile = await self._repo.get_profile(organization.id, person_public_id)
        if profile is None:
            raise NotFoundError("Institution person not found")
        item = await self._to_item(profile, organization.id, membership.role, actor_user_id)
        consent = await self._repo.get_consent(organization.id, profile.organization_person_id)
        verification_history = await self._verification_history(
            profile.organization_person_id, organization.id
        )
        return InstitutionPersonDetailResponse(
            **item.model_dump(),
            student_id=profile.student_id
            if membership.role in {OrganizationRole.OWNER, OrganizationRole.ADMIN}
            else None,
            consented_professional_fields=[
                InstitutionProfessionalField(value)
                for value in (consent.allowed_fields if consent else [])
                if value in {field.value for field in InstitutionProfessionalField}
            ]
            if consent and self._consent_active(consent)
            else [],
            verification_history=verification_history,
            credentials=[
                self._credential_response(credential) for credential in profile.credentials
            ],
            lifecycle_events=[
                {
                    "public_id": event.public_id,
                    "previous_status": event.previous_status,
                    "new_status": event.new_status,
                    "reason": event.reason,
                    "created_at": event.created_at,
                }
                for event in profile.lifecycle_events
            ],
        )

    async def verification_history(
        self, actor_user_id: UUID, org_public_id: UUID, person_public_id: UUID
    ) -> list[InstitutionVerificationEvent]:
        organization, _ = await self._require_university_access(actor_user_id, org_public_id)
        profile = await self._repo.get_profile(organization.id, person_public_id)
        if profile is None:
            raise NotFoundError("Institution person not found")
        return await self._verification_history(profile.organization_person_id, organization.id)

    async def credentials(
        self, actor_user_id: UUID, org_public_id: UUID, person_public_id: UUID
    ) -> list[InstitutionCredentialResponse]:
        organization, _ = await self._require_university_access(actor_user_id, org_public_id)
        profile = await self._repo.get_profile(organization.id, person_public_id)
        if profile is None:
            raise NotFoundError("Institution person not found")
        return [self._credential_response(credential) for credential in profile.credentials]

    async def credential(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        person_public_id: UUID,
        credential_public_id: UUID,
    ) -> InstitutionCredentialResponse:
        organization, _ = await self._require_university_access(actor_user_id, org_public_id)
        profile = await self._repo.get_profile(organization.id, person_public_id)
        if profile is None:
            raise NotFoundError("Institution person not found")
        for credential in profile.credentials:
            if credential.public_id == credential_public_id:
                return self._credential_response(credential)
        raise NotFoundError("Institution credential not found")

    async def _require_university_access(self, actor_user_id: UUID, org_public_id: UUID):
        organization = await self._organizations.get_by_public_id(org_public_id)
        if organization is None:
            raise NotFoundError("Organization not found")
        membership = await self._organizations.get_membership(organization.id, actor_user_id)
        if membership is None:
            raise NotFoundError("Organization not found")
        if membership.suspended_at is not None or organization.suspended_at is not None:
            raise ForbiddenError("Organization access is suspended")
        if organization.organization_type != OrganizationType.UNIVERSITY:
            raise ForbiddenError("Institution People is available only to university organizations")
        return organization, membership

    async def _to_item(
        self, profile, organization_id, role, actor_user_id
    ) -> InstitutionPersonListItem:
        consent = await self._repo.get_consent(organization_id, profile.organization_person_id)
        professional = await self._professional_information(profile.organization_person, consent)
        return InstitutionPersonListItem(
            public_id=profile.organization_person.public_id,
            display_name=profile.organization_person.full_name,
            student_id_masked=self._mask_student_id(profile.student_id),
            lifecycle_status=profile.lifecycle_status,
            degree=profile.degree,
            programme=profile.programme,
            department=profile.department,
            admission=InstitutionPeriod(
                date=profile.admission_date, period=profile.admission_period
            ),
            graduation=InstitutionPeriod(
                date=profile.graduation_date, period=profile.graduation_period
            ),
            verification_status=profile.institution_verification_status,
            active_verification_count=sum(
                1
                for request in profile.organization_person.verification_requests
                if request.request_type.value in {"education", "certification", "document"}
                and request.status.value
                in {"in_progress", "awaiting_information", "pending_organization_acceptance"}
            ),
            professional_information=professional,
        )

    async def _professional_information(
        self, person: OrganizationPerson, consent
    ) -> list[InstitutionProfessionalFieldValue]:
        if consent is None or not self._consent_active(consent) or person.linked_user_id is None:
            return []
        allowed = set(consent.allowed_fields)
        employment = await self._session.scalar(
            select(Employment)
            .where(
                Employment.created_by_user_id == person.linked_user_id,
                Employment.deleted_at.is_(None),
            )
            .order_by(Employment.end_date.is_(None).desc(), Employment.start_date.desc())
        )
        if employment is None:
            return []
        values: list[InstitutionProfessionalFieldValue] = []
        if InstitutionProfessionalField.CURRENT_TITLE.value in allowed:
            values.append(
                InstitutionProfessionalFieldValue(
                    field=InstitutionProfessionalField.CURRENT_TITLE,
                    value=employment.job_title,
                    consented_at=consent.granted_at,
                    expires_at=consent.expires_at,
                )
            )
        if InstitutionProfessionalField.CURRENT_EMPLOYER.value in allowed:
            values.append(
                InstitutionProfessionalFieldValue(
                    field=InstitutionProfessionalField.CURRENT_EMPLOYER,
                    value=employment.employer_legal_name,
                    consented_at=consent.granted_at,
                    expires_at=consent.expires_at,
                )
            )
        return values

    async def _verification_history(
        self, person_id: UUID, organization_id: UUID
    ) -> list[InstitutionVerificationEvent]:
        requests = await self._session.execute(
            select(VerificationRequest).where(
                VerificationRequest.organization_id == organization_id,
                VerificationRequest.organization_person_id == person_id,
                VerificationRequest.request_type.in_(["education", "certification", "document"]),
            )
        )
        request_rows = list(requests.scalars().all())
        result: list[InstitutionVerificationEvent] = []
        for request in request_rows:
            events = await self._session.execute(
                select(VerificationRequestEvent)
                .where(VerificationRequestEvent.verification_request_id == request.id)
                .order_by(VerificationRequestEvent.created_at.asc())
            )
            for event in events.scalars().all():
                result.append(
                    InstitutionVerificationEvent(
                        public_id=event.public_id,
                        request_public_id=request.public_id,
                        event_type=event.event_type,
                        event_source=event.event_source,
                        previous_status=event.previous_status,
                        new_status=event.new_status,
                        created_at=event.created_at,
                    )
                )
        return result

    @staticmethod
    def _credential_response(credential) -> InstitutionCredentialResponse:
        return InstitutionCredentialResponse(
            public_id=credential.public_id,
            credential_type=credential.credential_type,
            title=credential.title,
            degree=credential.degree,
            programme=credential.programme,
            department=credential.department,
            issued=InstitutionPeriod(date=credential.issued_date, period=credential.issued_period),
            credential_number=credential.credential_number,
            status=credential.status,
            version=credential.version,
            events=[
                InstitutionCredentialEventResponse(
                    public_id=event.public_id,
                    event_type=event.event_type,
                    previous_status=event.previous_status,
                    new_status=event.new_status,
                    created_at=event.created_at,
                )
                for event in credential.events
            ],
        )

    @staticmethod
    def _consent_active(consent) -> bool:
        now = datetime.now(tz=UTC)
        return consent.revoked_at is None and (
            consent.expires_at is None or consent.expires_at > now
        )

    @staticmethod
    def _mask_student_id(value: str | None) -> str | None:
        if not value:
            return None
        return "*" * max(0, len(value) - 4) + value[-4:]

    @staticmethod
    def _matches(
        profile, item: InstitutionPersonListItem, params: InstitutionPeopleListQuery
    ) -> bool:
        return all(
            (
                params.lifecycle_status is None or item.lifecycle_status == params.lifecycle_status,
                params.programme is None or item.programme == params.programme,
                params.department is None or item.department == params.department,
                params.graduation_period is None
                or item.graduation.period == params.graduation_period,
                params.verification_status is None
                or item.verification_status == params.verification_status,
                params.student_id is None or profile.student_id == params.student_id,
            )
        )
