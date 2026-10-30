"""Organization-scoped HR V2 lifecycle, configuration, and report projection."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.config import Settings
from app.core.permissions import Permission, has_permission
from app.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
from app.infrastructure.s3.presign import generate_presigned_get_url
from app.infrastructure.s3.service import S3UploadService
from app.models.court_record_check import CourtRecordCheck
from app.models.digilocker_identity_verification import DigiLockerIdentityVerification
from app.models.employment_reference import EmploymentReference, EmploymentReferenceEvent
from app.models.organization import Organization
from app.models.organization_activity_event import OrganizationActivityEvent
from app.models.organization_job_role import OrganizationJobRole
from app.models.organization_logo_upload import OrganizationLogoUpload
from app.models.organization_person import OrganizationPerson
from app.models.organization_person_correction import OrganizationPersonCorrection
from app.models.permanent_address import PermanentAddressSession, PermanentAddressVersion
from app.models.trust_invitation import TrustInvitation
from app.models.trust_score_snapshot import TrustScoreSnapshot
from app.models.user import User
from app.models.verification_request import VerificationRequest
from app.organization.permissions import is_organization_manager
from app.organization_people.enums import (
    OrganizationPersonEmploymentStatus,
    OrganizationPersonRelationship,
)
from app.repositories.organization_person import OrganizationPersonRepository
from app.schemas.hr_v2 import (
    DEFAULT_VERIFICATION_PREFERENCES,
    EmployeeLifecycleResponse,
    EmployeeLifecycleUpdateRequest,
    FormerEmployeeCorrectionCreateRequest,
    FormerEmployeeCorrectionDecisionRequest,
    FormerEmployeeCorrectionResponse,
    HiringRoleDecisionRequest,
    OrganizationJobRoleCreateRequest,
    OrganizationJobRoleResponse,
    OrganizationJobRoleUpdateRequest,
    OrganizationLogoConfirmRequest,
    OrganizationLogoResponse,
    OrganizationLogoUploadIntentRequest,
    OrganizationLogoUploadIntentResponse,
    OrganizationRoleAssignmentRequest,
    OrganizationRoleAssignmentResponse,
    OrganizationVerificationPreferencesResponse,
    OrganizationVerificationPreferencesUpdateRequest,
    VerificationReportAddressItem,
    VerificationReportCheckStatus,
    VerificationReportCheckSummary,
    VerificationReportCourtSearchItem,
    VerificationReportEducationItem,
    VerificationReportEmploymentItem,
    VerificationReportHeader,
    VerificationReportIdentityItem,
    VerificationReportOpenItem,
    VerificationReportReferenceItem,
    VerificationReportResponse,
    VerificationReportStatus,
    normalize_role_name,
)
from app.services.organization_service import OrganizationService
from app.trust_invitations.enums import TrustInvitationStatus
from app.verification_requests.enums import VerificationRequestStatus, VerificationRequestType

_LOGO_CONTENT_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
_LOGO_MAX_BYTES = 5_000_000
_LOGO_UPLOAD_TTL = timedelta(minutes=10)
_LOGO_READ_TTL_SECONDS = 300
_REPORT_CHECKS = (
    "identity",
    "employment",
    "education",
    "references",
    "address",
    "court_record_search",
)


class HRV2Service:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._organizations = OrganizationService(session)
        self._people = OrganizationPersonRepository(session)
        self._storage = S3UploadService(settings)

    async def update_employee_lifecycle(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        person_public_id: UUID,
        payload: EmployeeLifecycleUpdateRequest,
    ) -> EmployeeLifecycleResponse:
        organization, membership = await self._organizations.require_org_member(
            actor_user_id, org_public_id
        )
        self._assert_active_access(organization, membership)
        person = await self._locked_person(organization.id, person_public_id)

        current = OrganizationPersonEmploymentStatus(person.employment_status)
        if current == OrganizationPersonEmploymentStatus.EX_EMPLOYEE:
            if payload.employment_status == OrganizationPersonEmploymentStatus.ACTIVE:
                raise ConflictError(
                    "Reactivation is not supported in HR V2 V1 because historical exit data "
                    "requires a deliberate rehire lifecycle"
                )
            raise ConflictError(
                "Former-employee history is immutable; request an audited correction"
            )
        if payload.employment_status == OrganizationPersonEmploymentStatus.EX_EMPLOYEE:
            if payload.last_working_day is None:
                raise ValidationAppError("last_working_day is required for an ex-employee")
            if payload.last_working_day > date.today():
                raise ValidationAppError("last_working_day cannot be in the future")
            if person.joining_date is not None and payload.last_working_day < person.joining_date:
                raise ValidationAppError("last_working_day cannot be before joining_date")
            person.employment_status = OrganizationPersonEmploymentStatus.EX_EMPLOYEE.value
            person.last_working_day = payload.last_working_day
            person.relationship = OrganizationPersonRelationship.FORMER_EMPLOYEE
            await self._record_event(
                organization.id,
                actor_user_id,
                "employee_marked_ex_employee",
                "organization_person",
                person.public_id,
                {"last_working_day": payload.last_working_day.isoformat()},
            )
        elif current != payload.employment_status:
            person.employment_status = payload.employment_status.value

        await self._session.commit()
        await self._session.refresh(person)
        return EmployeeLifecycleResponse(
            person_public_id=person.public_id,
            employment_status=OrganizationPersonEmploymentStatus(person.employment_status),
            last_working_day=person.last_working_day,
            updated_at=person.updated_at,
        )

    async def list_roles(
        self, actor_user_id: UUID, org_public_id: UUID
    ) -> list[OrganizationJobRoleResponse]:
        organization, membership = await self._organizations.require_org_member(
            actor_user_id, org_public_id
        )
        self._assert_active_access(organization, membership)
        rows = await self._session.execute(
            select(OrganizationJobRole, func.count(OrganizationPerson.id))
            .outerjoin(OrganizationPerson, OrganizationPerson.role_id == OrganizationJobRole.id)
            .where(OrganizationJobRole.organization_id == organization.id)
            .group_by(OrganizationJobRole.id)
            .order_by(OrganizationJobRole.name.asc())
        )
        return [self._role_response(role, int(count)) for role, count in rows.all()]

    async def create_role(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        payload: OrganizationJobRoleCreateRequest,
    ) -> OrganizationJobRoleResponse:
        organization, membership = await self._organizations.require_org_member(
            actor_user_id, org_public_id
        )
        self._assert_active_access(organization, membership)
        normalized = normalize_role_name(payload.name)
        await self._assert_unique_role_name(organization.id, normalized)
        role = OrganizationJobRole(
            organization_id=organization.id,
            name=" ".join(payload.name.split()),
            normalized_name=normalized,
            description=payload.description,
            department=payload.department,
            location=payload.location,
            work_mode=payload.work_mode,
            status=(
                "draft"
                if payload.mode == "draft"
                else "active"
                if is_organization_manager(membership.role)
                else "pending_approval"
            ),
            is_active=payload.mode != "draft" and is_organization_manager(membership.role),
            created_by_user_id=actor_user_id,
            approved_by_user_id=(
                actor_user_id
                if is_organization_manager(membership.role) and payload.mode == "submit"
                else None
            ),
            approved_at=(
                datetime.now(tz=UTC)
                if is_organization_manager(membership.role) and payload.mode == "submit"
                else None
            ),
        )
        self._session.add(role)
        await self._session.flush()
        await self._record_event(
            organization.id, actor_user_id, "role_created", "organization_job_role", role.public_id
        )
        await self._session.commit()
        await self._session.refresh(role)
        return self._role_response(role, 0)

    async def update_role(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        role_public_id: UUID,
        payload: OrganizationJobRoleUpdateRequest,
    ) -> OrganizationJobRoleResponse:
        organization, _ = await self._organizations.require_org_manager(
            actor_user_id, org_public_id
        )
        role = await self._role(organization.id, role_public_id)
        if payload.name is not None:
            normalized = normalize_role_name(payload.name)
            await self._assert_unique_role_name(organization.id, normalized, exclude_id=role.id)
            role.name = " ".join(payload.name.split())
            role.normalized_name = normalized
        if "description" in payload.model_fields_set:
            role.description = payload.description
        for field in ("department", "location", "work_mode"):
            if field in payload.model_fields_set:
                setattr(role, field, getattr(payload, field))
        if payload.is_active is not None:
            role.is_active = payload.is_active
            if payload.is_active:
                role.status = "active"
                role.archived_at = None
                role.approved_by_user_id = actor_user_id
                role.approved_at = role.approved_at or datetime.now(tz=UTC)
            else:
                role.status = "archived"
                role.archived_at = datetime.now(tz=UTC)
        await self._record_event(
            organization.id, actor_user_id, "role_updated", "organization_job_role", role.public_id
        )
        await self._session.commit()
        await self._session.refresh(role)
        count = await self._role_assignment_count(role.id)
        return self._role_response(role, count)

    async def approve_role(
        self, actor_user_id: UUID, org_public_id: UUID, role_public_id: UUID
    ) -> OrganizationJobRoleResponse:
        organization, _ = await self._organizations.require_org_manager(
            actor_user_id, org_public_id
        )
        role = await self._role(organization.id, role_public_id)
        if role.status not in {"draft", "pending_approval", "rejected"}:
            raise ConflictError("Hiring role is not awaiting approval")
        now = datetime.now(tz=UTC)
        role.status = "active"
        role.is_active = True
        role.approved_by_user_id = actor_user_id
        role.approved_at = now
        role.rejected_at = None
        await self._record_event(
            organization.id,
            actor_user_id,
            "hiring_role_approved",
            "organization_job_role",
            role.public_id,
        )
        await self._session.commit()
        await self._session.refresh(role)
        return self._role_response(role, await self._role_assignment_count(role.id))

    async def reject_role(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        role_public_id: UUID,
        payload: HiringRoleDecisionRequest,
    ) -> OrganizationJobRoleResponse:
        organization, _ = await self._organizations.require_org_manager(
            actor_user_id, org_public_id
        )
        role = await self._role(organization.id, role_public_id)
        if role.status != "pending_approval":
            raise ConflictError("Only pending Hiring Roles can be rejected")
        role.status = "rejected"
        role.is_active = False
        role.rejected_at = datetime.now(tz=UTC)
        await self._record_event(
            organization.id,
            actor_user_id,
            "hiring_role_rejected",
            "organization_job_role",
            role.public_id,
            {"reason": payload.reason} if payload.reason else None,
        )
        await self._session.commit()
        await self._session.refresh(role)
        return self._role_response(role, await self._role_assignment_count(role.id))

    async def deactivate_role(
        self, actor_user_id: UUID, org_public_id: UUID, role_public_id: UUID
    ) -> OrganizationJobRoleResponse:
        organization, _ = await self._organizations.require_org_manager(
            actor_user_id, org_public_id
        )
        role = await self._role(organization.id, role_public_id)
        role.is_active = False
        role.status = "archived"
        role.archived_at = datetime.now(tz=UTC)
        await self._record_event(
            organization.id,
            actor_user_id,
            "role_deactivated",
            "organization_job_role",
            role.public_id,
        )
        await self._session.commit()
        await self._session.refresh(role)
        return self._role_response(role, await self._role_assignment_count(role.id))

    async def assign_role(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        person_public_id: UUID,
        payload: OrganizationRoleAssignmentRequest,
    ) -> OrganizationRoleAssignmentResponse:
        organization, membership = await self._organizations.require_org_member(
            actor_user_id, org_public_id
        )
        self._assert_active_access(organization, membership)
        person = await self._locked_person(organization.id, person_public_id)
        if (
            OrganizationPersonEmploymentStatus(getattr(person, "employment_status", "active"))
            == OrganizationPersonEmploymentStatus.EX_EMPLOYEE
        ):
            raise ConflictError(
                "Former-employee history is immutable; request an audited correction"
            )
        joining_date = (
            payload.joining_date
            if "joining_date" in payload.model_fields_set
            else person.joining_date
        )
        if (
            joining_date is not None
            and person.last_working_day is not None
            and joining_date > person.last_working_day
        ):
            raise ValidationAppError("joining_date cannot be after last_working_day")
        role = None
        if payload.role_id is not None:
            role = await self._role(organization.id, payload.role_id)
            if not role.is_active:
                raise ConflictError("Inactive job roles cannot receive new assignments")
        if "role_id" in payload.model_fields_set:
            person.role_id = role.id if role is not None else None
        elif person.role_id is not None:
            role = await self._session.get(OrganizationJobRole, person.role_id)
        if "department" in payload.model_fields_set:
            person.department = payload.department
        if "joining_date" in payload.model_fields_set:
            person.joining_date = payload.joining_date
        await self._session.commit()
        return OrganizationRoleAssignmentResponse(
            person_public_id=person.public_id,
            role_id=role.public_id if role is not None else None,
            role=role.name if role is not None else None,
            department=person.department,
            joining_date=person.joining_date,
        )

    async def create_former_employee_correction(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        person_public_id: UUID,
        payload: FormerEmployeeCorrectionCreateRequest,
    ) -> FormerEmployeeCorrectionResponse:
        organization, membership = await self._organizations.require_org_member(
            actor_user_id, org_public_id
        )
        self._assert_active_access(organization, membership)
        person = await self._locked_person(organization.id, person_public_id)
        if (
            OrganizationPersonEmploymentStatus(person.employment_status)
            != OrganizationPersonEmploymentStatus.EX_EMPLOYEE
        ):
            raise ConflictError("Corrections are reserved for immutable former-employee history")
        proposed_changes = dict(payload.proposed_changes)
        if proposed_changes.get("role_id") is not None:
            role_public_id = UUID(str(proposed_changes["role_id"]))
            await self._role(organization.id, role_public_id)
        snapshot = await self._employment_snapshot(person)
        row = OrganizationPersonCorrection(
            organization_id=organization.id,
            organization_person_id=person.id,
            proposed_changes=proposed_changes,
            before_snapshot=snapshot,
            reason=payload.reason,
            requested_by_user_id=actor_user_id,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return self._correction_response(row, person.public_id)

    async def approve_former_employee_correction(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        correction_public_id: UUID,
        payload: FormerEmployeeCorrectionDecisionRequest,
    ) -> FormerEmployeeCorrectionResponse:
        organization, _ = await self._organizations.require_org_manager(
            actor_user_id, org_public_id
        )
        row = (
            await self._session.execute(
                select(OrganizationPersonCorrection)
                .where(
                    OrganizationPersonCorrection.organization_id == organization.id,
                    OrganizationPersonCorrection.public_id == correction_public_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Former-employee correction not found")
        if row.status != "pending":
            raise ConflictError("Correction has already been decided")
        person = await self._session.get(OrganizationPerson, row.organization_person_id)
        if (
            person is None
            or OrganizationPersonEmploymentStatus(person.employment_status)
            != OrganizationPersonEmploymentStatus.EX_EMPLOYEE
        ):
            raise ConflictError("Former-employee record is no longer eligible")
        changes = dict(row.proposed_changes)
        joining_date = self._correction_date(
            changes.get("joining_date"),
            person.joining_date,
            "joining_date" in changes,
        )
        last_working_day = self._correction_date(
            changes.get("last_working_day"),
            person.last_working_day,
            "last_working_day" in changes,
        )
        if (
            joining_date is not None
            and last_working_day is not None
            and joining_date > last_working_day
        ):
            raise ValidationAppError("joining_date cannot be after last_working_day")
        resolved_role_id = person.role_id
        if "role_id" in changes:
            role_public_id = changes.pop("role_id")
            if role_public_id is None:
                resolved_role_id = None
            else:
                role = await self._role(organization.id, UUID(str(role_public_id)))
                resolved_role_id = role.id
        person.role_id = resolved_role_id
        self._apply_employment_correction(person, changes)
        row.after_snapshot = await self._employment_snapshot(person)
        row.status = "approved"
        row.decided_by_user_id = actor_user_id
        row.decided_at = datetime.now(tz=UTC)
        row.decision_reason = payload.decision_reason
        await self._record_event(
            organization.id,
            actor_user_id,
            "former_employee_correction_approved",
            "organization_person",
            person.public_id,
            {"correction_public_id": str(row.public_id)},
        )
        person_public_id = person.public_id
        await self._session.commit()
        await self._session.refresh(row)
        return self._correction_response(row, person_public_id)

    async def reject_former_employee_correction(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        correction_public_id: UUID,
        payload: FormerEmployeeCorrectionDecisionRequest,
    ) -> FormerEmployeeCorrectionResponse:
        organization, _ = await self._organizations.require_org_manager(
            actor_user_id, org_public_id
        )
        row = (
            await self._session.execute(
                select(OrganizationPersonCorrection)
                .where(
                    OrganizationPersonCorrection.organization_id == organization.id,
                    OrganizationPersonCorrection.public_id == correction_public_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Former-employee correction not found")
        if row.status != "pending":
            raise ConflictError("Correction has already been decided")
        person = await self._session.get(OrganizationPerson, row.organization_person_id)
        if person is None:
            raise NotFoundError("Organization person not found")
        row.status = "rejected"
        row.decided_by_user_id = actor_user_id
        row.decided_at = datetime.now(tz=UTC)
        row.decision_reason = payload.decision_reason
        person_public_id = person.public_id
        await self._session.commit()
        await self._session.refresh(row)
        return self._correction_response(row, person_public_id)

    async def create_logo_upload_intent(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        payload: OrganizationLogoUploadIntentRequest,
    ) -> OrganizationLogoUploadIntentResponse:
        organization, _ = await self._organizations.require_org_manager(
            actor_user_id, org_public_id
        )
        content_type = payload.content_type.split(";", 1)[0].strip().lower()
        extension = _LOGO_CONTENT_TYPES.get(content_type)
        if extension is None:
            raise ValidationAppError("Organization logos must be PNG, JPEG, or WEBP")
        if payload.byte_size > _LOGO_MAX_BYTES:
            raise ValidationAppError("Organization logo exceeds the 5 MB limit")
        upload_id = uuid.uuid4()
        prefix = self._settings.s3_document_key_prefix.strip("/")
        object_key = f"{prefix}/organizations/{organization.id}/logo/{upload_id}.{extension}"
        intent = OrganizationLogoUpload(
            id=upload_id,
            public_id=upload_id,
            organization_id=organization.id,
            created_by_user_id=actor_user_id,
            object_key=object_key,
            content_type=content_type,
            byte_size=payload.byte_size,
            expires_at=datetime.now(tz=UTC) + _LOGO_UPLOAD_TTL,
        )
        self._session.add(intent)
        upload_url, ttl = await self._storage.presign_put_url(
            object_key=object_key,
            content_type=content_type,
            ttl_seconds=int(_LOGO_UPLOAD_TTL.total_seconds()),
        )
        await self._session.commit()
        return OrganizationLogoUploadIntentResponse(
            upload_id=intent.public_id,
            upload_url=upload_url,
            expires_in_seconds=ttl,
            headers_required={"Content-Type": content_type},
        )

    async def confirm_logo(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        payload: OrganizationLogoConfirmRequest,
    ) -> OrganizationLogoResponse:
        organization, _ = await self._organizations.require_org_manager(
            actor_user_id, org_public_id
        )
        intent = (
            await self._session.execute(
                select(OrganizationLogoUpload)
                .where(
                    OrganizationLogoUpload.organization_id == organization.id,
                    OrganizationLogoUpload.public_id == payload.upload_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if intent is None:
            raise NotFoundError("Organization logo upload not found")
        if intent.completed_at is not None:
            raise ConflictError("Organization logo upload has already been confirmed")
        if intent.expires_at <= datetime.now(tz=UTC):
            raise ConflictError("Organization logo upload has expired")
        await self._storage.verify_upload_matches_intent(
            object_key=intent.object_key,
            expected_byte_size=intent.byte_size,
            declared_content_type=intent.content_type,
        )
        previous_key = organization.logo_object_key
        organization.logo_object_key = intent.object_key
        organization.logo_content_type = intent.content_type
        organization.logo_byte_size = intent.byte_size
        intent.completed_at = datetime.now(tz=UTC)
        await self._record_event(
            organization.id,
            actor_user_id,
            "organization_logo_changed",
            "organization",
            organization.public_id,
        )
        await self._session.commit()
        if previous_key and previous_key != intent.object_key:
            await self._storage.delete_object_best_effort(object_key=previous_key)
        return await self._logo_response(organization)

    async def get_logo(self, actor_user_id: UUID, org_public_id: UUID) -> OrganizationLogoResponse:
        organization, membership = await self._organizations.require_org_member(
            actor_user_id, org_public_id
        )
        self._assert_active_access(organization, membership)
        return await self._logo_response(organization)

    async def remove_logo(
        self, actor_user_id: UUID, org_public_id: UUID
    ) -> OrganizationLogoResponse:
        organization, _ = await self._organizations.require_org_manager(
            actor_user_id, org_public_id
        )
        previous_key = organization.logo_object_key
        organization.logo_object_key = None
        organization.logo_content_type = None
        organization.logo_byte_size = None
        await self._record_event(
            organization.id,
            actor_user_id,
            "organization_logo_changed",
            "organization",
            organization.public_id,
            {"action": "removed"},
        )
        await self._session.commit()
        if previous_key:
            await self._storage.delete_object_best_effort(object_key=previous_key)
        return OrganizationLogoResponse(has_logo=False, updated_at=organization.updated_at)

    async def get_preferences(
        self, actor_user_id: UUID, org_public_id: UUID
    ) -> OrganizationVerificationPreferencesResponse:
        organization, membership = await self._organizations.require_org_member(
            actor_user_id, org_public_id
        )
        self._assert_active_access(organization, membership)
        return self._preferences_response(
            organization.verification_preferences, organization.updated_at
        )

    async def update_preferences(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        payload: OrganizationVerificationPreferencesUpdateRequest,
    ) -> OrganizationVerificationPreferencesResponse:
        organization, _ = await self._organizations.require_org_manager(
            actor_user_id, org_public_id
        )
        preferences = {
            "version": 1,
            "checks": dict(payload.checks),
            "reference_count": payload.reference_count,
        }
        organization.verification_preferences = preferences
        await self._record_event(
            organization.id,
            actor_user_id,
            "verification_preferences_changed",
            "organization",
            organization.public_id,
            {"enabled_checks": sorted(k for k, enabled in payload.checks.items() if enabled)},
        )
        await self._session.commit()
        await self._session.refresh(organization)
        return self._preferences_response(preferences, organization.updated_at)

    async def get_verification_report(
        self, actor_user_id: UUID, org_public_id: UUID, person_public_id: UUID
    ) -> VerificationReportResponse:
        organization, membership = await self._organizations.require_org_member(
            actor_user_id, org_public_id
        )
        self._assert_active_access(organization, membership)
        person = await self._people.get_by_public_id(
            organization.id, person_public_id, load_related=True
        )
        if person is None:
            raise NotFoundError("Organization person not found")

        return await self._build_verification_report(organization, person)

    async def get_admin_verification_report(
        self, actor_user_id: UUID, org_public_id: UUID, person_public_id: UUID
    ) -> VerificationReportResponse:
        actor = await self._session.get(User, actor_user_id)
        if (
            actor is None
            or not actor.is_active
            or actor.deleted_at is not None
            or not has_permission(actor.role, Permission.READ_USERS)
        ):
            raise ForbiddenError("Insufficient permissions")
        organization = await self._session.scalar(
            select(Organization).where(Organization.public_id == org_public_id)
        )
        if organization is None:
            raise NotFoundError("Organization person not found")
        person = await self._people.get_by_public_id(
            organization.id, person_public_id, load_related=True
        )
        if person is None:
            raise NotFoundError("Organization person not found")
        return await self._build_verification_report(organization, person)

    async def _build_verification_report(
        self, organization: Organization, person: OrganizationPerson
    ) -> VerificationReportResponse:
        # Internal consumers only. External Passport/export projections use their
        # own allowlists and must never serialize this reference-comment report.
        requests = await self._report_requests(organization.id, person.id)
        invitations = list(
            (
                await self._session.scalars(
                    select(TrustInvitation).where(
                        TrustInvitation.organization_id == organization.id,
                        TrustInvitation.organization_person_id == person.id,
                        TrustInvitation.status.in_(
                            [
                                TrustInvitationStatus.PENDING,
                                TrustInvitationStatus.ACCEPTED,
                            ]
                        ),
                    )
                )
            ).all()
        )
        ordered = self._ordered_report_checks(requests, invitations)
        score = await self._latest_trust_score(person.linked_user_id)
        identity = await self._identity_items(person, requests) if "identity" in ordered else []
        employment = self._employment_items(requests)
        education = self._education_items(requests)
        references = await self._reference_items(requests, require_pair="references" in ordered)
        address = await self._address_items(person.linked_user_id) if "address" in ordered else []
        court_search, court_checks = await self._court_items(organization.id, person)
        summaries = self._check_summaries(
            requests, identity, employment, education, references, address, court_search, ordered
        )
        report_status, open_items, review_required = self._report_finality(
            requests, summaries, ordered
        )
        initiated_at = min(
            [
                *(request.created_at for request in requests),
                *(check.created_at for check in court_checks),
            ],
            default=person.added_at,
        )
        report_updated_at = max(
            [
                person.updated_at,
                *(request.updated_at for request in requests),
                *(check.updated_at for check in court_checks),
            ],
        )
        consent_at = max(
            (request.consented_at for request in requests if request.consented_at is not None),
            default=None,
        )
        role_name = person.job_role.name if person.job_role is not None else None
        return VerificationReportResponse(
            header=VerificationReportHeader(
                person_name=person.full_name,
                role=role_name,
                person_id=person.public_id,
                initiated_at=initiated_at,
                requested_by_organization=organization.name,
                masked_email=self._mask_email(person.primary_email),
                masked_phone=self._mask_phone(person.primary_phone),
                consent_at=consent_at,
                trust_score=score.overall_score if score is not None else None,
                report_updated_at=report_updated_at,
                report_status=report_status,
            ),
            check_summaries=summaries,
            identity=identity,
            employment=employment,
            education=education,
            references=references,
            address=address,
            court_search=court_search or [VerificationReportCourtSearchItem()],
            open_items=open_items,
            hr_review_required=review_required,
            metadata={"generated_at": datetime.now(tz=UTC).isoformat()},
        )

    async def _locked_person(
        self, organization_id: UUID, person_public_id: UUID
    ) -> OrganizationPerson:
        person = (
            await self._session.execute(
                select(OrganizationPerson)
                .where(
                    OrganizationPerson.organization_id == organization_id,
                    OrganizationPerson.public_id == person_public_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if person is None:
            raise NotFoundError("Organization person not found")
        return person

    async def _role(self, organization_id: UUID, role_public_id: UUID) -> OrganizationJobRole:
        role = (
            await self._session.execute(
                select(OrganizationJobRole).where(
                    OrganizationJobRole.organization_id == organization_id,
                    OrganizationJobRole.public_id == role_public_id,
                )
            )
        ).scalar_one_or_none()
        if role is None:
            raise NotFoundError("Organization job role not found")
        return role

    async def _assert_unique_role_name(
        self, organization_id: UUID, normalized_name: str, *, exclude_id: UUID | None = None
    ) -> None:
        stmt = select(OrganizationJobRole.id).where(
            OrganizationJobRole.organization_id == organization_id,
            OrganizationJobRole.normalized_name == normalized_name,
        )
        if exclude_id is not None:
            stmt = stmt.where(OrganizationJobRole.id != exclude_id)
        if (await self._session.execute(stmt)).scalar_one_or_none() is not None:
            raise ConflictError("A job role with this normalized name already exists")

    async def _role_assignment_count(self, role_id: UUID) -> int:
        return int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(OrganizationPerson)
                    .where(OrganizationPerson.role_id == role_id)
                )
            ).scalar_one()
        )

    def _role_response(self, role: OrganizationJobRole, count: int) -> OrganizationJobRoleResponse:
        return OrganizationJobRoleResponse(
            public_id=role.public_id,
            name=role.name,
            description=role.description,
            department=getattr(role, "department", None),
            location=getattr(role, "location", None),
            work_mode=getattr(role, "work_mode", None),
            status=getattr(role, "status", "active" if role.is_active else "archived"),
            created_by_user_id=getattr(role, "created_by_user_id", None),
            approved_by_user_id=getattr(role, "approved_by_user_id", None),
            approved_at=getattr(role, "approved_at", None),
            rejected_at=getattr(role, "rejected_at", None),
            archived_at=getattr(role, "archived_at", None),
            is_active=role.is_active,
            assigned_people_count=count,
            created_at=role.created_at,
            updated_at=role.updated_at,
        )

    async def _employment_snapshot(self, person: OrganizationPerson) -> dict[str, object]:
        role = (
            await self._session.get(OrganizationJobRole, person.role_id)
            if person.role_id is not None
            else None
        )
        return {
            "role_id": str(role.public_id) if role is not None else None,
            "department": person.department,
            "joining_date": person.joining_date.isoformat() if person.joining_date else None,
            "last_working_day": person.last_working_day.isoformat()
            if person.last_working_day
            else None,
        }

    @staticmethod
    def _apply_employment_correction(
        person: OrganizationPerson, changes: dict[str, object]
    ) -> None:
        for field, value in changes.items():
            if field in {"joining_date", "last_working_day"}:
                setattr(person, field, date.fromisoformat(str(value)) if value else None)
            else:
                setattr(person, field, value)

    @staticmethod
    def _correction_date(
        value: object, current: date | None, supplied: bool
    ) -> date | None:
        if not supplied:
            return current
        return date.fromisoformat(str(value)) if value else None

    @staticmethod
    def _correction_response(
        row: OrganizationPersonCorrection, person_public_id: UUID
    ) -> FormerEmployeeCorrectionResponse:
        return FormerEmployeeCorrectionResponse(
            public_id=row.public_id,
            person_public_id=person_public_id,
            proposed_changes=row.proposed_changes,
            before_snapshot=row.before_snapshot,
            after_snapshot=row.after_snapshot,
            reason=row.reason,
            status=row.status,
            requested_by_user_id=row.requested_by_user_id,
            decided_by_user_id=row.decided_by_user_id,
            decided_at=row.decided_at,
            decision_reason=row.decision_reason,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def _logo_response(self, organization) -> OrganizationLogoResponse:  # noqa: ANN001
        if not organization.logo_object_key:
            return OrganizationLogoResponse(has_logo=False, updated_at=organization.updated_at)
        bucket = self._settings.s3_documents_bucket
        if not bucket:
            raise ValidationAppError("Organization logo display is not configured")
        url = await generate_presigned_get_url(
            bucket=bucket,
            object_key=organization.logo_object_key,
            ttl_seconds=_LOGO_READ_TTL_SECONDS,
            settings=self._settings,
        )
        return OrganizationLogoResponse(
            has_logo=True,
            display_url=url,
            display_url_expires_in_seconds=_LOGO_READ_TTL_SECONDS,
            content_type=organization.logo_content_type,
            byte_size=organization.logo_byte_size,
            updated_at=organization.updated_at,
        )

    def _preferences_response(
        self, raw: dict[str, object] | None, updated_at: datetime | None
    ) -> OrganizationVerificationPreferencesResponse:
        defaults = DEFAULT_VERIFICATION_PREFERENCES
        raw = raw or {}
        checks = dict(defaults["checks"])
        if isinstance(raw.get("checks"), dict):
            checks.update({str(key): bool(value) for key, value in raw["checks"].items()})
        return OrganizationVerificationPreferencesResponse(
            version=int(raw.get("version", 1)),
            checks=checks,
            reference_count=int(raw.get("reference_count", 0)),
            updated_at=updated_at,
        )

    async def _report_requests(
        self, organization_id: UUID, person_id: UUID
    ) -> list[VerificationRequest]:
        rows = await self._session.execute(
            select(VerificationRequest)
            .options(
                joinedload(VerificationRequest.organization),
                joinedload(VerificationRequest.employment),
                joinedload(VerificationRequest.education),
                selectinload(VerificationRequest.evidence_items),
                selectinload(VerificationRequest.connector_runs),
                selectinload(VerificationRequest.verification_contacts),
            )
            .where(
                VerificationRequest.organization_id == organization_id,
                VerificationRequest.organization_person_id == person_id,
            )
            .order_by(VerificationRequest.created_at.asc())
        )
        return list(rows.scalars().unique().all())

    async def _latest_trust_score(self, user_id: UUID | None) -> TrustScoreSnapshot | None:
        if user_id is None:
            return None
        return (
            await self._session.execute(
                select(TrustScoreSnapshot)
                .where(TrustScoreSnapshot.user_id == user_id)
                .order_by(TrustScoreSnapshot.calculated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def _identity_items(
        self, person: OrganizationPerson, requests: list[VerificationRequest]
    ) -> list[VerificationReportIdentityItem]:
        identity_requests = [
            r for r in requests if r.request_type == VerificationRequestType.IDENTITY
        ]
        rows: list[DigiLockerIdentityVerification] = []
        if person.linked_user_id is not None:
            result = await self._session.execute(
                select(DigiLockerIdentityVerification)
                .where(DigiLockerIdentityVerification.user_id == person.linked_user_id)
                .order_by(DigiLockerIdentityVerification.created_at.desc())
            )
            rows = list(result.scalars().all())
        if rows:
            return [
                VerificationReportIdentityItem(
                    declared_values={"name": person.full_name},
                    verified_values={
                        "document_type": row.document_type,
                        "issuer": row.issuer_name,
                    },
                    source="DigiLocker",
                    reviewed_at=row.verified_at or row.updated_at,
                    evidence_id=row.id,
                    status=self._identity_status(row.match_result),
                    remarks=self._safe_identity_remark(row.match_reason),
                )
                for row in rows
            ]
        return [
            VerificationReportIdentityItem(
                declared_values={"name": request.subject_name},
                status=self._request_status(request.status),
                reviewed_at=request.updated_at,
            )
            for request in identity_requests
        ]

    def _employment_items(
        self, requests: list[VerificationRequest]
    ) -> list[VerificationReportEmploymentItem]:
        items: list[VerificationReportEmploymentItem] = []
        for request in requests:
            if (
                request.request_type != VerificationRequestType.EMPLOYMENT
                or request.employment is None
            ):
                continue
            employment = request.employment
            confirmation = employment.employer_verification_request
            confirmed = (confirmation.response_metadata or {}) if confirmation is not None else {}
            items.append(
                VerificationReportEmploymentItem(
                    organization=employment.employer_legal_name,
                    masked_employee_id=self._mask_identifier(confirmed.get("employee_id")),
                    declared_title=employment.job_title,
                    confirmed_title=self._safe_text(confirmed.get("job_title")),
                    declared_start_date=employment.start_date,
                    declared_end_date=employment.end_date,
                    confirmed_start_date=self._parse_date(confirmed.get("start_date")),
                    confirmed_end_date=self._parse_date(confirmed.get("end_date")),
                    employment_type=employment.employment_type,
                    confirmed_by=confirmation.relationship_to_subject if confirmation else None,
                    source="employer_confirmation" if confirmation else "candidate_declaration",
                    received_at=confirmation.responded_at if confirmation else None,
                    evidence_id=confirmation.public_id if confirmation else None,
                    remarks=confirmation.remarks if confirmation else None,
                    status=self._request_status(request.status),
                )
            )
        return items

    def _education_items(
        self, requests: list[VerificationRequest]
    ) -> list[VerificationReportEducationItem]:
        items: list[VerificationReportEducationItem] = []
        for request in requests:
            if (
                request.request_type != VerificationRequestType.EDUCATION
                or request.education is None
            ):
                continue
            education = request.education
            items.append(
                VerificationReportEducationItem(
                    qualification=education.degree,
                    institution=education.institution_name,
                    completion_year=education.end_date.year if education.end_date else None,
                    declared_values={
                        "degree": education.degree,
                        "field_of_study": education.field_of_study,
                    },
                    confirmation_date=education.verified_at or education.reviewed_at,
                    status=self._request_status(request.status),
                )
            )
        return items

    async def _reference_items(
        self, requests: list[VerificationRequest], *, require_pair: bool = False
    ) -> list[VerificationReportReferenceItem]:
        employment_ids = {
            r.employment_id
            for r in requests
            if r.employment_id is not None
            and getattr(r, "status", None)
            not in {
                VerificationRequestStatus.CANCELLED,
                VerificationRequestStatus.WITHDRAWN_BY_CANDIDATE,
            }
        }
        if not employment_ids:
            return []
        result = await self._session.execute(
            select(EmploymentReference)
            .where(
                EmploymentReference.employment_id.in_(employment_ids),
                EmploymentReference.active.is_(True),
            )
            .order_by(EmploymentReference.created_at.asc())
        )
        references = list(result.scalars().all())
        events_by_reference: dict[UUID, list[datetime]] = {}
        if references:
            event_result = await self._session.execute(
                select(EmploymentReferenceEvent).where(
                    EmploymentReferenceEvent.reference_id.in_([r.id for r in references]),
                    EmploymentReferenceEvent.event.in_(
                        ["resent", "reminder_sent", "follow_up_sent"]
                    ),
                )
            )
            for event in event_result.scalars().all():
                events_by_reference.setdefault(event.reference_id, []).append(event.created_at)
        items = [
            VerificationReportReferenceItem(
                name=self._safe_text(
                    (row.nomination or {}).get("full_name") or (row.nomination or {}).get("name")
                ),
                title_or_relationship=self._safe_text(
                    (row.nomination or {}).get("designation")
                    or (row.nomination or {}).get("title")
                    or (row.nomination or {}).get("relationship")
                ),
                organization=self._safe_text((row.nomination or {}).get("organization")),
                known_for=self._safe_text((row.answers or {}).get("known_for")),
                request_date=row.nominated_at,
                follow_up_dates=events_by_reference.get(row.id, []),
                response_date=row.completed_at,
                status=self._reference_status(row.status),
                strengths=self._safe_text(
                    (row.answers or {}).get("key_strength") or (row.answers or {}).get("strengths")
                ),
                development_areas=self._safe_text((row.answers or {}).get("development_areas")),
                rehire_response=self._safe_text(
                    (row.answers or {}).get("eligible_for_rehire")
                    or (row.answers or {}).get("rehire_response")
                ),
                comments=self._safe_text(
                    (row.answers or {}).get("additional_comments")
                    or (row.answers or {}).get("comments")
                ),
                evidence_id=row.id,
            )
            for row in references
        ]
        if require_pair:
            present = {(row.employment_id, row.kind) for row in references}
            for employment_id in sorted(employment_ids, key=str):
                for kind in ("hr_reference", "reporting_manager_reference"):
                    if (employment_id, kind) not in present:
                        items.append(
                            VerificationReportReferenceItem(
                                title_or_relationship=(
                                    "HR reference"
                                    if kind == "hr_reference"
                                    else "Reporting manager"
                                ),
                                status=VerificationReportCheckStatus.PENDING,
                            )
                        )
        return items

    async def _address_items(self, user_id: UUID | None) -> list[VerificationReportAddressItem]:
        if user_id is None:
            return []
        address = (
            await self._session.execute(
                select(PermanentAddressVersion)
                .where(PermanentAddressVersion.user_id == user_id)
                .order_by(PermanentAddressVersion.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if address is None:
            return []
        sessions = (
            (
                await self._session.execute(
                    select(PermanentAddressSession).where(
                        PermanentAddressSession.address_version_id == address.id
                    )
                )
            )
            .scalars()
            .all()
        )
        physical_visit = any(
            bool((session.derived_evidence or {}).get("onsite")) for session in sessions
        )
        return [
            VerificationReportAddressItem(
                declared_address=self._display_address(address.claimed_address),
                verification_method=address.target_source or "document",
                verified_at=address.completed_at or address.target_confirmed_at,
                status=(
                    VerificationReportCheckStatus.CONFIRMED
                    if address.completed_at is not None
                    else VerificationReportCheckStatus.PENDING
                ),
                scope="Permanent address evidence only; no location coordinates are disclosed",
                physical_visit_performed=physical_visit,
                evidence_id=address.id,
            )
        ]

    async def _court_items(
        self, organization_id: UUID, person: OrganizationPerson
    ) -> tuple[list[VerificationReportCourtSearchItem], list[CourtRecordCheck]]:
        # A few contract-level tests construct the service around repository fakes only.
        # Production instances always have a session; retaining the empty projection keeps
        # those pre-existing seams backwards compatible.
        if not hasattr(self, "_session"):
            return [], []
        rows = list(
            (
                await self._session.scalars(
                    select(CourtRecordCheck)
                    .options(selectinload(CourtRecordCheck.evidence_items))
                    .where(
                        CourtRecordCheck.organization_id == organization_id,
                        CourtRecordCheck.organization_person_id == person.id,
                    )
                    .order_by(CourtRecordCheck.created_at.asc())
                )
            ).all()
        )
        reviewer_ids = {row.reviewer_user_id for row in rows if row.reviewer_user_id is not None}
        reviewers = {}
        if reviewer_ids:
            reviewer_rows = (
                await self._session.scalars(select(User).where(User.id.in_(reviewer_ids)))
            ).all()
            reviewers = {row.id: row.full_name or row.email for row in reviewer_rows}
        statuses = {
            "pending": VerificationReportCheckStatus.PENDING,
            "no_match_found": VerificationReportCheckStatus.CONFIRMED,
            "match_found": VerificationReportCheckStatus.DISCREPANCY,
            "review_required": VerificationReportCheckStatus.DISCREPANCY,
            "unable_to_complete": VerificationReportCheckStatus.UNABLE_TO_VERIFY,
        }
        items = [
            VerificationReportCourtSearchItem(
                safe_subject_display=person.full_name,
                scope=f"{row.jurisdiction}: {row.coverage}",
                search_period=row.search_period,
                searched_at=row.searched_at,
                source=row.source,
                finding=(
                    row.finding
                    or (
                        "No match found within the stated court-record scope"
                        if row.status == "no_match_found"
                        else None
                    )
                ),
                evidence_id=row.evidence_items[0].document_id if row.evidence_items else None,
                reviewer=reviewers.get(row.reviewer_user_id),
                remarks=row.remarks,
                limitations=row.limitations,
                status=(
                    statuses.get(row.status, VerificationReportCheckStatus.PENDING)
                    if row.finalized_at is not None
                    else VerificationReportCheckStatus.PENDING
                ),
            )
            for row in rows
        ]
        return items, rows

    def _check_summaries(
        self,
        requests,
        identity,
        employment,
        education,
        references,
        address,
        court_search=None,
        ordered=None,
    ):  # noqa: ANN001
        by_check: dict[str, list[VerificationReportCheckStatus]] = {
            key: [] for key in _REPORT_CHECKS
        }
        by_check["identity"] = [item.status for item in identity]
        by_check["employment"] = [item.status for item in employment]
        by_check["education"] = [item.status for item in education]
        by_check["references"] = [item.status for item in references]
        by_check["address"] = [item.status for item in address]
        by_check["court_record_search"] = [item.status for item in (court_search or [])]
        request_times: dict[str, datetime] = {}
        request_map = {
            VerificationRequestType.IDENTITY: "identity",
            VerificationRequestType.EMPLOYMENT: "employment",
            VerificationRequestType.EDUCATION: "education",
            VerificationRequestType.REFERENCE: "references",
        }
        for request in requests:
            key = request_map.get(request.request_type)
            if key:
                request_times[key] = max(
                    request_times.get(key, request.updated_at), request.updated_at
                )
                by_check[key].append(self._request_status(request.status))
        if court_search:
            request_times["court_record_search"] = (
                max(item.searched_at for item in court_search if item.searched_at is not None)
                if any(item.searched_at is not None for item in court_search)
                else None
            )
        summaries = []
        for check in _REPORT_CHECKS:
            by_check[check] = [
                status
                for status in by_check[check]
                if status != VerificationReportCheckStatus.NOT_ORDERED
            ]
            if not by_check[check] and check in (ordered or set()):
                by_check[check].append(VerificationReportCheckStatus.PENDING)
            status = self._aggregate_status(by_check[check])
            summaries.append(
                VerificationReportCheckSummary(
                    check=check,
                    status=status,
                    updated_at=request_times.get(check),
                    display_text=self._status_display(check, status),
                )
            )
        return summaries

    @staticmethod
    def _ordered_report_checks(requests, invitations) -> set[str]:  # noqa: ANN001
        mapping = {"reference": "references", "professional_reference": "references"}
        ordered = {
            mapping.get(r.request_type.value, r.request_type.value)
            for r in requests
            if r.status
            not in {
                VerificationRequestStatus.CANCELLED,
                VerificationRequestStatus.WITHDRAWN_BY_CANDIDATE,
            }
        }
        for invitation in invitations:
            ordered.update(
                mapping.get(value, value) for value in invitation.requested_verification_types
            )
            snapshot = invitation.verification_preferences_snapshot or {}
            # Historical HR defaults could record address intent without an enum mapping.
            # Explicit selections in new invitations never inherit unselected defaults.
            if snapshot.get("requested_types_source") != "explicit" and (
                snapshot.get("checks", {}).get("address") is True
            ):
                ordered.add("address")
        return ordered

    def _report_finality(self, requests, summaries, ordered=None):  # noqa: ANN001
        """One unresolved-work policy owns finality, open items and review indication."""
        items = self._open_items(requests)
        resolved = {
            VerificationReportCheckStatus.NOT_ORDERED,
            VerificationReportCheckStatus.CONFIRMED,
            VerificationReportCheckStatus.DETAILS_MATCHED,
        }
        request_checks = {"reference": "references"}
        represented = {request_checks.get(item.check, item.check) for item in items}
        present = {
            request_checks.get(r.request_type.value, r.request_type.value)
            for r in requests
            if r.status
            not in {
                VerificationRequestStatus.CANCELLED,
                VerificationRequestStatus.WITHDRAWN_BY_CANDIDATE,
            }
        }
        present.update(
            summary.check
            for summary in summaries
            if summary.status != VerificationReportCheckStatus.NOT_ORDERED
        )
        for check in sorted((ordered or set()) - present):
            items.append(
                VerificationReportOpenItem(
                    code="PENDING_VERIFICATION",
                    check=check,
                    display_text="Requested verification has no completed result",
                )
            )
        for summary in summaries:
            if summary.status in resolved or summary.check in represented:
                continue
            code = {
                VerificationReportCheckStatus.AWAITING_RESPONSE: "AWAITING_RESPONSE",
                VerificationReportCheckStatus.DISCREPANCY: "REVIEW_REQUIRED",
                VerificationReportCheckStatus.REJECTED: "REVIEW_REQUIRED",
                VerificationReportCheckStatus.UNABLE_TO_VERIFY: "REVIEW_REQUIRED",
            }.get(summary.status, "PENDING_VERIFICATION")
            items.append(
                VerificationReportOpenItem(
                    code=code,
                    check=summary.check,
                    display_text=summary.display_text,
                )
            )
        has_work = bool(requests) or any(
            summary.status != VerificationReportCheckStatus.NOT_ORDERED for summary in summaries
        )
        status = (
            VerificationReportStatus.FINAL
            if has_work and not items
            else VerificationReportStatus.INTERIM
        )
        return status, items, bool(items)

    def _open_items(self, requests: list[VerificationRequest]) -> list[VerificationReportOpenItem]:
        items = []
        for request in requests:
            if request.status in {
                VerificationRequestStatus.VERIFIED,
                VerificationRequestStatus.CANCELLED,
                VerificationRequestStatus.WITHDRAWN_BY_CANDIDATE,
            }:
                continue
            code = (
                "AWAITING_RESPONSE"
                if request.status
                in {
                    VerificationRequestStatus.PENDING_SUBJECT_ACCEPTANCE,
                    VerificationRequestStatus.PENDING_SUBJECT_SUBMISSION,
                    VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE,
                    VerificationRequestStatus.AWAITING_INFORMATION,
                }
                else "REVIEW_REQUIRED"
                if request.status
                in {
                    VerificationRequestStatus.REJECTED,
                    VerificationRequestStatus.UNABLE_TO_VERIFY,
                    VerificationRequestStatus.EXPIRED,
                }
                else "PENDING_VERIFICATION"
            )
            items.append(
                VerificationReportOpenItem(
                    code=code,
                    check=request.request_type.value,
                    display_text=(
                        "A response is still awaited"
                        if code == "AWAITING_RESPONSE"
                        else "Verification outcome requires review"
                        if code == "REVIEW_REQUIRED"
                        else "Verification processing is still in progress"
                    ),
                    request_public_id=request.public_id,
                )
            )
        return items

    def _request_status(self, status: VerificationRequestStatus) -> VerificationReportCheckStatus:
        if status in {
            VerificationRequestStatus.CANCELLED,
            VerificationRequestStatus.WITHDRAWN_BY_CANDIDATE,
        }:
            return VerificationReportCheckStatus.NOT_ORDERED
        if status == VerificationRequestStatus.VERIFIED:
            return VerificationReportCheckStatus.CONFIRMED
        if status == VerificationRequestStatus.REJECTED:
            return VerificationReportCheckStatus.REJECTED
        if status in {
            VerificationRequestStatus.UNABLE_TO_VERIFY,
            VerificationRequestStatus.EXPIRED,
        }:
            return VerificationReportCheckStatus.UNABLE_TO_VERIFY
        if status in {
            VerificationRequestStatus.PENDING_SUBJECT_ACCEPTANCE,
            VerificationRequestStatus.PENDING_SUBJECT_SUBMISSION,
            VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE,
            VerificationRequestStatus.AWAITING_INFORMATION,
        }:
            return VerificationReportCheckStatus.AWAITING_RESPONSE
        return VerificationReportCheckStatus.PENDING

    def _identity_status(self, match_result: str) -> VerificationReportCheckStatus:
        return {
            "VERIFIED_MATCH": VerificationReportCheckStatus.DETAILS_MATCHED,
            "PARTIAL_MATCH": VerificationReportCheckStatus.DISCREPANCY,
            "MISMATCH": VerificationReportCheckStatus.DISCREPANCY,
            "UNABLE_TO_VERIFY": VerificationReportCheckStatus.UNABLE_TO_VERIFY,
        }.get(match_result, VerificationReportCheckStatus.PENDING)

    def _reference_status(self, status: str) -> VerificationReportCheckStatus:
        if status == "completed":
            return VerificationReportCheckStatus.CONFIRMED
        if status in {"declined", "expired", "cannot_confirm"}:
            return VerificationReportCheckStatus.UNABLE_TO_VERIFY
        if status in {"invitation_sent", "opened"}:
            return VerificationReportCheckStatus.AWAITING_RESPONSE
        if status == "needs_review":
            return VerificationReportCheckStatus.DISCREPANCY
        return VerificationReportCheckStatus.PENDING

    def _aggregate_status(
        self, statuses: list[VerificationReportCheckStatus]
    ) -> VerificationReportCheckStatus:
        statuses = [
            status for status in statuses if status != VerificationReportCheckStatus.NOT_ORDERED
        ]
        if not statuses:
            return VerificationReportCheckStatus.NOT_ORDERED
        priority = (
            VerificationReportCheckStatus.DISCREPANCY,
            VerificationReportCheckStatus.REJECTED,
            VerificationReportCheckStatus.UNABLE_TO_VERIFY,
            VerificationReportCheckStatus.AWAITING_RESPONSE,
            VerificationReportCheckStatus.PENDING,
            VerificationReportCheckStatus.DETAILS_MATCHED,
            VerificationReportCheckStatus.CONFIRMED,
        )
        return next(status for status in priority if status in statuses)

    def _status_display(self, check: str, status: VerificationReportCheckStatus) -> str:
        labels = {
            VerificationReportCheckStatus.CONFIRMED: "Confirmed",
            VerificationReportCheckStatus.DETAILS_MATCHED: "Details matched",
            VerificationReportCheckStatus.DISCREPANCY: "Discrepancy requires review",
            VerificationReportCheckStatus.PENDING: "Verification is in progress",
            VerificationReportCheckStatus.AWAITING_RESPONSE: "Awaiting response",
            VerificationReportCheckStatus.UNABLE_TO_VERIFY: "Unable to verify",
            VerificationReportCheckStatus.REJECTED: "Rejected",
            VerificationReportCheckStatus.NOT_ORDERED: "Not ordered",
        }
        return f"{check.replace('_', ' ').title()}: {labels[status]}"

    async def _record_event(
        self,
        organization_id: UUID,
        actor_user_id: UUID,
        event_type: str,
        subject_type: str | None = None,
        subject_public_id: UUID | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self._session.add(
            OrganizationActivityEvent(
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                event_type=event_type,
                subject_type=subject_type,
                subject_public_id=str(subject_public_id) if subject_public_id else None,
                metadata_payload=metadata or {},
            )
        )
        await self._session.flush()

    def _assert_active_access(self, organization, membership) -> None:  # noqa: ANN001
        if organization.suspended_at is not None:
            raise ForbiddenError("Organization access is suspended")
        if membership.suspended_at is not None:
            raise ForbiddenError("Organization membership is suspended")

    def _mask_email(self, value: str | None) -> str | None:
        if not value or "@" not in value:
            return None
        local, domain = value.split("@", 1)
        return f"{local[:1]}{'*' * max(2, len(local) - 1)}@{domain}"

    def _mask_phone(self, value: str | None) -> str | None:
        if not value:
            return None
        digits = re.sub(r"\D", "", value)
        return f"***{digits[-4:]}" if len(digits) >= 4 else "***"

    def _mask_identifier(self, value: object) -> str | None:
        text = self._safe_text(value)
        if not text:
            return None
        return f"***{text[-4:]}" if len(text) > 4 else "***"

    def _safe_identity_remark(self, reason: str | None) -> str | None:
        if reason is None:
            return None
        return reason.replace("_", " ").title()

    def _safe_text(self, value: object) -> str | None:
        if not isinstance(value, (str, int, float, bool)):
            return None
        text = str(value).strip()
        return text[:2000] or None

    def _parse_date(self, value: object) -> date | None:
        if not isinstance(value, str):
            return None
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None

    def _display_address(self, value: dict) -> str | None:  # noqa: ANN001
        allowed = ("line1", "line2", "city", "district", "state", "postal_code", "country")
        parts = [self._safe_text(value.get(key)) for key in allowed]
        return ", ".join(part for part in parts if part) or None
