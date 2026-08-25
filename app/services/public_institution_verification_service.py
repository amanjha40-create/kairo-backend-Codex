"""Public institution magic-link verification flow."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import hash_refresh_token
from app.config import Settings, get_settings
from app.exceptions import ConflictError, ExpiredLinkError, NotFoundError, ValidationAppError
from app.integrations.email.sender import get_email_sender
from app.models.institution_verification_request import InstitutionVerificationRequest
from app.models.verification_request import VerificationRequest
from app.notifications.contracts import NotificationRequest
from app.repositories.education import EducationRepository
from app.repositories.institution_verification import InstitutionVerificationRepository
from app.repositories.organization import OrganizationRepository
from app.repositories.verification_request import VerificationRequestRepository
from app.repositories.verification_request_evidence import VerificationRequestEvidenceRepository
from app.schemas.public_institution_verification import (
    PublicInstitutionVerificationCandidateClaim,
    PublicInstitutionVerificationClarificationRequest,
    PublicInstitutionVerificationConfirmRequest,
    PublicInstitutionVerificationDiscrepancyRequest,
    PublicInstitutionVerificationEvidenceFile,
    PublicInstitutionVerificationReadResponse,
    PublicInstitutionVerificationRequestProjection,
)
from app.services.notification_service import NotificationService
from app.services.verification_request_service import VerificationRequestService
from app.services.verification_request_workflow_service import VerificationRequestWorkflowService
from app.verification_requests.enums import (
    VerificationRequestEventSource,
    VerificationRequestStatus,
)

_TERMINAL_REQUEST_STATUSES = {
    VerificationRequestStatus.VERIFIED,
    VerificationRequestStatus.REJECTED,
    VerificationRequestStatus.UNABLE_TO_VERIFY,
    VerificationRequestStatus.CANCELLED,
    VerificationRequestStatus.EXPIRED,
}
_COMPLETED_PUBLIC_REQUEST_STATUSES = _TERMINAL_REQUEST_STATUSES | {
    VerificationRequestStatus.PENDING_ADMIN_QUALITY_REVIEW,
    VerificationRequestStatus.AWAITING_INFORMATION,
}


class PublicInstitutionVerificationService:
    """Scoped public verification endpoint for one institution education request."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._requests = VerificationRequestRepository(session)
        self._organizations = OrganizationRepository(session)
        self._education = EducationRepository(session)
        self._public_requests = InstitutionVerificationRepository(session)
        self._evidence = VerificationRequestEvidenceRepository(session)
        self._verification_service = VerificationRequestService(session)
        self._workflow = VerificationRequestWorkflowService(self._requests)
        self._notifications = NotificationService(session, self._settings)
        self._email = get_email_sender(self._settings, session=session)

    def _review_link(self, token: str) -> str:
        base = (
            self._settings.institution_portal_base_url or self._settings.app_public_base_url
        ).rstrip("/")
        return f"{base}/institution/verify/{token}"

    async def issue_public_link(
        self,
        *,
        actor_user_id: UUID,
        verification_request: VerificationRequest,
    ) -> InstitutionVerificationRequest:
        if verification_request.education_id is None:
            raise ConflictError(
                "Institution public verification requires an education-linked request"
            )
        if verification_request.organization_id is None:
            raise ConflictError("Institution public verification requires a resolved organization")

        organization = await self._organizations.get_by_id(verification_request.organization_id)
        education = await self._education.get_active_by_id(verification_request.education_id)
        if organization is None or education is None:
            raise NotFoundError("Institution verification context not found")

        recipient_email = (
            (
                organization.work_email
                or verification_request.target_organization_email
                or ""
            )
            .strip()
            .lower()
        )
        if not recipient_email:
            raise ConflictError(
                "A recipient email is required for institution verification delivery"
            )

        now = datetime.now(tz=UTC)
        ttl = timedelta(hours=self._settings.employer_verification_token_ttl_hours)
        raw_token = secrets.token_urlsafe(32)
        token_hash = hash_refresh_token(raw_token)
        row = await self._public_requests.get_by_verification_request_id(verification_request.id)
        if row is None:
            row = InstitutionVerificationRequest(
                verification_request_id=verification_request.id,
                organization_id=organization.id,
                contact_name=organization.name,
                recipient_email=recipient_email,
                token_hash=token_hash,
                expires_at=now + ttl,
                sent_at=now,
            )
            await self._public_requests.create(row)
        else:
            row.organization_id = organization.id
            row.contact_name = organization.name
            row.recipient_email = recipient_email
            row.token_hash = token_hash
            row.expires_at = now + ttl
            row.sent_at = now
            row.viewed_at = None
            row.responded_at = None
            row.revoked_at = None
            row.revoked_by_user_id = None
            row.response_action = "pending"
            row.response_note = None
            row.response_metadata = {}
            await self._public_requests.update(row)

        await self._email.send_institution_verification(
            to_email=recipient_email,
            contact_name=organization.name,
            subject_name=verification_request.subject_name,
            institution_name=education.institution_name,
            degree=education.degree or "Education record",
            programme=education.field_of_study or "Not provided",
            review_url=self._review_link(raw_token),
            ttl_hours=self._settings.employer_verification_token_ttl_hours,
            audit_metadata={
                "institution_verification_request_public_id": str(row.public_id),
                "verification_request_public_id": str(verification_request.public_id),
                "organization_public_id": str(organization.public_id),
                "actor_user_id": str(actor_user_id),
            },
        )
        await self._workflow.record_action(
            verification_request,
            actor_user_id=actor_user_id,
            event_type="institution_link_issued",
            event_source=VerificationRequestEventSource.ADMIN,
            metadata={
                "institution_verification_request_public_id": str(row.public_id),
                "recipient_email_domain": recipient_email.split("@")[-1],
                "organization_public_id": str(organization.public_id),
            },
        )
        return row

    async def get_public_request(
        self,
        raw_token: str,
    ) -> PublicInstitutionVerificationReadResponse:
        row = await self._load_by_token(raw_token, allow_missing=True)
        if row is None:
            return PublicInstitutionVerificationReadResponse(token=raw_token, state="invalid")

        request = await self._requests.get_by_id(row.verification_request_id)
        if request is None or request.education_id is None:
            return PublicInstitutionVerificationReadResponse(
                token=raw_token,
                state="invalid",
                expires_at=row.expires_at,
            )

        state = self._derive_state(row, request)
        if row.viewed_at is None and state == "valid":
            row.viewed_at = datetime.now(tz=UTC)
            await self._workflow.record_action(
                request,
                actor_user_id=None,
                event_type="institution_link_opened",
                event_source=VerificationRequestEventSource.ORGANIZATION,
                metadata={"institution_verification_request_public_id": str(row.public_id)},
            )
            await self._session.commit()

        projection = await self._build_request_projection(request)
        return PublicInstitutionVerificationReadResponse(
            token=raw_token,
            state=state,
            expires_at=row.expires_at,
            request=projection if state != "invalid" else None,
        )

    async def confirm_from_public(
        self,
        raw_token: str,
        payload: PublicInstitutionVerificationConfirmRequest,
    ) -> PublicInstitutionVerificationReadResponse:
        return await self._respond(
            raw_token,
            action="confirm",
            metadata=self._normalize_metadata(note=payload.note),
        )

    async def report_discrepancy_from_public(
        self,
        raw_token: str,
        payload: PublicInstitutionVerificationDiscrepancyRequest,
    ) -> PublicInstitutionVerificationReadResponse:
        return await self._respond(
            raw_token,
            action="discrepancy",
            metadata=self._normalize_metadata(
                note=payload.explanation,
                fields=payload.fields,
            ),
        )

    async def request_clarification_from_public(
        self,
        raw_token: str,
        payload: PublicInstitutionVerificationClarificationRequest,
    ) -> PublicInstitutionVerificationReadResponse:
        return await self._respond(
            raw_token,
            action="clarification",
            metadata=self._normalize_metadata(
                note=payload.message,
                fields=payload.fields,
                request_document=payload.request_document,
            ),
        )

    async def _respond(
        self,
        raw_token: str,
        *,
        action: str,
        metadata: dict[str, object],
    ) -> PublicInstitutionVerificationReadResponse:
        row = await self._load_by_token(raw_token, allow_missing=False)
        request = await self._requests.get_by_id(row.verification_request_id)
        if request is None:
            raise NotFoundError("This verification link is invalid or has expired")

        now = datetime.now(tz=UTC)
        if row.revoked_at is not None:
            raise ConflictError("This verification link has been revoked")
        if row.expires_at <= now or request.status == VerificationRequestStatus.EXPIRED:
            raise ExpiredLinkError()

        if row.responded_at is not None:
            if row.response_action == action and dict(row.response_metadata or {}) == metadata:
                return await self.get_public_request(raw_token)
            raise ConflictError("This verification link has already been used")

        await self._transition_to_in_progress_if_needed(
            request,
            metadata,
            allowed_current_statuses={
                VerificationRequestStatus.ACCEPTED,
                VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE,
                VerificationRequestStatus.AWAITING_INFORMATION,
            },
        )

        if action == "confirm":
            await self._workflow.transition(
                request,
                target_status=VerificationRequestStatus.PENDING_ADMIN_QUALITY_REVIEW,
                actor_user_id=None,
                event_type="verification_response_received",
                event_source=VerificationRequestEventSource.ORGANIZATION,
                metadata={**metadata, "verifier_outcome": "confirmed"},
            )
            await self._notifications.create_and_dispatch_for_admin_roles(
                NotificationRequest(
                    event_type="admin_verification_quality_review_required",
                    channel="in_app",
                    template_key="admin_in_app",
                    dedupe_key=f"admin-quality-review-required:{request.public_id}",
                    payload={
                        "verification_request_public_id": str(request.public_id),
                        "subject_name": request.subject_name,
                        "organization_name": self._request_organization_name(request),
                        "request_type": (
                            request.request_type.value
                            if hasattr(request.request_type, "value")
                            else request.request_type
                        ),
                    },
                    metadata={
                        "verification_request_public_id": str(request.public_id),
                        "linked_record_type": (
                            "education" if request.education_id is not None else None
                        ),
                        "linked_record_id": str(request.education_id)
                        if request.education_id is not None
                        else None,
                    },
                )
            )
        elif action == "discrepancy":
            await self._workflow.transition(
                request,
                target_status=VerificationRequestStatus.PENDING_ADMIN_QUALITY_REVIEW,
                actor_user_id=None,
                event_type="verification_response_received",
                event_source=VerificationRequestEventSource.ORGANIZATION,
                metadata={**metadata, "verifier_outcome": "discrepancy"},
            )
            await self._notifications.create_and_dispatch_for_admin_roles(
                NotificationRequest(
                    event_type="admin_verification_quality_review_required",
                    channel="in_app",
                    template_key="admin_in_app",
                    dedupe_key=f"admin-quality-review-required:{request.public_id}",
                    payload={
                        "verification_request_public_id": str(request.public_id),
                        "subject_name": request.subject_name,
                        "organization_name": self._request_organization_name(request),
                        "request_type": (
                            request.request_type.value
                            if hasattr(request.request_type, "value")
                            else request.request_type
                        ),
                    },
                    metadata={
                        "verification_request_public_id": str(request.public_id),
                        "linked_record_type": (
                            "education" if request.education_id is not None else None
                        ),
                        "linked_record_id": str(request.education_id)
                        if request.education_id is not None
                        else None,
                    },
                )
            )
        elif action == "clarification":
            await self._workflow.transition(
                request,
                target_status=VerificationRequestStatus.AWAITING_INFORMATION,
                actor_user_id=None,
                event_type="verification_request_information_requested",
                event_source=VerificationRequestEventSource.ORGANIZATION,
                metadata=metadata,
            )
        else:
            raise ValidationAppError("Unsupported institution verification action")

        row.responded_at = now
        row.response_action = action
        row.response_note = metadata.get("note") if isinstance(metadata.get("note"), str) else None
        row.response_metadata = metadata
        await self._session.commit()
        return await self.get_public_request(raw_token)

    async def _transition_to_in_progress_if_needed(
        self,
        request: VerificationRequest,
        metadata: dict[str, object],
        *,
        allowed_current_statuses: set[VerificationRequestStatus],
    ) -> None:
        if request.status in allowed_current_statuses:
            await self._workflow.transition(
                request,
                target_status=VerificationRequestStatus.IN_PROGRESS,
                actor_user_id=None,
                event_type="verification_request_started",
                event_source=VerificationRequestEventSource.ORGANIZATION,
                metadata=metadata,
            )

    async def _load_by_token(
        self,
        raw_token: str,
        *,
        allow_missing: bool,
    ) -> InstitutionVerificationRequest | None:
        if not raw_token or len(raw_token) < 16:
            if allow_missing:
                return None
            raise NotFoundError("This verification link is invalid or has expired")
        row = await self._public_requests.get_by_token_hash(hash_refresh_token(raw_token))
        if row is None and not allow_missing:
            raise NotFoundError("This verification link is invalid or has expired")
        return row

    def _derive_state(
        self,
        row: InstitutionVerificationRequest,
        request: VerificationRequest,
    ) -> str:
        if row.revoked_at is not None:
            return "revoked"
        if row.responded_at is not None or request.status in _COMPLETED_PUBLIC_REQUEST_STATUSES:
            return "completed"
        if (
            row.expires_at <= datetime.now(tz=UTC)
            or request.status == VerificationRequestStatus.EXPIRED
        ):
            return "expired"
        return "valid"

    async def _build_request_projection(
        self,
        request: VerificationRequest,
    ) -> PublicInstitutionVerificationRequestProjection:
        education = await self._education.get_active_by_id(request.education_id)
        organization_name = self._request_organization_name(request)
        if education is None:
            raise NotFoundError("Education record not found")

        evidence_items = await self._evidence.list_for_request(request.id)
        visible_evidence = self._verification_service._filter_evidence_by_consent(  # noqa: SLF001
            request,
            evidence_items,
        )
        evidence = [
            await self._verification_service._to_evidence_response(  # noqa: SLF001
                item,
                include_download_url=True,
            )
            for item in visible_evidence
        ]

        return PublicInstitutionVerificationRequestProjection(
            reference=f"VR-{str(request.public_id).split('-', 1)[0].upper()}",
            requested_by=organization_name,
            purpose=f"{request.request_type.value.replace('_', ' ').title()} verification request",
            request_date=request.created_at,
            consent_received=request.consented_at is not None,
            candidate=PublicInstitutionVerificationCandidateClaim(
                candidate_name=request.subject_name,
                institution_name=education.institution_name or "Not provided",
                degree=education.degree or "Not provided",
                programme=education.field_of_study or "Not provided",
                department="Not provided",
                admission_year=self._format_period(education.start_date),
                graduation_year=self._format_period(education.end_date),
                completion_status="completed" if education.end_date is not None else "ongoing",
                additional_note=request.candidate_response,
            ),
            evidence=[
                PublicInstitutionVerificationEvidenceFile(
                    id=str(item.public_id),
                    name=item.original_filename or item.field_key,
                    type=item.document_type or item.evidence_type,
                    uploaded_by="Request subject",
                    uploaded_at=item.created_at,
                    url=item.download_url,
                )
                for item in evidence
            ],
        )

    def _request_organization_name(self, request: VerificationRequest) -> str:
        return request.target_organization_name or "Kairo"

    @staticmethod
    def _format_period(value) -> str:  # noqa: ANN001
        if value is None:
            return "Not provided"
        return value.isoformat()

    @staticmethod
    def _normalize_metadata(
        *,
        note: str | None = None,
        fields: list[str] | None = None,
        request_document: bool | None = None,
    ) -> dict[str, object]:
        normalized_fields: list[str] = []
        if fields:
            seen: set[str] = set()
            for field in fields:
                cleaned = field.strip()
                if not cleaned or cleaned in seen:
                    continue
                normalized_fields.append(cleaned)
                seen.add(cleaned)
        metadata: dict[str, object] = {}
        if note and note.strip():
            metadata["note"] = note.strip()
        if normalized_fields:
            metadata["fields"] = normalized_fields
        if request_document is not None:
            metadata["request_document"] = request_document
        return metadata
