"""Admin Operations V1.1 orchestration with explicit lifecycle and policy guards."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.admin_operations.enums import (
    CandidateClaimStatus,
    CourtCheckStatus,
    ProfileProvenanceSource,
)
from app.auth.email_utils import mask_email, normalize_email
from app.auth.passwords import hash_password
from app.auth.phone_utils import mask_phone, normalize_phone
from app.auth.tokens import hash_refresh_token
from app.config import Settings
from app.core.constants import Role
from app.exceptions import (
    ConflictError,
    ExpiredLinkError,
    NotFoundError,
    RateLimitError,
    ValidationAppError,
)
from app.models.admin_profile_provenance import AdminProfileProvenance
from app.models.candidate_activation import CandidateActivationToken
from app.models.court_record_check import CourtRecordCheck, CourtRecordCheckEvidence
from app.models.in_person_verification import InPersonVerificationRecord
from app.models.organization import Organization
from app.models.organization_activity_event import OrganizationActivityEvent
from app.models.organization_invitation import OrganizationInvitation
from app.models.organization_member import OrganizationMember
from app.models.organization_person import OrganizationPerson
from app.models.pending_signup import PendingSignup
from app.models.user import User
from app.models.user_account_event import UserAccountEvent
from app.models.user_document import UserDocument
from app.organization.enums import OrganizationInvitationStatus, OrganizationRole
from app.resumes.review_schemas import ImportBatchResponse, review_claim_adapter
from app.schemas.admin_operations import (
    AdminCandidateResponse,
    AdminCareerMutationRequest,
    AdminCareerMutationResponse,
    AdminCreateCandidateRequest,
    AdminFirstHRInvitationRequest,
    AdminFirstHRInvitationResponse,
    AdminFirstHRInvitationStatus,
    AdminOrganizationCreateRequest,
    AdminOrganizationCreateResponse,
    AdminOrganizationProvisioningStatus,
    AdminProfileMutationRequest,
    AdminProfileMutationResponse,
    CandidateActivationResponse,
    CandidateActivationValidationResponse,
    CandidateClaimRequest,
    CandidateClaimResponse,
    CandidateProvenanceConfirmationRequest,
    CandidateProvenanceConfirmationResponse,
    CourtCheckResponse,
    CourtCheckUpdateRequest,
    CourtCheckWriteRequest,
    InPersonVerificationCreateRequest,
    InPersonVerificationResponse,
)
from app.schemas.pagination import Page, PageParams
from app.services.email_delivery_service import EmailDeliveryService
from app.services.organization_service import OrganizationService
from app.services.resume_review_service import ResumeReviewService

_ACTIVATION_TTL = timedelta(hours=24)
_ACTIVATION_RESEND_COOLDOWN = timedelta(seconds=60)
_TEAM_INVITATION_TTL = timedelta(days=7)
_EVIDENCE_MIME_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/webp"}
_EVIDENCE_MAX_BYTES = 50 * 1024 * 1024
_TERMINAL_COURT_STATUSES = {
    CourtCheckStatus.NO_MATCH_FOUND,
    CourtCheckStatus.MATCH_FOUND,
    CourtCheckStatus.REVIEW_REQUIRED,
    CourtCheckStatus.UNABLE_TO_COMPLETE,
}


class AdminOperationsConflict(ConflictError):
    """409 with a stable frontend-facing reason code."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class AdminOperationsService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        email_delivery: EmailDeliveryService | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._email = email_delivery or EmailDeliveryService(session, settings)

    async def create_candidate(
        self, actor_user_id: UUID, payload: AdminCreateCandidateRequest
    ) -> AdminCandidateResponse:
        idempotent = await self._session.scalar(
            select(User).where(User.assisted_creation_idempotency_key == payload.idempotency_key)
        )
        if idempotent is not None:
            return await self._candidate_response(idempotent)

        email = normalize_email(str(payload.email))
        existing_email = await self._session.scalar(
            select(User).where(func.lower(User.email) == email)
        )
        if existing_email is not None:
            code = (
                "candidate_unclaimed_exists"
                if existing_email.claim_status
                in {
                    CandidateClaimStatus.ADMIN_CREATED_UNCLAIMED.value,
                    CandidateClaimStatus.ACTIVATION_PENDING.value,
                }
                else "candidate_email_exists"
            )
            if existing_email.deleted_at is not None:
                code = "candidate_pending_deletion"
            raise AdminOperationsConflict("A Candidate account already uses this email", code=code)

        phone = normalize_phone(payload.phone, self._settings) if payload.phone else None
        if phone is not None:
            existing_phone = await self._session.scalar(select(User).where(User.phone == phone))
            if existing_phone is not None:
                code = (
                    "candidate_pending_deletion"
                    if existing_phone.deleted_at is not None
                    else "candidate_phone_exists"
                )
                raise AdminOperationsConflict(
                    "A Candidate account already uses this phone", code=code
                )

        pending_contacts = [func.lower(PendingSignup.email) == email]
        if phone is not None:
            pending_contacts.append(PendingSignup.phone == phone)
        pending = await self._session.scalar(
            select(PendingSignup).where(*pending_contacts)
            if len(pending_contacts) == 1
            else select(PendingSignup).where(pending_contacts[0] | pending_contacts[1])
        )
        if pending is not None and pending.completed_at is None:
            raise AdminOperationsConflict(
                "A Candidate signup is already pending for this contact",
                code="candidate_signup_pending",
            )

        now = datetime.now(tz=UTC)
        user = User(
            email=email,
            phone=phone,
            full_name=payload.full_name,
            headline=payload.headline,
            location=payload.location,
            password_hash=None,
            role=Role.USER.value,
            is_active=True,
            email_verified_at=None,
            phone_verified_at=None,
            claim_status=CandidateClaimStatus.ADMIN_CREATED_UNCLAIMED.value,
            admin_created_by_user_id=actor_user_id,
            admin_created_at=now,
            claimed_at=None,
            assisted_creation_idempotency_key=payload.idempotency_key,
        )
        self._session.add(user)
        await self._session.flush()
        self._session.add(
            UserAccountEvent(
                user_id=user.id,
                actor_user_id=actor_user_id,
                actor_role=Role.ADMIN.value,
                event_type="admin_person_created",
                title="Candidate account created for assisted onboarding",
                detail=(
                    "Account is unclaimed; no password or verified contact was created by Admin."
                ),
                metadata_payload={"claim_status": user.claim_status},
            )
        )
        await self._record_profile_provenance(
            user.id,
            "profile",
            user.id,
            {"full_name": user.full_name, "headline": user.headline, "location": user.location},
            ProfileProvenanceSource.ADMIN_ENTERED,
            actor_user_id,
        )
        await self._session.commit()
        await self._session.refresh(user)
        return await self._candidate_response(user)

    async def candidate_status(self, candidate_id: UUID) -> AdminCandidateResponse:
        return await self._candidate_response(await self._managed_candidate(candidate_id))

    async def send_candidate_activation(
        self, actor_user_id: UUID, candidate_id: UUID, *, resend: bool
    ) -> CandidateActivationResponse:
        user = await self._locked_managed_candidate(candidate_id)
        if user.claim_status == CandidateClaimStatus.CLAIMED.value:
            raise AdminOperationsConflict(
                "Candidate account has already been claimed", code="candidate_already_claimed"
            )
        now = datetime.now(tz=UTC)
        active = list(
            (
                await self._session.scalars(
                    select(CandidateActivationToken)
                    .where(
                        CandidateActivationToken.user_id == user.id,
                        CandidateActivationToken.used_at.is_(None),
                        CandidateActivationToken.revoked_at.is_(None),
                    )
                    .order_by(CandidateActivationToken.token_version.desc())
                    .with_for_update()
                )
            ).all()
        )
        if resend and active:
            available_at = active[0].last_sent_at + _ACTIVATION_RESEND_COOLDOWN
            if available_at > now:
                raise RateLimitError(
                    "Candidate activation can be resent after the cooldown",
                    retry_after_seconds=max(1, int((available_at - now).total_seconds())),
                )
        if not resend and active and active[0].expires_at > now:
            raise AdminOperationsConflict(
                "An active Candidate activation already exists",
                code="candidate_activation_exists",
            )
        previous_version = await self._session.scalar(
            select(func.max(CandidateActivationToken.token_version)).where(
                CandidateActivationToken.user_id == user.id
            )
        )
        version = int(previous_version or 0) + 1
        for row in active:
            row.revoked_at = now

        raw_token = secrets.token_urlsafe(48)
        token = CandidateActivationToken(
            user_id=user.id,
            created_by_user_id=actor_user_id,
            token_hash=hash_refresh_token(raw_token),
            token_version=version,
            expires_at=now + _ACTIVATION_TTL,
            last_sent_at=now,
        )
        self._session.add(token)
        user.claim_status = CandidateClaimStatus.ACTIVATION_PENDING.value
        self._session.add(
            UserAccountEvent(
                user_id=user.id,
                actor_user_id=actor_user_id,
                actor_role=Role.ADMIN.value,
                event_type=(
                    "candidate_activation_resent" if resend else "candidate_activation_sent"
                ),
                title="Candidate activation queued",
                detail=(
                    "A single-use activation link was queued without exposing its token to Admin."
                ),
                metadata_payload={
                    "token_version": version,
                    "expires_at": token.expires_at.isoformat(),
                },
            )
        )
        await self._session.commit()

        base = (self._settings.candidate_portal_base_url or "https://app.kairoid.com").rstrip("/")
        activation_url = f"{base}/activate-account?token={quote(raw_token, safe='')}"
        try:
            delivery = await self._email.queue_template_email(
                template_key="candidate_account_activation",
                to_email=user.email,
                template_data={
                    "candidate_name": user.full_name or "there",
                    "activation_url": activation_url,
                    "expires_at_iso": token.expires_at.isoformat(),
                },
                recipient_user_id=user.id,
            )
            if delivery.status == "failed":
                raise RuntimeError("email delivery failed")
            delivery_state = "queued"
        except Exception as exc:
            token.delivery_failed_at = datetime.now(tz=UTC)
            token.revoked_at = token.delivery_failed_at
            user.claim_status = CandidateClaimStatus.ADMIN_CREATED_UNCLAIMED.value
            await self._session.commit()
            raise ValidationAppError(
                "Candidate activation email could not be queued",
                code="candidate_activation_delivery_failed",
            ) from exc
        return CandidateActivationResponse(
            candidate_id=user.id,
            claim_status=CandidateClaimStatus(user.claim_status),
            email_masked=mask_email(user.email),
            expires_at=token.expires_at,
            last_sent_at=token.last_sent_at,
            resend_available_at=token.last_sent_at + _ACTIVATION_RESEND_COOLDOWN,
            delivery_state=delivery_state,
        )

    async def validate_candidate_activation(
        self, raw_token: str
    ) -> CandidateActivationValidationResponse:
        token, user = await self._resolve_activation(raw_token)
        return CandidateActivationValidationResponse(
            candidate_id=user.id,
            claim_status=CandidateClaimStatus(user.claim_status),
            full_name=user.full_name,
            email_masked=mask_email(user.email),
            expires_at=token.expires_at,
        )

    async def claim_candidate_account(
        self, payload: CandidateClaimRequest
    ) -> CandidateClaimResponse:
        token_hash = hash_refresh_token(payload.token)
        token = await self._session.scalar(
            select(CandidateActivationToken)
            .where(CandidateActivationToken.token_hash == token_hash)
            .with_for_update()
        )
        if token is None:
            raise NotFoundError("Candidate activation not found")
        user = await self._session.scalar(
            select(User).where(User.id == token.user_id).with_for_update()
        )
        if user is None or user.deleted_at is not None:
            raise NotFoundError("Candidate activation not found")
        now = datetime.now(tz=UTC)
        self._assert_activation_actionable(token, user, now)
        user.password_hash = hash_password(payload.password)
        user.claim_status = CandidateClaimStatus.CLAIMED.value
        user.claimed_at = now
        # The opaque link is delivered only to the normalized account email; consuming it
        # is therefore the email-contact proof. Phone verification remains untouched.
        if user.email_verified_at is None:
            user.email_verified_at = now
        token.used_at = now
        sibling_tokens = (
            await self._session.scalars(
                select(CandidateActivationToken).where(
                    CandidateActivationToken.user_id == user.id,
                    CandidateActivationToken.id != token.id,
                    CandidateActivationToken.used_at.is_(None),
                    CandidateActivationToken.revoked_at.is_(None),
                )
            )
        ).all()
        for sibling in sibling_tokens:
            sibling.revoked_at = now
        self._session.add(
            UserAccountEvent(
                user_id=user.id,
                actor_user_id=user.id,
                actor_role=Role.USER.value,
                event_type="candidate_account_claimed",
                title="Candidate account claimed",
                detail=(
                    "Candidate set their own password using the single-use email activation link."
                ),
                metadata_payload={"email_verified_by": "activation_link"},
            )
        )
        await self._session.commit()
        return CandidateClaimResponse(
            candidate_id=user.id,
            claim_status=CandidateClaimStatus.CLAIMED,
            claimed_at=now,
            email_verified=user.email_verified_at is not None,
            phone_verified=user.phone_verified_at is not None,
        )

    async def update_candidate_profile(
        self, actor_user_id: UUID, candidate_id: UUID, payload: AdminProfileMutationRequest
    ) -> AdminProfileMutationResponse:
        user = await self._locked_managed_candidate(candidate_id)
        changes = payload.model_dump(exclude={"source"}, exclude_unset=True)
        await self._protect_verified_fields(user.id, "profile", user.id, changes)
        if "phone" in changes and changes["phone"] is not None:
            phone = normalize_phone(changes["phone"], self._settings)
            duplicate = await self._session.scalar(
                select(User).where(User.phone == phone, User.id != user.id)
            )
            if duplicate is not None:
                raise AdminOperationsConflict(
                    "A Candidate account already uses this phone", code="candidate_phone_exists"
                )
            if phone != user.phone:
                user.phone_verified_at = None
            changes["phone"] = phone
        for field, value in changes.items():
            setattr(user, field, value)
        await self._record_profile_provenance(
            user.id, "profile", user.id, changes, payload.source, actor_user_id
        )
        self._session.add(
            UserAccountEvent(
                user_id=user.id,
                actor_user_id=actor_user_id,
                actor_role=Role.ADMIN.value,
                event_type="admin_profile_updated",
                title="Assisted profile updated",
                detail="Profile fields were updated with explicit non-verified provenance.",
                metadata_payload={"fields": sorted(changes), "source": payload.source.value},
            )
        )
        await self._session.commit()
        return AdminProfileMutationResponse(
            candidate_id=user.id,
            claim_status=CandidateClaimStatus(user.claim_status),
            updated_fields=sorted(changes),
            provenance_source=payload.source,
            candidate_confirmation_required=True,
        )

    async def mutate_candidate_career(
        self,
        actor_user_id: UUID,
        candidate_id: UUID,
        payload: AdminCareerMutationRequest,
        *,
        record_id: UUID | None = None,
    ) -> AdminCareerMutationResponse:
        user = await self._locked_managed_candidate(candidate_id)
        raw = {**payload.payload, "claim_type": payload.claim_type}
        claim = review_claim_adapter.validate_python(raw)
        typed = review_claim_adapter.dump_python(claim, mode="python")
        review = ResumeReviewService(self._session)
        if record_id is None:
            record = await review._create_record(user.id, payload.claim_type, typed)
            self._session.add(record)
        else:
            record = await review._target(user.id, payload.claim_type, record_id)
            if await review._is_protected_target(user.id, payload.claim_type, record):
                raise AdminOperationsConflict(
                    "Source-verified or active Career records cannot be overwritten",
                    code="source_verified_field_protected",
                )
            await self._protect_verified_fields(
                user.id, payload.claim_type, record.id, payload.payload
            )
            review._apply_update(record, payload.claim_type, typed)
        await self._session.flush()
        fields = {key: value for key, value in payload.payload.items() if key != "claim_type"}
        await self._record_profile_provenance(
            user.id,
            payload.claim_type,
            record.id,
            fields,
            payload.source,
            actor_user_id,
        )
        self._session.add(
            UserAccountEvent(
                user_id=user.id,
                actor_user_id=actor_user_id,
                actor_role=Role.ADMIN.value,
                event_type="admin_profile_updated",
                title="Assisted Career record updated",
                detail="Career fields remain unverified until their domain workflow verifies them.",
                metadata_payload={
                    "record_type": payload.claim_type,
                    "record_id": str(record.id),
                    "fields": sorted(fields),
                    "source": payload.source.value,
                },
            )
        )
        await self._session.commit()
        return AdminCareerMutationResponse(
            candidate_id=user.id,
            claim_type=payload.claim_type,
            record_id=record.id,
            updated_fields=sorted(fields),
            provenance_source=payload.source,
            verification_status=str(getattr(record, "verification_status", "unverified")),
        )

    async def confirm_candidate_provenance(
        self, user_id: UUID, payload: CandidateProvenanceConfirmationRequest
    ) -> CandidateProvenanceConfirmationResponse:
        now = datetime.now(tz=UTC)
        confirmed = 0
        for item in payload.items:
            latest = await self._latest_provenance(
                user_id, item.record_type, item.record_id, item.field_name
            )
            if latest is None:
                raise NotFoundError("Profile provenance item not found")
            if latest.source == ProfileProvenanceSource.SOURCE_VERIFIED.value:
                continue
            self._session.add(
                AdminProfileProvenance(
                    user_id=user_id,
                    record_type=item.record_type,
                    record_id=item.record_id,
                    field_name=item.field_name,
                    source=ProfileProvenanceSource.CANDIDATE_CONFIRMED.value,
                    value_hash=latest.value_hash,
                    actor_user_id=user_id,
                    candidate_confirmed_at=now,
                )
            )
            confirmed += 1
        await self._session.commit()
        return CandidateProvenanceConfirmationResponse(confirmed_count=confirmed, confirmed_at=now)

    async def record_cv_import_audit(
        self,
        actor_user_id: UUID,
        candidate_id: UUID,
        batch: ImportBatchResponse,
    ) -> None:
        await self._managed_candidate(candidate_id)
        existing = await self._session.scalar(
            select(UserAccountEvent.id).where(
                UserAccountEvent.user_id == candidate_id,
                UserAccountEvent.event_type == "admin_cv_import_confirmed",
                UserAccountEvent.metadata_payload["import_batch_id"].as_string() == str(batch.id),
            )
        )
        if existing is not None:
            return
        self._session.add(
            UserAccountEvent(
                user_id=candidate_id,
                actor_user_id=actor_user_id,
                actor_role=Role.ADMIN.value,
                event_type="admin_cv_import_confirmed",
                title="Admin confirmed selected CV data for profile import",
                detail=(
                    "Selected reviewed CV items were imported with CV/Admin provenance; "
                    "no source verification was created."
                ),
                metadata_payload={
                    "import_batch_id": str(batch.id),
                    "review_session_id": str(batch.review_session_id),
                    "imported_count": batch.imported_count,
                    "linked_count": batch.linked_count,
                    "skipped_count": batch.skipped_count,
                    "failed_count": batch.failed_count,
                },
            )
        )
        await self._session.commit()

    async def create_organization(
        self, actor_user_id: UUID, payload: AdminOrganizationCreateRequest
    ) -> AdminOrganizationCreateResponse:
        existing_key = await self._session.scalar(
            select(Organization).where(
                Organization.admin_provisioning_idempotency_key == payload.idempotency_key
            )
        )
        if existing_key is not None:
            return self._organization_response(existing_key)
        normalized_name = " ".join(payload.name.casefold().split())
        duplicate = await self._session.scalar(
            select(Organization).where(
                func.lower(func.regexp_replace(Organization.name, r"\s+", " ", "g"))
                == normalized_name
            )
        )
        if duplicate is not None:
            raise AdminOperationsConflict(
                "An organization with this normalized name already exists",
                code="organization_name_exists",
            )
        if payload.work_email is not None:
            email = normalize_email(str(payload.work_email))
            existing_invite = await self._session.scalar(
                select(OrganizationInvitation).where(
                    func.lower(OrganizationInvitation.invitee_email) == email,
                    OrganizationInvitation.status == OrganizationInvitationStatus.PENDING,
                )
            )
            if existing_invite is not None:
                raise AdminOperationsConflict(
                    "The primary HR email already has a pending organization invitation",
                    code="primary_hr_invitation_exists",
                )
        now = datetime.now(tz=UTC)
        organization = Organization(
            created_by_user_id=actor_user_id,
            name=payload.name,
            organization_type=payload.organization_type,
            website=payload.website,
            industry=payload.industry,
            location=payload.location,
            work_email=normalize_email(str(payload.work_email)) if payload.work_email else None,
            domain=payload.domain,
            organization_size=payload.organization_size,
            verification_capabilities=[],
            setup_completed_at=None,
            provisioned_by_admin_user_id=actor_user_id,
            provisioned_at=now,
            admin_provisioning_idempotency_key=payload.idempotency_key,
        )
        self._session.add(organization)
        await self._session.flush()
        self._session.add(
            OrganizationActivityEvent(
                organization_id=organization.id,
                actor_user_id=actor_user_id,
                event_type="admin_organization_created",
                subject_type="organization",
                subject_public_id=str(organization.public_id),
                metadata_payload={"lifecycle_state": "awaiting_first_hr_claim"},
            )
        )
        await self._session.commit()
        await self._session.refresh(organization)
        return self._organization_response(organization)

    async def invite_first_hr(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        payload: AdminFirstHRInvitationRequest,
        *,
        resend_invitation_public_id: UUID | None = None,
    ) -> AdminFirstHRInvitationResponse:
        organization = await self._admin_provisioned_organization(org_public_id)
        if await self._session.scalar(
            select(OrganizationMember.id).where(
                OrganizationMember.organization_id == organization.id
            )
        ):
            raise AdminOperationsConflict(
                "Organization already has a member", code="first_hr_already_claimed"
            )
        email = normalize_email(str(payload.email))
        pending = list(
            (
                await self._session.scalars(
                    select(OrganizationInvitation)
                    .options(
                        selectinload(OrganizationInvitation.organization),
                        selectinload(OrganizationInvitation.invited_by_user),
                    )
                    .where(
                        OrganizationInvitation.organization_id == organization.id,
                        OrganizationInvitation.status == OrganizationInvitationStatus.PENDING,
                    )
                    .with_for_update()
                )
            ).all()
        )
        now = datetime.now(tz=UTC)
        invitation: OrganizationInvitation | None = None
        if resend_invitation_public_id is not None:
            invitation = next(
                (row for row in pending if row.public_id == resend_invitation_public_id), None
            )
            if invitation is None:
                raise NotFoundError("First HR invitation not found")
            if normalize_email(invitation.invitee_email) != email:
                raise AdminOperationsConflict(
                    "First HR invitation email cannot be changed during resend",
                    code="first_hr_invitation_email_mismatch",
                )
        elif pending:
            same = next(
                (row for row in pending if normalize_email(row.invitee_email) == email),
                None,
            )
            if same is not None:
                raise AdminOperationsConflict(
                    "A first HR invitation is already pending for this email",
                    code="first_hr_invitation_exists",
                )
            raise AdminOperationsConflict(
                "A different first HR invitation is already pending",
                code="first_hr_invitation_conflict",
            )

        actor = await self._session.get(User, actor_user_id)
        if actor is None:
            raise NotFoundError("Admin user not found")
        org_service = OrganizationService(
            self._session, settings=self._settings, email_delivery=self._email
        )
        if invitation is None:
            invitee = await self._session.scalar(
                select(User).where(func.lower(User.email) == email, User.deleted_at.is_(None))
            )
            invitation = OrganizationInvitation(
                organization=organization,
                invited_by_user=actor,
                invitee_user_id=invitee.id if invitee is not None else None,
                invitee_name=payload.full_name,
                invitee_email=email,
                role=OrganizationRole.OWNER,
                status=OrganizationInvitationStatus.PENDING,
                expires_at=now + _TEAM_INVITATION_TTL,
            )
            self._session.add(invitation)
            event_type = "first_hr_invitation_sent"
        else:
            event_type = "first_hr_invitation_resent"
        raw_token = org_service._rotate_team_invitation_token(invitation)
        self._session.add(
            OrganizationActivityEvent(
                organization_id=organization.id,
                actor_user_id=actor_user_id,
                event_type=event_type,
                subject_type="organization_invitation",
                subject_public_id=str(invitation.public_id),
                metadata_payload={"role": OrganizationRole.OWNER.value},
            )
        )
        await self._session.commit()
        await self._session.refresh(invitation)
        await org_service._deliver_team_invitation(invitation, raw_token)
        return self._first_hr_response(organization, invitation)

    async def provisioning_status(self, org_public_id: UUID) -> AdminOrganizationProvisioningStatus:
        organization = await self._session.scalar(
            select(Organization).where(Organization.public_id == org_public_id)
        )
        if organization is None or organization.provisioned_at is None:
            raise NotFoundError("Admin-provisioned organization not found")
        roles = list(
            (
                await self._session.scalars(
                    select(OrganizationMember.role).where(
                        OrganizationMember.organization_id == organization.id
                    )
                )
            ).all()
        )
        invitation = await self._session.scalar(
            select(OrganizationInvitation)
            .where(
                OrganizationInvitation.organization_id == organization.id,
                OrganizationInvitation.role == OrganizationRole.OWNER,
            )
            .order_by(OrganizationInvitation.created_at.desc(), OrganizationInvitation.id.desc())
            .limit(1)
        )
        receipt = None
        if invitation is not None:
            stored_status = str(getattr(invitation.status, "value", invitation.status))
            effective = stored_status
            expires = invitation.token_expires_at or invitation.expires_at
            if stored_status == OrganizationInvitationStatus.PENDING.value:
                if invitation.token_revoked_at is not None:
                    effective = "revoked"
                elif expires is not None and expires <= datetime.now(tz=UTC):
                    effective = "expired"
                elif invitation.delivery_failed_at is not None:
                    effective = "delivery_failed"
            receipt = AdminFirstHRInvitationStatus(
                invitation_public_id=invitation.public_id,
                invitee_email_masked=mask_email(invitation.invitee_email),
                status=stored_status,
                effective_status=effective,
                expires_at=expires,
                last_sent_at=invitation.last_sent_at,
                delivery_failed_at=invitation.delivery_failed_at,
            )
        return AdminOrganizationProvisioningStatus(
            organization_public_id=organization.public_id,
            member_present=bool(roles),
            owner_membership_present=OrganizationRole.OWNER in roles,
            first_hr_invitation=receipt,
        )

    async def list_court_checks(
        self, org_public_id: UUID, person_public_id: UUID, params: PageParams
    ) -> Page[CourtCheckResponse]:
        organization, person = await self._organization_person(org_public_id, person_public_id)
        filters = (
            CourtRecordCheck.organization_id == organization.id,
            CourtRecordCheck.organization_person_id == person.id,
        )
        total = await self._session.scalar(
            select(func.count()).select_from(CourtRecordCheck).where(*filters)
        )
        rows = (
            await self._session.scalars(
                select(CourtRecordCheck)
                .options(selectinload(CourtRecordCheck.evidence_items))
                .where(*filters)
                .order_by(CourtRecordCheck.created_at.desc(), CourtRecordCheck.id.desc())
                .offset(params.offset)
                .limit(params.limit)
            )
        ).all()
        return Page[CourtCheckResponse].create(
            items=[self._court_response(organization, person, row) for row in rows],
            total=total or 0,
            params=params,
        )

    async def get_court_check(
        self, org_public_id: UUID, person_public_id: UUID, check_public_id: UUID
    ) -> CourtCheckResponse:
        organization, person = await self._organization_person(org_public_id, person_public_id)
        row = await self._session.scalar(
            select(CourtRecordCheck)
            .options(selectinload(CourtRecordCheck.evidence_items))
            .where(
                CourtRecordCheck.organization_id == organization.id,
                CourtRecordCheck.organization_person_id == person.id,
                CourtRecordCheck.public_id == check_public_id,
            )
        )
        if row is None:
            raise NotFoundError("Court record check not found")
        return self._court_response(organization, person, row)

    async def list_in_person_verifications(
        self, org_public_id: UUID, person_public_id: UUID, params: PageParams
    ) -> Page[InPersonVerificationResponse]:
        organization, person = await self._organization_person(org_public_id, person_public_id)
        filters = (
            InPersonVerificationRecord.organization_id == organization.id,
            InPersonVerificationRecord.organization_person_id == person.id,
        )
        total = await self._session.scalar(
            select(func.count()).select_from(InPersonVerificationRecord).where(*filters)
        )
        rows = (
            await self._session.scalars(
                select(InPersonVerificationRecord)
                .where(*filters)
                .order_by(
                    InPersonVerificationRecord.created_at.desc(),
                    InPersonVerificationRecord.id.desc(),
                )
                .offset(params.offset)
                .limit(params.limit)
            )
        ).all()
        return Page[InPersonVerificationResponse].create(
            items=[self._in_person_response(organization, person, row) for row in rows],
            total=total or 0,
            params=params,
        )

    async def get_in_person_verification(
        self, org_public_id: UUID, person_public_id: UUID, record_public_id: UUID
    ) -> InPersonVerificationResponse:
        organization, person = await self._organization_person(org_public_id, person_public_id)
        row = await self._session.scalar(
            select(InPersonVerificationRecord).where(
                InPersonVerificationRecord.organization_id == organization.id,
                InPersonVerificationRecord.organization_person_id == person.id,
                InPersonVerificationRecord.public_id == record_public_id,
            )
        )
        if row is None:
            raise NotFoundError("In-person verification not found")
        return self._in_person_response(organization, person, row)

    async def create_court_check(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        person_public_id: UUID,
        payload: CourtCheckWriteRequest,
    ) -> CourtCheckResponse:
        organization, person = await self._organization_person(org_public_id, person_public_id)
        existing = await self._session.scalar(
            select(CourtRecordCheck)
            .options(selectinload(CourtRecordCheck.evidence_items))
            .where(
                CourtRecordCheck.organization_id == organization.id,
                CourtRecordCheck.idempotency_key == payload.idempotency_key,
            )
        )
        if existing is not None:
            if existing.organization_person_id != person.id:
                raise AdminOperationsConflict(
                    "Court-check idempotency key is already in use",
                    code="court_check_idempotency_conflict",
                )
            return self._court_response(organization, person, existing)
        evidence = await self._validated_evidence(person, payload.evidence_document_ids)
        check = CourtRecordCheck(
            organization_id=organization.id,
            organization_person_id=person.id,
            subject_user_id=person.linked_user_id,
            status=payload.status.value,
            searched_at=payload.searched_at,
            jurisdiction=payload.jurisdiction,
            coverage=payload.coverage,
            search_period=payload.search_period,
            source=payload.source,
            finding=payload.finding,
            remarks=payload.remarks,
            limitations=payload.limitations,
            reviewer_user_id=actor_user_id,
            idempotency_key=payload.idempotency_key,
        )
        self._session.add(check)
        await self._session.flush()
        for document in evidence:
            self._session.add(
                CourtRecordCheckEvidence(
                    court_record_check_id=check.id,
                    document_id=document.id,
                    attached_by_user_id=actor_user_id,
                )
            )
        await self._organization_event(
            organization.id,
            actor_user_id,
            "court_check_created",
            "court_record_check",
            check.public_id,
            {"status": check.status},
        )
        await self._session.commit()
        return await self._reloaded_court_response(organization, person, check.public_id)

    async def update_court_check(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        person_public_id: UUID,
        check_public_id: UUID,
        payload: CourtCheckUpdateRequest,
    ) -> CourtCheckResponse:
        organization, person = await self._organization_person(org_public_id, person_public_id)
        check = await self._locked_court_check(organization.id, person.id, check_public_id)
        if check.finalized_at is not None:
            raise AdminOperationsConflict(
                "Finalized court checks are immutable", code="court_check_finalized"
            )
        changes = payload.model_dump(exclude_unset=True, exclude={"evidence_document_ids"})
        if "status" in changes:
            changes["status"] = changes["status"].value
        for field, value in changes.items():
            setattr(check, field, value)
        if check.status != CourtCheckStatus.PENDING.value and check.searched_at is None:
            raise ValidationAppError("searched_at is required for a court-check result")
        if (
            check.status
            in {
                CourtCheckStatus.MATCH_FOUND.value,
                CourtCheckStatus.REVIEW_REQUIRED.value,
            }
            and not check.finding
        ):
            raise ValidationAppError("finding is required for match or review-required results")
        if payload.evidence_document_ids is not None:
            evidence = await self._validated_evidence(person, payload.evidence_document_ids)
            existing_ids = {item.document_id for item in check.evidence_items}
            for document in evidence:
                if document.id not in existing_ids:
                    self._session.add(
                        CourtRecordCheckEvidence(
                            court_record_check_id=check.id,
                            document_id=document.id,
                            attached_by_user_id=actor_user_id,
                        )
                    )
        check.reviewer_user_id = actor_user_id
        await self._organization_event(
            organization.id,
            actor_user_id,
            "court_check_updated",
            "court_record_check",
            check.public_id,
            {"status": check.status},
        )
        await self._session.commit()
        return await self._reloaded_court_response(organization, person, check.public_id)

    async def finalize_court_check(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        person_public_id: UUID,
        check_public_id: UUID,
    ) -> CourtCheckResponse:
        organization, person = await self._organization_person(org_public_id, person_public_id)
        check = await self._locked_court_check(organization.id, person.id, check_public_id)
        if check.finalized_at is not None:
            return self._court_response(organization, person, check)
        if CourtCheckStatus(check.status) not in _TERMINAL_COURT_STATUSES:
            raise AdminOperationsConflict(
                "A pending court check cannot be finalized", code="court_check_result_required"
            )
        if check.searched_at is None:
            raise ValidationAppError("searched_at is required before finalization")
        check.finalized_at = datetime.now(tz=UTC)
        check.reviewer_user_id = actor_user_id
        await self._organization_event(
            organization.id,
            actor_user_id,
            "court_check_finalized",
            "court_record_check",
            check.public_id,
            {"status": check.status},
        )
        await self._session.commit()
        return await self._reloaded_court_response(organization, person, check.public_id)

    async def record_in_person_verification(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        person_public_id: UUID,
        payload: InPersonVerificationCreateRequest,
    ) -> InPersonVerificationResponse:
        organization, person = await self._organization_person(org_public_id, person_public_id)
        existing = await self._session.scalar(
            select(InPersonVerificationRecord).where(
                InPersonVerificationRecord.organization_id == organization.id,
                InPersonVerificationRecord.idempotency_key == payload.idempotency_key,
            )
        )
        if existing is not None:
            if existing.organization_person_id != person.id:
                raise AdminOperationsConflict(
                    "In-person idempotency key is already in use",
                    code="in_person_idempotency_conflict",
                )
            return self._in_person_response(organization, person, existing)
        await self._validated_evidence(person, payload.evidence_document_ids)
        record = InPersonVerificationRecord(
            organization_id=organization.id,
            organization_person_id=person.id,
            subject_user_id=person.linked_user_id,
            verification_type=payload.verification_type.value,
            method="in_person",
            performed_at=payload.performed_at,
            performed_by_user_id=actor_user_id,
            person_met=payload.person_met,
            relationship=payload.relationship,
            result=payload.result.value,
            notes=payload.notes,
            evidence_document_ids=payload.evidence_document_ids,
            idempotency_key=payload.idempotency_key,
        )
        self._session.add(record)
        await self._session.flush()
        await self._organization_event(
            organization.id,
            actor_user_id,
            "in_person_verification_recorded",
            "in_person_verification",
            record.public_id,
            {
                "verification_type": record.verification_type,
                "result": record.result,
                "changes_canonical_verification_status": False,
                "permanent_address_check_credit": 0,
            },
        )
        await self._session.commit()
        await self._session.refresh(record)
        return self._in_person_response(organization, person, record)

    async def _managed_candidate(self, candidate_id: UUID) -> User:
        user = await self._session.scalar(
            select(User).where(User.id == candidate_id, User.deleted_at.is_(None))
        )
        if user is None or user.admin_created_at is None:
            raise NotFoundError("Admin-managed Candidate not found")
        return user

    async def _locked_managed_candidate(self, candidate_id: UUID) -> User:
        user = await self._session.scalar(
            select(User).where(User.id == candidate_id, User.deleted_at.is_(None)).with_for_update()
        )
        if user is None or user.admin_created_at is None:
            raise NotFoundError("Admin-managed Candidate not found")
        return user

    async def _candidate_response(self, user: User) -> AdminCandidateResponse:
        activation = await self._session.scalar(
            select(CandidateActivationToken)
            .where(
                CandidateActivationToken.user_id == user.id,
                CandidateActivationToken.used_at.is_(None),
                CandidateActivationToken.revoked_at.is_(None),
            )
            .order_by(CandidateActivationToken.token_version.desc())
        )
        return AdminCandidateResponse(
            candidate_id=user.id,
            full_name=user.full_name,
            email_masked=mask_email(user.email),
            phone_masked=mask_phone(user.phone) if user.phone else None,
            claim_status=CandidateClaimStatus(user.claim_status),
            password_configured=user.password_hash is not None,
            email_verified=user.email_verified_at is not None,
            phone_verified=user.phone_verified_at is not None,
            activation_expires_at=activation.expires_at if activation else None,
            activation_last_sent_at=activation.last_sent_at if activation else None,
            created_at=user.created_at,
        )

    async def _resolve_activation(self, raw_token: str) -> tuple[CandidateActivationToken, User]:
        if not raw_token or len(raw_token) < 32:
            raise NotFoundError("Candidate activation not found")
        token = await self._session.scalar(
            select(CandidateActivationToken).where(
                CandidateActivationToken.token_hash == hash_refresh_token(raw_token)
            )
        )
        if token is None:
            raise NotFoundError("Candidate activation not found")
        user = await self._session.get(User, token.user_id)
        if user is None or user.deleted_at is not None:
            raise NotFoundError("Candidate activation not found")
        self._assert_activation_actionable(token, user, datetime.now(tz=UTC))
        return token, user

    @staticmethod
    def _assert_activation_actionable(
        token: CandidateActivationToken, user: User, now: datetime
    ) -> None:
        if token.expires_at <= now:
            raise ExpiredLinkError("Candidate activation has expired")
        if token.revoked_at is not None:
            raise AdminOperationsConflict(
                "Candidate activation has been revoked", code="candidate_activation_revoked"
            )
        if token.used_at is not None or user.claim_status == CandidateClaimStatus.CLAIMED.value:
            raise AdminOperationsConflict(
                "Candidate activation has already been used", code="candidate_activation_used"
            )
        if token.delivery_failed_at is not None:
            raise AdminOperationsConflict(
                "Candidate activation was not delivered", code="candidate_activation_undelivered"
            )

    async def _record_profile_provenance(
        self,
        user_id: UUID,
        record_type: str,
        record_id: UUID,
        values: dict[str, Any],
        source: ProfileProvenanceSource,
        actor_user_id: UUID,
    ) -> None:
        for field, value in values.items():
            if value is None:
                continue
            self._session.add(
                AdminProfileProvenance(
                    user_id=user_id,
                    record_type=record_type,
                    record_id=record_id,
                    field_name=field,
                    source=source.value,
                    value_hash=self._value_hash(value),
                    actor_user_id=actor_user_id,
                )
            )

    async def _protect_verified_fields(
        self, user_id: UUID, record_type: str, record_id: UUID, changes: dict[str, Any]
    ) -> None:
        for field in changes:
            latest = await self._latest_provenance(user_id, record_type, record_id, field)
            if (
                latest is not None
                and latest.source == ProfileProvenanceSource.SOURCE_VERIFIED.value
            ):
                raise AdminOperationsConflict(
                    f"Verified field cannot be overwritten: {field}",
                    code="source_verified_field_protected",
                )

    async def _latest_provenance(
        self, user_id: UUID, record_type: str, record_id: UUID, field_name: str
    ) -> AdminProfileProvenance | None:
        return await self._session.scalar(
            select(AdminProfileProvenance)
            .where(
                AdminProfileProvenance.user_id == user_id,
                AdminProfileProvenance.record_type == record_type,
                AdminProfileProvenance.record_id == record_id,
                AdminProfileProvenance.field_name == field_name,
            )
            .order_by(AdminProfileProvenance.created_at.desc(), AdminProfileProvenance.id.desc())
        )

    @staticmethod
    def _value_hash(value: Any) -> str:
        serialized = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(serialized.encode()).hexdigest()

    async def _admin_provisioned_organization(self, public_id: UUID) -> Organization:
        organization = await self._session.scalar(
            select(Organization).where(Organization.public_id == public_id).with_for_update()
        )
        if organization is None or organization.provisioned_at is None:
            raise NotFoundError("Admin-provisioned organization not found")
        return organization

    @staticmethod
    def _organization_response(organization: Organization) -> AdminOrganizationCreateResponse:
        return AdminOrganizationCreateResponse(
            organization_public_id=organization.public_id,
            name=organization.name,
            organization_type=organization.organization_type,
            verification_state=str(
                getattr(organization.verification_state, "value", organization.verification_state)
            ),
            created_at=organization.created_at,
        )

    @staticmethod
    def _first_hr_response(
        organization: Organization, invitation: OrganizationInvitation
    ) -> AdminFirstHRInvitationResponse:
        return AdminFirstHRInvitationResponse(
            invitation_public_id=invitation.public_id,
            organization_public_id=organization.public_id,
            invitee_email_masked=mask_email(invitation.invitee_email),
            role=OrganizationRole.OWNER,
            status=str(getattr(invitation.status, "value", invitation.status)),
            expires_at=invitation.token_expires_at or invitation.expires_at,
            last_sent_at=invitation.last_sent_at,
        )

    async def _organization_person(
        self, org_public_id: UUID, person_public_id: UUID
    ) -> tuple[Organization, OrganizationPerson]:
        row = (
            await self._session.execute(
                select(Organization, OrganizationPerson)
                .join(
                    OrganizationPerson,
                    OrganizationPerson.organization_id == Organization.id,
                )
                .where(
                    Organization.public_id == org_public_id,
                    OrganizationPerson.public_id == person_public_id,
                )
            )
        ).one_or_none()
        if row is None:
            raise NotFoundError("Organization person not found")
        return row[0], row[1]

    async def _validated_evidence(
        self, person: OrganizationPerson, document_ids: list[UUID]
    ) -> list[UserDocument]:
        if not document_ids:
            return []
        if person.linked_user_id is None:
            raise ValidationAppError(
                "Evidence requires a linked Candidate account",
                code="evidence_subject_not_linked",
            )
        rows = list(
            (
                await self._session.scalars(
                    select(UserDocument).where(
                        UserDocument.id.in_(set(document_ids)),
                        UserDocument.user_id == person.linked_user_id,
                        UserDocument.deleted_at.is_(None),
                        UserDocument.superseded_at.is_(None),
                    )
                )
            ).all()
        )
        if len(rows) != len(set(document_ids)):
            raise ValidationAppError(
                "Evidence document is unavailable for this person",
                code="invalid_evidence_association",
            )
        for row in rows:
            if (
                row.content_type not in _EVIDENCE_MIME_TYPES
                or row.byte_size <= 0
                or row.byte_size > _EVIDENCE_MAX_BYTES
                or not row.checksum_sha256
            ):
                raise ValidationAppError(
                    "Evidence must be a completed PDF or supported image up to 50 MB",
                    code="invalid_evidence",
                )
        return rows

    async def _locked_court_check(
        self, organization_id: UUID, person_id: UUID, public_id: UUID
    ) -> CourtRecordCheck:
        check = await self._session.scalar(
            select(CourtRecordCheck)
            .options(selectinload(CourtRecordCheck.evidence_items))
            .where(
                CourtRecordCheck.organization_id == organization_id,
                CourtRecordCheck.organization_person_id == person_id,
                CourtRecordCheck.public_id == public_id,
            )
            .with_for_update()
        )
        if check is None:
            raise NotFoundError("Court record check not found")
        return check

    async def _reloaded_court_response(
        self, organization: Organization, person: OrganizationPerson, public_id: UUID
    ) -> CourtCheckResponse:
        check = await self._session.scalar(
            select(CourtRecordCheck)
            .options(selectinload(CourtRecordCheck.evidence_items))
            .where(CourtRecordCheck.public_id == public_id)
        )
        if check is None:
            raise NotFoundError("Court record check not found")
        return self._court_response(organization, person, check)

    @staticmethod
    def _court_response(
        organization: Organization, person: OrganizationPerson, check: CourtRecordCheck
    ) -> CourtCheckResponse:
        return CourtCheckResponse(
            public_id=check.public_id,
            organization_public_id=organization.public_id,
            person_public_id=person.public_id,
            status=CourtCheckStatus(check.status),
            searched_at=check.searched_at,
            jurisdiction=check.jurisdiction,
            coverage=check.coverage,
            search_period=check.search_period,
            source=check.source,
            finding=check.finding,
            remarks=check.remarks,
            limitations=check.limitations,
            reviewer_user_id=check.reviewer_user_id,
            evidence_document_ids=[item.document_id for item in check.evidence_items],
            finalized_at=check.finalized_at,
            created_at=check.created_at,
            updated_at=check.updated_at,
        )

    @staticmethod
    def _in_person_response(
        organization: Organization,
        person: OrganizationPerson,
        record: InPersonVerificationRecord,
    ) -> InPersonVerificationResponse:
        return InPersonVerificationResponse(
            public_id=record.public_id,
            organization_public_id=organization.public_id,
            person_public_id=person.public_id,
            verification_type=record.verification_type,
            performed_at=record.performed_at,
            performed_by_user_id=record.performed_by_user_id,
            person_met=record.person_met,
            relationship=record.relationship,
            result=record.result,
            notes=record.notes,
            evidence_document_ids=record.evidence_document_ids,
            created_at=record.created_at,
        )

    async def _organization_event(
        self,
        organization_id: UUID,
        actor_user_id: UUID,
        event_type: str,
        subject_type: str,
        subject_public_id: UUID,
        metadata: dict[str, Any],
    ) -> None:
        self._session.add(
            OrganizationActivityEvent(
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                event_type=event_type,
                subject_type=subject_type,
                subject_public_id=str(subject_public_id),
                metadata_payload=metadata,
            )
        )
        await self._session.flush()
