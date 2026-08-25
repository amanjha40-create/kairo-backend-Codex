"""Institution-only verification and dashboard projections."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.institution_people.enums import (
    InstitutionPersonLifecycleStatus,
    InstitutionVerificationStatus,
)
from app.models.institution_people import InstitutionPersonProfile
from app.models.verification_request import VerificationRequest
from app.models.verification_request_event import VerificationRequestEvent
from app.organization.enums import OrganizationType
from app.repositories.institution_people import InstitutionPeopleRepository
from app.repositories.organization import OrganizationRepository
from app.repositories.verification_request import VerificationRequestRepository
from app.repositories.verification_request_evidence import (
    VerificationRequestEvidenceRepository,
)
from app.schemas.institution_people import InstitutionPeriod
from app.schemas.institution_workspace import (
    InstitutionAuthoritativeRecord,
    InstitutionCandidateEducationClaim,
    InstitutionComparisonField,
    InstitutionDashboardActivity,
    InstitutionDashboardCredential,
    InstitutionDashboardResponse,
    InstitutionDashboardStatistics,
    InstitutionPassportCredentialSummary,
    InstitutionPassportSummaryResponse,
    InstitutionPeopleSummary,
    InstitutionVerificationComparison,
    InstitutionVerificationDetailResponse,
    InstitutionVerificationInboxItem,
    InstitutionVerificationInboxQuery,
    InstitutionVerificationInboxResponse,
)
from app.schemas.pagination import ListQueryParams, Page, filter_sort_paginate
from app.schemas.verification_request import (
    VerificationRequestEvidenceResponse,
    VerificationRequestTimelineEventResponse,
    VerificationRequestTimelineResponse,
)
from app.services.institution_people_service import InstitutionPeopleService
from app.services.verification_request_service import (
    VerificationRequestService,
    is_internal_admin_note_event,
    is_private_organization_event,
)
from app.services.verification_request_workflow_service import VerificationRequestWorkflowService
from app.verification_requests.enums import (
    VerificationRequestEventSource,
    VerificationRequestStatus,
    VerificationRequestType,
)

ACADEMIC_REQUEST_TYPES = {
    VerificationRequestType.EDUCATION,
    VerificationRequestType.CERTIFICATION,
    VerificationRequestType.DOCUMENT,
}
FINAL_STATUSES = {
    VerificationRequestStatus.VERIFIED,
    VerificationRequestStatus.REJECTED,
    VerificationRequestStatus.UNABLE_TO_VERIFY,
    VerificationRequestStatus.CANCELLED,
    VerificationRequestStatus.EXPIRED,
}
FINAL_STATUS_VALUES = {status.value for status in FINAL_STATUSES}
INSTITUTION_ACTIVE_STATUS_VALUES = {
    VerificationRequestStatus.DRAFT.value,
    VerificationRequestStatus.PENDING_SUBJECT_ACCEPTANCE.value,
    VerificationRequestStatus.ACCEPTED.value,
    VerificationRequestStatus.PENDING_SUBJECT_SUBMISSION.value,
    VerificationRequestStatus.PENDING_ADMIN_REVIEW.value,
    VerificationRequestStatus.AWAITING_SUBJECT_CORRECTIONS.value,
    VerificationRequestStatus.PENDING_ADMIN_RE_REVIEW.value,
    VerificationRequestStatus.APPROVED_FOR_ORGANIZATION_VERIFICATION.value,
    VerificationRequestStatus.PENDING_ORGANIZATION_RESOLUTION.value,
    VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE.value,
    VerificationRequestStatus.IN_PROGRESS.value,
    VerificationRequestStatus.AWAITING_INFORMATION.value,
}
PRIORITY_ORDER = {"urgent": 0, "high": 1, "normal": 2, "low": 3}


class InstitutionWorkspaceService:
    """Read models and actions restricted to university workspaces."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._organizations = OrganizationRepository(session)
        self._people = InstitutionPeopleRepository(session)
        self._people_service = InstitutionPeopleService(session)
        self._verification_requests = VerificationRequestRepository(session)
        self._verification_evidence = VerificationRequestEvidenceRepository(session)
        self._verification_service = VerificationRequestService(session)
        self._workflow = VerificationRequestWorkflowService(self._verification_requests)

    async def dashboard(
        self, actor_user_id: UUID, org_public_id: UUID
    ) -> InstitutionDashboardResponse:
        organization, _ = await self._require_university_access(actor_user_id, org_public_id)
        requests = await self._requests_for_organization(organization.id)
        profiles = await self._people.list_profiles(organization.id)
        status_counts = Counter(self._request_status_value(request) for request in requests)
        lifecycle_counts = Counter(profile.lifecycle_status for profile in profiles)
        recent_credentials = sorted(
            (
                credential
                for profile in profiles
                if profile.institution_verification_status == InstitutionVerificationStatus.VERIFIED
                for credential in profile.credentials
            ),
            key=lambda credential: credential.updated_at,
            reverse=True,
        )[:10]
        events = await self._recent_events(organization.id)
        return InstitutionDashboardResponse(
            pending_verifications=sum(
                1
                for request in requests
                if self._request_status_value(request) in INSTITUTION_ACTIVE_STATUS_VALUES
            ),
            recently_verified_credentials=[
                InstitutionDashboardCredential(
                    public_id=credential.public_id,
                    title=credential.title,
                    credential_type=credential.credential_type,
                    status=credential.status,
                    updated_at=credential.updated_at,
                )
                for credential in recent_credentials
            ],
            verification_activity=[
                InstitutionDashboardActivity(
                    request_public_id=request_public_id,
                    event_type=event.event_type,
                    event_source=event.event_source,
                    created_at=event.created_at,
                )
                for event, request_public_id in events
            ],
            people=InstitutionPeopleSummary(
                total=len(profiles),
                current_student=lifecycle_counts[
                    InstitutionPersonLifecycleStatus.CURRENT_STUDENT.value
                ],
                alumni=lifecycle_counts[InstitutionPersonLifecycleStatus.ALUMNI.value],
                withdrawn=lifecycle_counts[InstitutionPersonLifecycleStatus.WITHDRAWN.value],
                inactive=lifecycle_counts[InstitutionPersonLifecycleStatus.INACTIVE.value],
            ),
            statistics=InstitutionDashboardStatistics(
                total_verifications=len(requests),
                verified_verifications=status_counts[VerificationRequestStatus.VERIFIED.value],
                awaiting_information=status_counts[
                    VerificationRequestStatus.AWAITING_INFORMATION.value
                ],
                high_priority=sum(
                    1 for request in requests if request.priority in {"high", "urgent"}
                ),
            ),
        )

    async def list_verifications(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        params: InstitutionVerificationInboxQuery,
    ) -> InstitutionVerificationInboxResponse:
        organization, _ = await self._require_university_access(actor_user_id, org_public_id)
        requests = await self._requests_for_organization(organization.id)
        filtered = [
            request for request in requests if self._matches_request(request, actor_user_id, params)
        ]
        ordered = self._sort_requests(filtered, params)
        total = len(ordered)
        items = [
            self._inbox_item(request) for request in ordered[params.slice_start : params.slice_end]
        ]
        return InstitutionVerificationInboxResponse.create(items=items, total=total, params=params)

    async def verification_detail(
        self, actor_user_id: UUID, org_public_id: UUID, request_public_id: UUID
    ) -> InstitutionVerificationDetailResponse:
        organization, _ = await self._require_university_access(actor_user_id, org_public_id)
        request = await self._get_academic_request(organization.id, request_public_id)
        return self._detail_response(request, await self._comparison(organization.id, request))

    async def list_verification_evidence(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        request_public_id: UUID,
        params: ListQueryParams | None = None,
    ) -> list[VerificationRequestEvidenceResponse] | Page[VerificationRequestEvidenceResponse]:
        organization, _ = await self._require_university_access(actor_user_id, org_public_id)
        request = await self._get_academic_request(organization.id, request_public_id)
        items = await self._verification_evidence.list_for_request(request.id)
        visible_items = self._verification_service._filter_evidence_by_consent(request, items)  # noqa: SLF001
        responses = [
            await self._verification_service._to_evidence_response(  # noqa: SLF001
                item,
                include_download_url=True,
            )
            for item in visible_items
        ]
        if params is None:
            return responses
        return filter_sort_paginate(
            responses,
            params=params,
            search_fields=("evidence_type", "field_key", "status"),
            allowed_sort_fields=(
                "created_at",
                "updated_at",
                "evidence_type",
                "field_key",
                "status",
            ),
            default_sort_by="created_at",
        )

    async def get_verification_timeline(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        request_public_id: UUID,
        params: ListQueryParams | None = None,
    ) -> VerificationRequestTimelineResponse:
        organization, _ = await self._require_university_access(actor_user_id, org_public_id)
        request = await self._get_academic_request(organization.id, request_public_id)
        rows = await self._verification_requests.list_timeline(request.id)
        timeline_items = [
            VerificationRequestTimelineEventResponse(
                public_id=row.public_id,
                event_type=row.event_type,
                event_source=row.event_source,
                previous_status=row.previous_status,
                new_status=row.new_status,
                metadata=dict(row.metadata_payload or {}),
                created_at=row.created_at,
            )
            for row in rows
            if self._institution_timeline_event_visible(row)
        ]
        effective_params = params or ListQueryParams()
        page = filter_sort_paginate(
            timeline_items,
            params=effective_params,
            search_fields=("event_type", "event_source"),
            status_field=None,
            allowed_sort_fields=("created_at", "event_type"),
            default_sort_by="created_at",
            force_page_envelope=True,
        )
        if not isinstance(page, Page):
            raise RuntimeError("Timeline pagination must return a page envelope")
        return VerificationRequestTimelineResponse(
            verification_request_public_id=request.public_id,
            items=page.items,
            total=page.total,
            page=page.page,
            page_size=page.page_size,
            total_pages=page.total_pages,
            offset=page.offset,
            limit=page.limit,
        )

    async def cancel_verification(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        request_public_id: UUID,
        payload,
    ) -> InstitutionVerificationDetailResponse:
        organization, _ = await self._require_university_access(actor_user_id, org_public_id)
        await self._get_academic_request(organization.id, request_public_id)
        await self._verification_service.cancel(actor_user_id, request_public_id, payload)
        request = await self._get_academic_request(organization.id, request_public_id)
        return self._detail_response(request, await self._comparison(organization.id, request))

    async def change_priority(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        request_public_id: UUID,
        priority: str,
    ) -> InstitutionVerificationDetailResponse:
        organization, _ = await self._require_university_access(actor_user_id, org_public_id)
        request = await self._get_academic_request(organization.id, request_public_id)
        if request.status in FINAL_STATUSES:
            raise ConflictError("Cannot change priority for a closed verification request")
        previous_priority = request.priority or "normal"
        request.priority = priority
        await self._workflow.record_action(
            request,
            actor_user_id=actor_user_id,
            event_type="verification_request_priority_changed",
            event_source=VerificationRequestEventSource.ORGANIZATION,
            metadata={
                "visibility": "organization_internal",
                "previous_priority": previous_priority,
                "priority": priority,
            },
        )
        await self._session.commit()
        request = await self._get_academic_request(organization.id, request_public_id)
        return self._detail_response(request, await self._comparison(organization.id, request))

    async def passport_summary(
        self, actor_user_id: UUID, org_public_id: UUID, person_public_id: UUID
    ) -> InstitutionPassportSummaryResponse:
        organization, membership = await self._require_university_access(
            actor_user_id, org_public_id
        )
        profile = await self._people.get_profile(organization.id, person_public_id)
        if profile is None:
            raise NotFoundError("Institution person not found")
        item = await self._people_service._to_item(  # noqa: SLF001 - shared allowlisted projection
            profile, organization.id, membership.role, actor_user_id
        )
        consent = await self._people.get_consent(organization.id, profile.organization_person_id)
        fields = (
            [field for field in item.professional_information]
            if consent is not None and self._people_service._consent_active(consent)  # noqa: SLF001
            else []
        )
        return InstitutionPassportSummaryResponse(
            person_public_id=item.public_id,
            display_name=item.display_name,
            lifecycle_status=item.lifecycle_status,
            degree=item.degree,
            programme=item.programme,
            department=item.department,
            admission=item.admission,
            graduation=item.graduation,
            verification_status=item.verification_status,
            consented_professional_fields=[field.field for field in fields],
            professional_information=fields,
            credentials=[
                InstitutionPassportCredentialSummary(
                    public_id=credential.public_id,
                    title=credential.title,
                    credential_type=credential.credential_type,
                    status=credential.status,
                    issued=InstitutionPeriod(
                        date=credential.issued_date, period=credential.issued_period
                    ),
                )
                for credential in profile.credentials
            ],
        )

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
            raise ForbiddenError(
                "Institution workspace is available only to university organizations"
            )
        return organization, membership

    async def _requests_for_organization(self, organization_id: UUID) -> list[VerificationRequest]:
        result = await self._session.execute(
            select(VerificationRequest)
            .where(
                VerificationRequest.organization_id == organization_id,
                VerificationRequest.request_type.in_(ACADEMIC_REQUEST_TYPES),
            )
            .options(
                selectinload(VerificationRequest.education),
                selectinload(VerificationRequest.organization_person),
                selectinload(VerificationRequest.events),
            )
            .order_by(VerificationRequest.created_at.desc())
        )
        return list(result.scalars().unique().all())

    async def _get_academic_request(
        self, organization_id: UUID, request_public_id: UUID
    ) -> VerificationRequest:
        result = await self._session.execute(
            select(VerificationRequest)
            .where(
                VerificationRequest.organization_id == organization_id,
                VerificationRequest.public_id == request_public_id,
                VerificationRequest.request_type.in_(ACADEMIC_REQUEST_TYPES),
            )
            .options(
                selectinload(VerificationRequest.education),
                selectinload(VerificationRequest.organization_person),
                selectinload(VerificationRequest.events),
            )
        )
        request = result.scalar_one_or_none()
        if request is None:
            raise NotFoundError("Institution verification request not found")
        return request

    async def _recent_events(
        self, organization_id: UUID
    ) -> list[tuple[VerificationRequestEvent, UUID]]:
        since = datetime.now(tz=UTC) - timedelta(days=30)
        rows = await self._session.execute(
            select(VerificationRequestEvent, VerificationRequest.public_id)
            .join(
                VerificationRequest,
                VerificationRequest.id == VerificationRequestEvent.verification_request_id,
            )
            .where(
                VerificationRequest.organization_id == organization_id,
                VerificationRequest.request_type.in_(ACADEMIC_REQUEST_TYPES),
                VerificationRequestEvent.created_at >= since,
            )
            .order_by(VerificationRequestEvent.created_at.desc())
            .limit(20)
        )
        return list(rows.all())

    @staticmethod
    def _matches_request(
        request: VerificationRequest,
        actor_user_id: UUID,
        params: InstitutionVerificationInboxQuery,
    ) -> bool:
        request_status = InstitutionWorkspaceService._request_status_value(request)
        if params.statuses and request_status not in params.statuses:
            return False
        if params.priority and request.priority != params.priority:
            return False
        request_type = InstitutionWorkspaceService._request_type_value(request)
        if params.request_type and request_type != params.request_type.value:
            return False
        if params.assigned_to_me is True and request.assigned_to_user_id != actor_user_id:
            return False
        if params.assigned_to_me is False and request.assigned_to_user_id == actor_user_id:
            return False
        if not params.search:
            return True
        needle = params.search.casefold()
        education = request.education
        candidates = (
            request.subject_name,
            request.subject_email,
            education.institution_name if education is not None else None,
            education.degree if education is not None else None,
            education.field_of_study if education is not None else None,
        )
        return any(needle in (value or "").casefold() for value in candidates)

    @staticmethod
    def _sort_requests(
        requests: list[VerificationRequest], params: InstitutionVerificationInboxQuery
    ) -> list[VerificationRequest]:
        if params.sort_by == "priority":

            def key(request: VerificationRequest) -> int:
                return PRIORITY_ORDER.get(request.priority or "normal", 2)
        elif params.sort_by == "due_date":

            def key(request: VerificationRequest) -> tuple[bool, object]:
                return request.due_date is None, request.due_date
        else:

            def key(request: VerificationRequest) -> object:
                return getattr(request, params.sort_by)

        return sorted(requests, key=key, reverse=params.sort_order == "desc")

    @staticmethod
    def _inbox_item(request: VerificationRequest) -> InstitutionVerificationInboxItem:
        education = request.education
        return InstitutionVerificationInboxItem(
            public_id=request.public_id,
            subject_name=request.subject_name,
            request_type=InstitutionWorkspaceService._request_type_value(request),
            status=InstitutionWorkspaceService._request_status_value(request),
            priority=request.priority or "normal",
            due_date=request.due_date,
            created_at=request.created_at,
            updated_at=request.updated_at,
            assigned_reviewer_name=None,
            education_institution_name=education.institution_name if education else None,
            education_degree=education.degree if education else None,
        )

    @staticmethod
    def _request_status_value(request: VerificationRequest) -> str:
        status = request.status
        return status.value if hasattr(status, "value") else str(status)

    @staticmethod
    def _request_type_value(request: VerificationRequest) -> str:
        request_type = request.request_type
        return request_type.value if hasattr(request_type, "value") else str(request_type)

    async def _comparison(
        self, organization_id: UUID, request: VerificationRequest
    ) -> InstitutionVerificationComparison:
        education = request.education
        candidate = InstitutionCandidateEducationClaim(
            institution_name=education.institution_name if education else None,
            degree=education.degree if education else None,
            programme=education.field_of_study if education else None,
            admission=InstitutionPeriod(date=education.start_date if education else None),
            graduation=InstitutionPeriod(date=education.end_date if education else None),
        )
        profile = None
        if request.organization_person_id is not None:
            profile = await self._session.scalar(
                select(InstitutionPersonProfile).where(
                    InstitutionPersonProfile.organization_id == organization_id,
                    InstitutionPersonProfile.organization_person_id
                    == request.organization_person_id,
                )
            )
        if profile is None:
            return InstitutionVerificationComparison(
                match_status="record_unavailable",
                candidate_claim=candidate,
                institution_record=InstitutionAuthoritativeRecord(found=False),
                fields=[],
            )
        institution = InstitutionAuthoritativeRecord(
            found=True,
            student_id=profile.student_id,
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
        )
        fields = [
            self._comparison_field("degree", candidate.degree, profile.degree),
            self._comparison_field("programme", candidate.programme, profile.programme),
            self._comparison_field(
                "admission_date",
                self._date_value(education.start_date if education else None),
                self._date_value(profile.admission_date),
            ),
            self._comparison_field(
                "graduation_date",
                self._date_value(education.end_date if education else None),
                self._date_value(profile.graduation_date),
            ),
        ]
        compared = [field for field in fields if field.outcome != "unavailable"]
        if not compared:
            match_status = "record_unavailable"
        elif all(field.outcome == "match" for field in compared) and len(compared) == len(fields):
            match_status = "exact"
        elif any(field.outcome == "match" for field in compared):
            match_status = "partial"
        else:
            match_status = "no_match"
        return InstitutionVerificationComparison(
            match_status=match_status,
            candidate_claim=candidate,
            institution_record=institution,
            fields=fields,
        )

    @staticmethod
    def _comparison_field(
        key: str, candidate_value: str | None, institution_value: str | None
    ) -> InstitutionComparisonField:
        if candidate_value is None or institution_value is None:
            outcome = "unavailable"
        elif candidate_value.strip().casefold() == institution_value.strip().casefold():
            outcome = "match"
        else:
            outcome = "different"
        return InstitutionComparisonField(
            key=key,
            candidate_value=candidate_value,
            institution_value=institution_value,
            outcome=outcome,
        )

    @staticmethod
    def _date_value(value) -> str | None:  # noqa: ANN001
        return value.isoformat() if value is not None else None

    @staticmethod
    def _institution_timeline_event_visible(row: VerificationRequestEvent) -> bool:
        return not is_internal_admin_note_event(
            row.event_type,
            row.metadata_payload,
        ) and not is_private_organization_event(
            row.event_type,
            row.metadata_payload,
        )

    def _detail_response(
        self,
        request: VerificationRequest,
        comparison: InstitutionVerificationComparison,
    ) -> InstitutionVerificationDetailResponse:
        return InstitutionVerificationDetailResponse(
            **self._inbox_item(request).model_dump(),
            organization_internal_note=request.organization_internal_note,
            candidate_response=request.candidate_response,
            candidate_response_submitted_at=request.candidate_response_submitted_at,
            consented_fields=list(request.consented_fields or []),
            consented_evidence_scope=list(request.consented_evidence_scope or []),
            comparison=comparison,
        )
