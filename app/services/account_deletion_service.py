"""Candidate self-service account deletion and data erasure orchestration."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from redis.asyncio import Redis
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import verify_password
from app.auth.signup_otp import SignupOtpStore
from app.config import Settings
from app.core.constants import Role
from app.exceptions import (
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationAppError,
)
from app.infrastructure.s3.client import get_s3_client
from app.models import (
    Certification,
    CredentialVerificationRequest,
    Education,
    EducationDocument,
    EmailDeliveryLog,
    Employment,
    EmploymentDocument,
    FreelanceContract,
    FreelanceContractDocument,
    GigPlatform,
    InstitutionPersonConsent,
    Internship,
    InternshipDocument,
    Notification,
    NotificationPreference,
    OrganizationMember,
    OrganizationPerson,
    PassportShareLink,
    PasswordResetToken,
    PendingSignup,
    PortfolioItem,
    ProfileLanguage,
    ProfileLink,
    ProfileView,
    Project,
    RefreshToken,
    ResumeDocument,
    ResumeImportBatch,
    ResumeImportResult,
    ResumeParsedResult,
    ResumeProcessingJob,
    ResumeRecordProvenance,
    ResumeReviewItem,
    ResumeReviewSession,
    Skill,
    TrustInvitation,
    TrustScoreSnapshot,
    User,
    UserDocument,
    UserSocialAccount,
    VerificationContact,
    VerificationRequest,
    VerificationRequestEvidence,
)
from app.repositories.user import UserRepository
from app.schemas.account_deletion import AccountDeletionRequest
from app.verification_requests.enums import VerificationRequestStatus

logger = logging.getLogger(__name__)


_PURGEABLE_VERIFICATION_STATUSES = frozenset(
    {
        VerificationRequestStatus.DRAFT.value,
        VerificationRequestStatus.PENDING_SUBJECT_ACCEPTANCE.value,
        VerificationRequestStatus.ACCEPTED.value,
        VerificationRequestStatus.PENDING_SUBJECT_SUBMISSION.value,
        VerificationRequestStatus.PENDING_ADMIN_REVIEW.value,
        VerificationRequestStatus.AWAITING_SUBJECT_CORRECTIONS.value,
        VerificationRequestStatus.PENDING_ADMIN_RE_REVIEW.value,
    }
)


@dataclass(slots=True)
class _DeletionSnapshot:
    pending_signup_ids: list[UUID] = field(default_factory=list)
    storage_keys: set[str] = field(default_factory=set)
    employment_ids: set[UUID] = field(default_factory=set)
    retained_employment_ids: set[UUID] = field(default_factory=set)
    education_ids: set[UUID] = field(default_factory=set)
    retained_education_ids: set[UUID] = field(default_factory=set)
    internship_ids: set[UUID] = field(default_factory=set)
    freelance_ids: set[UUID] = field(default_factory=set)
    verification_request_ids_to_purge: set[UUID] = field(default_factory=set)
    verification_request_ids_to_retain: set[UUID] = field(default_factory=set)


class AccountDeletionService:
    """Coordinate irreversible candidate data erasure with shared-audit preservation."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        redis: Redis,
    ) -> None:
        self._session = session
        self._settings = settings
        self._redis = redis
        self._users = UserRepository(session)
        self._otp = SignupOtpStore(redis, settings)

    async def delete_candidate_account(
        self,
        actor_user_id: UUID,
        payload: AccountDeletionRequest,
    ) -> None:
        user = await self._users.get_by_id(actor_user_id)
        if user is None:
            raise NotFoundError("User not found")

        await self._assert_candidate_self_service_eligible(user)
        self._assert_confirmation(payload.confirm)
        self._assert_recent_password_reauthentication(user, payload.current_password)

        snapshot = await self._build_snapshot(user)
        await self._clear_signup_otp_state(snapshot.pending_signup_ids)
        await self._delete_storage_objects(snapshot.storage_keys)

        now = datetime.now(tz=UTC)
        tombstone_email = self._tombstone_email(user.id)
        deleted_name = "Deleted Candidate"
        original_email = user.email

        try:
            await self._purge_verification_requests(snapshot.verification_request_ids_to_purge)
            await self._scrub_retained_verification_records(
                request_ids=snapshot.verification_request_ids_to_retain,
                tombstone_email=tombstone_email,
                deleted_name=deleted_name,
            )
            await self._scrub_trust_invitations(
                user_id=user.id,
                original_email=original_email,
                tombstone_email=tombstone_email,
                deleted_name=deleted_name,
                now=now,
            )
            await self._session.flush()
            await self._purge_candidate_exclusive_rows(user, snapshot)
            await self._soft_delete_retained_career_records(snapshot, now, deleted_name)
            await self._scrub_shared_links(user.id)
            self._scrub_user_row(user, now, tombstone_email, deleted_name)
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

        logger.info(
            "candidate_account_deleted",
            extra={
                "event": "candidate_account_deleted",
                "user_id": str(user.id),
                "purged_request_count": len(snapshot.verification_request_ids_to_purge),
                "retained_request_count": len(snapshot.verification_request_ids_to_retain),
            },
        )

    async def _assert_candidate_self_service_eligible(self, user: User) -> None:
        if user.role != Role.USER.value:
            raise ForbiddenError("Only candidate accounts can use self-service account deletion")

        membership_count = int(
            (
                await self._session.execute(
                    select(OrganizationMember).where(OrganizationMember.user_id == user.id).limit(1)
                )
            )
            .scalars()
            .first()
            is not None
        )
        if membership_count:
            raise ForbiddenError(
                "Organization workspace accounts cannot use "
                "candidate self-service account deletion"
            )

    def _assert_confirmation(self, confirm: str) -> None:
        if confirm != "DELETE":
            raise ValidationAppError('Account deletion requires confirm="DELETE"')

    def _assert_recent_password_reauthentication(
        self,
        user: User,
        current_password: str | None,
    ) -> None:
        if user.password_hash is None:
            return
        if not current_password or not verify_password(current_password, user.password_hash):
            raise UnauthorizedError("Current password is incorrect")

    async def _build_snapshot(self, user: User) -> _DeletionSnapshot:
        snapshot = _DeletionSnapshot()

        snapshot.pending_signup_ids = list(
            (
                await self._session.execute(
                    select(PendingSignup.id).where(
                        or_(
                            PendingSignup.email == user.email,
                            PendingSignup.completed_user_id == user.id,
                            PendingSignup.phone == user.phone if user.phone is not None else False,
                        )
                    )
                )
            )
            .scalars()
            .all()
        )

        snapshot.employment_ids = set(
            (
                await self._session.execute(
                    select(Employment.id).where(Employment.created_by_user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        snapshot.education_ids = set(
            (
                await self._session.execute(
                    select(Education.id).where(Education.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        snapshot.internship_ids = set(
            (
                await self._session.execute(
                    select(Internship.id).where(Internship.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        snapshot.freelance_ids = set(
            (
                await self._session.execute(
                    select(FreelanceContract.id).where(FreelanceContract.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )

        request_filters = [
            VerificationRequest.subject_user_id == user.id,
            VerificationRequest.requested_by_user_id == user.id,
            VerificationRequest.subject_email == user.email,
        ]
        if snapshot.employment_ids:
            request_filters.append(VerificationRequest.employment_id.in_(snapshot.employment_ids))
        if snapshot.education_ids:
            request_filters.append(VerificationRequest.education_id.in_(snapshot.education_ids))

        requests = list(
            (
                await self._session.execute(
                    select(VerificationRequest).where(or_(*request_filters))
                )
            )
            .scalars()
            .all()
        )

        for request in requests:
            if request.status in _PURGEABLE_VERIFICATION_STATUSES:
                snapshot.verification_request_ids_to_purge.add(request.id)
            else:
                snapshot.verification_request_ids_to_retain.add(request.id)
                if request.employment_id is not None:
                    snapshot.retained_employment_ids.add(request.employment_id)
                if request.education_id is not None:
                    snapshot.retained_education_ids.add(request.education_id)

        storage_statements = [
            select(ResumeDocument.storage_key).where(ResumeDocument.user_id == user.id),
            select(UserDocument.object_key).where(UserDocument.user_id == user.id),
            select(EmploymentDocument.object_key).where(
                or_(
                    EmploymentDocument.uploaded_by_user_id == user.id,
                    (
                        EmploymentDocument.employment_id.in_(snapshot.employment_ids)
                        if snapshot.employment_ids
                        else False
                    ),
                )
            ),
            select(EducationDocument.object_key).where(
                or_(
                    EducationDocument.uploaded_by_user_id == user.id,
                    (
                        EducationDocument.education_id.in_(snapshot.education_ids)
                        if snapshot.education_ids
                        else False
                    ),
                )
            ),
            select(Certification.object_key).where(
                Certification.user_id == user.id,
                Certification.object_key.is_not(None),
            ),
            select(PortfolioItem.object_key).where(
                PortfolioItem.user_id == user.id,
                PortfolioItem.object_key.is_not(None),
            ),
            select(InternshipDocument.object_key).where(
                or_(
                    InternshipDocument.uploaded_by_user_id == user.id,
                    (
                        InternshipDocument.internship_id.in_(snapshot.internship_ids)
                        if snapshot.internship_ids
                        else False
                    ),
                )
            ),
            select(FreelanceContractDocument.object_key).where(
                or_(
                    FreelanceContractDocument.uploaded_by_user_id == user.id,
                    (
                        FreelanceContractDocument.freelance_contract_id.in_(
                            snapshot.freelance_ids
                        )
                        if snapshot.freelance_ids
                        else False
                    ),
                )
            ),
        ]

        if user.avatar_key:
            snapshot.storage_keys.add(user.avatar_key)

        for stmt in storage_statements:
            keys = list((await self._session.execute(stmt)).scalars().all())
            snapshot.storage_keys.update({key for key in keys if key})

        return snapshot

    async def _clear_signup_otp_state(self, signup_ids: list[UUID]) -> None:
        for signup_id in signup_ids:
            await self._otp.clear_all(signup_id)

    async def _delete_storage_objects(self, object_keys: set[str]) -> None:
        if not object_keys:
            return

        bucket = self._settings.s3_documents_bucket
        if not bucket:
            raise ValidationAppError(
                "Account deletion cannot proceed because document storage "
                "is not configured"
            )

        def _delete_one(object_key: str) -> None:
            client = get_s3_client(self._settings)
            client.delete_object(Bucket=bucket, Key=object_key)

        for object_key in sorted(object_keys):
            await asyncio.to_thread(_delete_one, object_key)

    async def _purge_verification_requests(self, request_ids: set[UUID]) -> None:
        if not request_ids:
            return
        await self._session.execute(
            delete(VerificationRequest).where(VerificationRequest.id.in_(request_ids))
        )

    async def _scrub_retained_verification_records(
        self,
        *,
        request_ids: set[UUID],
        tombstone_email: str,
        deleted_name: str,
    ) -> None:
        if not request_ids:
            return

        requests = list(
            (
                await self._session.execute(
                    select(VerificationRequest).where(VerificationRequest.id.in_(request_ids))
                )
            )
            .scalars()
            .all()
        )
        for request in requests:
            request.subject_user_id = None
            request.subject_name = deleted_name
            request.subject_email = tombstone_email
            request.candidate_response = None
            request.candidate_response_submitted_at = None

        contacts = list(
            (
                await self._session.execute(
                    select(VerificationContact).where(
                        VerificationContact.verification_request_id.in_(request_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        for contact in contacts:
            contact.candidate_note = None

        evidence_rows = list(
            (
                await self._session.execute(
                    select(VerificationRequestEvidence).where(
                        VerificationRequestEvidence.verification_request_id.in_(request_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        for evidence in evidence_rows:
            evidence.document_id = None
            evidence.employment_document_id = None
            evidence.education_document_id = None
            evidence.value = None

    async def _purge_candidate_exclusive_rows(
        self,
        user: User,
        snapshot: _DeletionSnapshot,
    ) -> None:
        await self._session.execute(
            delete(ProfileLanguage).where(ProfileLanguage.user_id == user.id)
        )
        await self._session.execute(delete(ProfileLink).where(ProfileLink.user_id == user.id))
        await self._session.execute(
            delete(ProfileView).where(ProfileView.profile_user_id == user.id)
        )
        await self._session.execute(
            update(ProfileView)
            .where(ProfileView.viewer_user_id == user.id)
            .values(viewer_user_id=None)
        )

        await self._session.execute(
            delete(NotificationPreference).where(NotificationPreference.user_id == user.id)
        )
        await self._session.execute(
            delete(Notification).where(
                or_(
                    Notification.recipient_user_id == user.id,
                    Notification.recipient_email == user.email,
                    Notification.recipient_phone == user.phone if user.phone is not None else False,
                )
            )
        )
        await self._session.execute(
            delete(EmailDeliveryLog).where(
                or_(
                    EmailDeliveryLog.recipient_user_id == user.id,
                    EmailDeliveryLog.recipient_email == user.email,
                )
            )
        )

        await self._session.execute(
            delete(PassportShareLink).where(PassportShareLink.owner_user_id == user.id)
        )
        await self._session.execute(
            delete(TrustScoreSnapshot).where(TrustScoreSnapshot.user_id == user.id)
        )

        await self._session.execute(
            delete(UserSocialAccount).where(UserSocialAccount.user_id == user.id)
        )
        await self._session.execute(delete(RefreshToken).where(RefreshToken.user_id == user.id))
        await self._session.execute(
            delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
        )
        await self._session.execute(
            delete(PendingSignup).where(
                or_(
                    PendingSignup.completed_user_id == user.id,
                    PendingSignup.email == user.email,
                    PendingSignup.phone == user.phone if user.phone is not None else False,
                )
            )
        )

        await self._session.execute(delete(UserDocument).where(UserDocument.user_id == user.id))

        await self._session.execute(
            delete(EmploymentDocument).where(
                or_(
                    EmploymentDocument.uploaded_by_user_id == user.id,
                    (
                        EmploymentDocument.employment_id.in_(snapshot.employment_ids)
                        if snapshot.employment_ids
                        else False
                    ),
                )
            )
        )
        await self._session.execute(
            delete(EducationDocument).where(
                or_(
                    EducationDocument.uploaded_by_user_id == user.id,
                    (
                        EducationDocument.education_id.in_(snapshot.education_ids)
                        if snapshot.education_ids
                        else False
                    ),
                )
            )
        )
        await self._session.execute(
            delete(InternshipDocument).where(
                or_(
                    InternshipDocument.uploaded_by_user_id == user.id,
                    (
                        InternshipDocument.internship_id.in_(snapshot.internship_ids)
                        if snapshot.internship_ids
                        else False
                    ),
                )
            )
        )
        await self._session.execute(
            delete(FreelanceContractDocument).where(
                or_(
                    FreelanceContractDocument.uploaded_by_user_id == user.id,
                    (
                        FreelanceContractDocument.freelance_contract_id.in_(
                            snapshot.freelance_ids
                        )
                        if snapshot.freelance_ids
                        else False
                    ),
                )
            )
        )

        await self._purge_resume_rows(user.id)

        if snapshot.employment_ids:
            hard_delete_employment_ids = snapshot.employment_ids - snapshot.retained_employment_ids
            if hard_delete_employment_ids:
                await self._session.execute(
                    delete(Employment).where(Employment.id.in_(hard_delete_employment_ids))
                )
        if snapshot.education_ids:
            hard_delete_education_ids = snapshot.education_ids - snapshot.retained_education_ids
            if hard_delete_education_ids:
                await self._session.execute(
                    delete(Education).where(Education.id.in_(hard_delete_education_ids))
                )

        await self._session.execute(delete(Certification).where(Certification.user_id == user.id))
        await self._session.execute(delete(Project).where(Project.user_id == user.id))
        await self._session.execute(delete(PortfolioItem).where(PortfolioItem.user_id == user.id))
        await self._session.execute(delete(Skill).where(Skill.user_id == user.id))
        await self._session.execute(delete(GigPlatform).where(GigPlatform.user_id == user.id))

        if snapshot.internship_ids:
            await self._session.execute(
                delete(CredentialVerificationRequest).where(
                    CredentialVerificationRequest.subject_type == "internship",
                    CredentialVerificationRequest.subject_id.in_(snapshot.internship_ids),
                )
            )
        if snapshot.freelance_ids:
            await self._session.execute(
                delete(CredentialVerificationRequest).where(
                    CredentialVerificationRequest.subject_type == "freelance_contract",
                    CredentialVerificationRequest.subject_id.in_(snapshot.freelance_ids),
                )
            )

        await self._session.execute(delete(Internship).where(Internship.user_id == user.id))
        await self._session.execute(
            delete(FreelanceContract).where(FreelanceContract.user_id == user.id)
        )

    async def _purge_resume_rows(self, user_id: UUID) -> None:
        batch_ids = select(ResumeImportBatch.id).where(ResumeImportBatch.user_id == user_id)
        await self._session.execute(
            delete(ResumeRecordProvenance).where(ResumeRecordProvenance.user_id == user_id)
        )
        await self._session.execute(
            delete(ResumeImportResult).where(ResumeImportResult.import_batch_id.in_(batch_ids))
        )
        await self._session.execute(
            delete(ResumeImportBatch).where(ResumeImportBatch.user_id == user_id)
        )
        await self._session.execute(
            delete(ResumeReviewItem).where(ResumeReviewItem.user_id == user_id)
        )
        await self._session.execute(
            delete(ResumeReviewSession).where(ResumeReviewSession.user_id == user_id)
        )
        await self._session.execute(
            delete(ResumeParsedResult).where(ResumeParsedResult.user_id == user_id)
        )
        await self._session.execute(
            delete(ResumeProcessingJob).where(ResumeProcessingJob.user_id == user_id)
        )
        await self._session.execute(delete(ResumeDocument).where(ResumeDocument.user_id == user_id))

    async def _soft_delete_retained_career_records(
        self,
        snapshot: _DeletionSnapshot,
        now: datetime,
        deleted_name: str,
    ) -> None:
        if snapshot.retained_employment_ids:
            rows = list(
                (
                    await self._session.execute(
                        select(Employment).where(Employment.id.in_(snapshot.retained_employment_ids))
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                row.deleted_at = now
                row.subject_full_name = deleted_name
                row.subject_email = None

        if snapshot.retained_education_ids:
            rows = list(
                (
                    await self._session.execute(
                        select(Education).where(Education.id.in_(snapshot.retained_education_ids))
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                row.deleted_at = now

    async def _scrub_shared_links(self, user_id: UUID) -> None:
        await self._session.execute(
            update(OrganizationPerson)
            .where(OrganizationPerson.linked_user_id == user_id)
            .values(linked_user_id=None)
        )
        await self._session.execute(
            update(InstitutionPersonConsent)
            .where(InstitutionPersonConsent.subject_user_id == user_id)
            .values(subject_user_id=None)
        )

    async def _scrub_trust_invitations(
        self,
        *,
        user_id: UUID,
        original_email: str,
        tombstone_email: str,
        deleted_name: str,
        now: datetime,
    ) -> None:
        invitation_rows = list(
            (
                await self._session.execute(
                    select(TrustInvitation).where(
                        or_(
                            TrustInvitation.accepted_by_user_id == user_id,
                            TrustInvitation.subject_email == original_email,
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        for invitation in invitation_rows:
            invitation.subject_name = deleted_name
            invitation.subject_email = tombstone_email
            invitation.subject_phone = None
            invitation.accepted_by_user_id = None
            invitation.token_hash = hashlib.sha256(
                f"{invitation.id}:{uuid4()}".encode("utf-8")
            ).hexdigest()
            invitation.expires_at = now
            invitation.cancelled_at = invitation.cancelled_at or now

    def _scrub_user_row(
        self,
        user: User,
        now: datetime,
        tombstone_email: str,
        deleted_name: str,
    ) -> None:
        user.email = tombstone_email
        user.password_hash = None
        user.full_name = deleted_name
        user.profile_slug = None
        user.phone = None
        user.current_role = None
        user.industry = None
        user.years_of_experience = None
        user.location = None
        user.location_city = None
        user.location_region = None
        user.location_country = None
        user.headline = None
        user.bio = None
        user.date_of_birth = None
        user.avatar_key = None
        user.is_active = False
        user.email_verified_at = None
        user.phone_verified_at = None
        user.employment_onboarding_completed_at = None
        user.trust_score_consent_at = None
        user.trust_score_consent_version = None
        user.active_organization_id = None
        user.deleted_at = now

    def _tombstone_email(self, user_id: UUID) -> str:
        return f"deleted-candidate+{user_id.hex}@deleted.kairoid.invalid"
