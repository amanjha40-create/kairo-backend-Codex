"""Candidate self-service account deletion and data erasure orchestration."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin_review.enums import VerificationRequestReviewStatus
from app.auth.passwords import verify_password
from app.config import Settings
from app.core.constants import Role
from app.employment.enums import VerificationStatus
from app.exceptions import (
    NotFoundError,
    ServiceUnavailableError,
    UnauthorizedError,
    ValidationAppError,
)
from app.infrastructure.sqs.envelope import SqsJobEnvelope
from app.infrastructure.sqs.publisher import send_json_message
from app.integrations.digilocker.transactions import TransactionStore
from app.models import (
    Certification,
    CredentialVerificationRequest,
    DigiLockerConnection,
    DigiLockerIdentityVerification,
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
    TrustSafetyInvestigation,
    TrustScoreSnapshot,
    User,
    UserDocument,
    UserSocialAccount,
    VerificationContact,
    VerificationRequest,
    VerificationRequestEvidence,
    VerificationRequestReview,
)
from app.models.account_deletion import AccountDeletion
from app.organization.enums import OrganizationRole
from app.schemas.account_deletion import AccountDeletionRequest
from app.services.account_deletion_inventory import inventory_deletion
from app.services.account_deletion_policy import revoke_and_scrub_related, scrub_invitation_events
from app.services.clean_slate_synthetic_organization import (
    SyntheticOrganizationPurgeTarget,
    purge_synthetic_organization_for_clean_slate,
)
from app.services.organization_account_deletion import resolve_organizations_for_account_deletion
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

    async def delete_candidate_account(
        self,
        actor_user_id: UUID,
        payload: AccountDeletionRequest,
    ) -> None:
        user = await self._lock_user(actor_user_id)
        if user is None:
            raise NotFoundError("User not found")

        self._assert_confirmation(payload.confirm)
        if user.deleted_at is not None:
            # The HTTP auth dependency still rejects deleted accounts. A duplicate
            # in-flight service invocation is a no-op, not an erasure restart.
            previous = await self._session.scalar(
                select(AccountDeletion.id).where(AccountDeletion.user_id == user.id)
            )
            if previous is None:
                raise NotFoundError("User not found")
            await self._session.commit()
            return

        self._assert_recent_password_reauthentication(user, payload.current_password)
        await self._delete_locked_user(user)

    async def delete_candidate_account_by_operator(self, target_user_id: UUID) -> UUID:
        """Delete one exact Candidate through the canonical transaction.

        This is an internal operator primitive, not an HTTP endpoint. The caller
        must validate its signed allowlist and environment gates first. Role
        enforcement here is intentionally redundant so an admin or service
        identity can never reach the destructive transaction.
        """
        user = await self._lock_user(target_user_id)
        if user is None:
            raise NotFoundError("User not found")
        if user.role != "user":
            raise ValidationAppError("Only Candidate accounts may be operator-deleted")
        if user.deleted_at is not None:
            previous = await self._session.scalar(
                select(AccountDeletion.id).where(AccountDeletion.user_id == user.id)
            )
            if previous is None:
                raise NotFoundError("User not found")
            await self._session.commit()
            return previous
        return await self._delete_locked_user(user)

    async def delete_account_by_clean_slate_operator(
        self,
        target_user_id: UUID,
        *,
        approved_role: str,
        approved_user_ids: frozenset[UUID],
        synthetic_organization_purges: tuple[SyntheticOrganizationPurgeTarget, ...] = (),
    ) -> UUID:
        """Exact-manifest operator deletion for Candidate or one approved Admin.

        This capability is intentionally separate from the ordinary operator
        primitive. The caller must bind both the exact target ID and expected role
        from a checksum-verified Clean Slate v2 manifest.
        """
        user = await self._lock_user(target_user_id)
        if user is None:
            raise NotFoundError("User not found")
        if user.role == Role.SUPERADMIN.value:
            raise ValidationAppError("Superadmin accounts cannot be clean-slate targets")
        if user.deleted_at is not None:
            previous = await self._session.scalar(
                select(AccountDeletion.id).where(AccountDeletion.user_id == user.id)
            )
            if previous is None:
                raise NotFoundError("User not found")
            await self._session.commit()
            return previous
        if approved_role not in {Role.USER.value, Role.ADMIN.value} or user.role != approved_role:
            raise ValidationAppError("Clean-slate account role does not match the manifest")
        if approved_role == Role.ADMIN.value:
            await self.assert_clean_slate_admin_eligible(
                user.id,
                purge_ids=frozenset(
                    target.organization_id for target in synthetic_organization_purges
                ),
            )
        return await self._delete_locked_user(
            user,
            synthetic_organization_purges=synthetic_organization_purges,
            clean_slate_approved_user_ids=approved_user_ids,
        )

    async def assert_clean_slate_admin_eligible(
        self,
        user_id: UUID,
        *,
        purge_ids: frozenset[UUID],
    ) -> None:
        superadmin_count = int(
            await self._session.scalar(
                select(func.count()).select_from(User).where(
                    User.role == Role.SUPERADMIN.value,
                    User.is_active.is_(True),
                    User.deleted_at.is_(None),
                    User.suspended_at.is_(None),
                )
            )
            or 0
        )
        if superadmin_count < 1:
            raise ValidationAppError("An active Superadmin must remain")
        owned_ids = set(
            (
                await self._session.scalars(
                    select(OrganizationMember.organization_id).where(
                        OrganizationMember.user_id == user_id,
                        OrganizationMember.role == OrganizationRole.OWNER,
                        OrganizationMember.suspended_at.is_(None),
                    )
                )
            ).all()
        )
        if not owned_ids.issubset(purge_ids):
            raise ValidationAppError("Admin still owns a preserved organization")
        if await self._active_operational_assignment_count(user_id):
            raise ValidationAppError("Admin has unresolved operational assignments")

    async def _active_operational_assignment_count(self, user_id: UUID) -> int:
        active_request_statuses = {
            value.value
            for value in VerificationRequestStatus
            if value
            not in {
                VerificationRequestStatus.VERIFIED,
                VerificationRequestStatus.REJECTED,
                VerificationRequestStatus.UNABLE_TO_VERIFY,
                VerificationRequestStatus.CANCELLED,
                VerificationRequestStatus.WITHDRAWN_BY_CANDIDATE,
                VerificationRequestStatus.EXPIRED,
            }
        }
        active_review_statuses = {
            VerificationRequestReviewStatus.PENDING,
            VerificationRequestReviewStatus.ASSIGNED,
            VerificationRequestReviewStatus.IN_REVIEW,
            VerificationRequestReviewStatus.CORRECTIONS_REQUESTED,
        }
        active_employment_statuses = {
            VerificationStatus.SUBMITTED.value,
            VerificationStatus.UNDER_REVIEW.value,
            VerificationStatus.ADDITIONAL_INFO_REQUESTED.value,
        }
        counts = (
            await self._session.scalar(
                select(func.count()).select_from(VerificationRequest).where(
                    VerificationRequest.assigned_to_user_id == user_id,
                    VerificationRequest.status.in_(active_request_statuses),
                )
            )
            or 0,
            await self._session.scalar(
                select(func.count()).select_from(VerificationRequestReview).where(
                    VerificationRequestReview.assigned_reviewer_user_id == user_id,
                    VerificationRequestReview.review_status.in_(active_review_statuses),
                )
            )
            or 0,
            await self._session.scalar(
                select(func.count()).select_from(Employment).where(
                    Employment.assigned_reviewer_user_id == user_id,
                    Employment.verification_status.in_(active_employment_statuses),
                    Employment.deleted_at.is_(None),
                )
            )
            or 0,
            await self._session.scalar(
                select(func.count()).select_from(TrustSafetyInvestigation).where(
                    TrustSafetyInvestigation.assigned_admin_user_id == user_id,
                    TrustSafetyInvestigation.status.in_({"open", "in_progress"}),
                )
            )
            or 0,
        )
        return sum(int(value) for value in counts)

    async def _lock_user(self, user_id: UUID) -> User | None:
        return (
            await self._session.execute(
                select(User)
                .where(User.id == user_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()

    async def _delete_locked_user(
        self,
        user: User,
        *,
        synthetic_organization_purges: tuple[SyntheticOrganizationPurgeTarget, ...] = (),
        clean_slate_approved_user_ids: frozenset[UUID] = frozenset(),
    ) -> UUID:
        """Execute the shared, irreversible deletion transaction for a locked user."""

        now = datetime.now(tz=UTC)
        tombstone_email = self._tombstone_email(user.id, role=user.role)
        deleted_name = (
            "Deleted Account" if user.role == Role.ADMIN.value else "Deleted Candidate"
        )
        original_email = user.email

        try:
            snapshot = await self._build_snapshot(user)
            await self._session.execute(
                delete(DigiLockerIdentityVerification).where(
                    DigiLockerIdentityVerification.user_id == user.id
                )
            )
            digilocker_removed = (
                await self._session.execute(
                    delete(DigiLockerConnection)
                    .where(DigiLockerConnection.user_id == user.id)
                    .returning(DigiLockerConnection.id)
                )
            ).scalar_one_or_none() is not None
            deletion = await inventory_deletion(self._session, self._settings, user, snapshot)
            for purge_target in synthetic_organization_purges:
                await purge_synthetic_organization_for_clean_slate(
                    self._session,
                    self._settings,
                    deletion,
                    purge_target,
                    approved_user_ids=clean_slate_approved_user_ids,
                )
            await resolve_organizations_for_account_deletion(self._session, user, deletion)
            await revoke_and_scrub_related(self._session, user.id, snapshot, now)
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
            logger.warning("account_deletion.database_transaction_failed")
            raise ServiceUnavailableError(
                "Account deletion could not be completed. Please try again."
            ) from None

        logger.info(
            "candidate_account_deleted",
            extra={
                "event": "candidate_account_deleted",
                "purged_request_count": len(snapshot.verification_request_ids_to_purge),
                "retained_request_count": len(snapshot.verification_request_ids_to_retain),
            },
        )
        if digilocker_removed:
            try:
                await TransactionStore(self._redis, self._settings).clear(user.id)
            except RedisError:
                # The deleted owner can never complete a callback. Remaining state expires in 10m.
                logger.warning("account_deletion.digilocker_state_cleanup_deferred")
        # Acceleration only. The independently runnable DB sweeper needs no queue.
        if self._settings.sqs_main_queue_url:
            try:
                await send_json_message(
                    SqsJobEnvelope(
                        type="account.deletion.purge",
                        data={"deletion_id": str(deletion.id)},
                    ),
                    settings=self._settings,
                )
            except Exception:
                logger.warning("account_deletion.queue_acceleration_unavailable")
        return deletion.id

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
            (await self._session.execute(select(Education.id).where(Education.user_id == user.id)))
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
            (
                VerificationRequest.subject_user_id.is_(None)
                & (VerificationRequest.subject_email == user.email)
            ),
        ]
        if snapshot.employment_ids:
            request_filters.append(VerificationRequest.employment_id.in_(snapshot.employment_ids))
        if snapshot.education_ids:
            request_filters.append(VerificationRequest.education_id.in_(snapshot.education_ids))

        requests = list(
            (await self._session.execute(select(VerificationRequest).where(or_(*request_filters))))
            .scalars()
            .all()
        )

        for request in requests:
            if request.status in _PURGEABLE_VERIFICATION_STATUSES:
                snapshot.verification_request_ids_to_purge.add(request.id)
            else:
                snapshot.verification_request_ids_to_retain.add(request.id)
                if request.employment_id in snapshot.employment_ids:
                    snapshot.retained_employment_ids.add(request.employment_id)
                if request.education_id in snapshot.education_ids:
                    snapshot.retained_education_ids.add(request.education_id)

        return snapshot

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
            request.claim_snapshot = {}
            request.trust_context = {}
            request.registry_resolution_metadata = {}
            request.target_organization_metadata = {}
            request.organization_internal_note = None
            request.consented_fields = []
            request.consented_evidence_scope = []

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

        from app.models.permanent_address import PermanentAddressVersion

        # Address revisions cascade-delete their derived sessions/reviews. No raw
        # coordinates survive logical account erasure in the private target store.
        await self._session.execute(
            delete(PermanentAddressVersion).where(PermanentAddressVersion.user_id == user.id)
        )
        await self._session.execute(delete(UserDocument).where(UserDocument.user_id == user.id))

        await self._session.execute(
            delete(EmploymentDocument).where(
                EmploymentDocument.employment_id.in_(snapshot.employment_ids)
            )
        )
        await self._session.execute(
            delete(EducationDocument).where(
                EducationDocument.education_id.in_(snapshot.education_ids)
            )
        )
        await self._session.execute(
            delete(InternshipDocument).where(
                InternshipDocument.internship_id.in_(snapshot.internship_ids)
            )
        )
        await self._session.execute(
            delete(FreelanceContractDocument).where(
                FreelanceContractDocument.freelance_contract_id.in_(snapshot.freelance_ids)
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
                        select(Employment).where(
                            Employment.id.in_(snapshot.retained_employment_ids)
                        )
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                row.deleted_at = now
                row.subject_full_name = deleted_name
                row.subject_email = None
                row.reviewer_summary = None
                row.pending_info_request = None
                row.extraction_preview = None

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
                row.reviewer_note = None

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
            await scrub_invitation_events(self._session, invitation.id)
            invitation.subject_name = deleted_name
            invitation.subject_email = tombstone_email
            invitation.subject_phone = None
            invitation.purpose = None
            invitation.message = None
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
        user.suspension_reason = None
        user.deleted_at = now

    def _tombstone_email(self, user_id: UUID, *, role: str = Role.USER.value) -> str:
        label = "account" if role == Role.ADMIN.value else "candidate"
        return f"deleted-{label}+{user_id.hex}@deleted.kairoid.invalid"
