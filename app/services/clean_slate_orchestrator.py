"""Exact-ID administrative clean-slate planning over canonical account deletion."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.signup_otp import SignupOtpStore
from app.config import Settings
from app.infrastructure.s3.client import get_s3_client
from app.models import (
    AccountDeletion,
    AccountDeletionItem,
    Certification,
    DigiLockerConnection,
    DigiLockerIdentityVerification,
    DocumentSharePack,
    Education,
    EducationDocument,
    Employment,
    EmploymentDocument,
    FreelanceContract,
    FreelanceContractDocument,
    GigPlatform,
    Internship,
    InternshipDocument,
    Notification,
    Organization,
    OrganizationDeletionResolution,
    OrganizationLogoUpload,
    OrganizationMember,
    PassportShareLink,
    PendingSignup,
    PortfolioItem,
    Project,
    RefreshToken,
    ResumeDocument,
    ResumeImportBatch,
    ResumeParsedResult,
    ResumeProcessingJob,
    ResumeRecordProvenance,
    ResumeReviewItem,
    ResumeReviewSession,
    Skill,
    TrustScoreSnapshot,
    User,
    UserDocument,
    UserSocialAccount,
    VerificationRequest,
)
from app.organization.enums import OrganizationRole
from app.services.account_deletion_inventory import safe_key
from app.services.account_deletion_service import AccountDeletionService


class CleanSlateSafetyError(RuntimeError):
    """A stable fail-closed reason; never include PII or object keys."""


@dataclass(frozen=True)
class BackupEvidence:
    rds_snapshot_id: str
    rds_database_id: str
    rds_snapshot_created_at: str
    s3_backup_uri: str
    s3_backup_sha256: str

    def complete(self) -> bool:
        return all(
            (
                self.rds_snapshot_id,
                self.rds_database_id,
                self.rds_snapshot_created_at,
                self.s3_backup_uri,
                len(self.s3_backup_sha256) == 64,
            )
        )


@dataclass(frozen=True)
class CleanSlateAllowlist:
    schema_version: int
    environment: str
    approved_user_ids: frozenset[UUID]
    approved_pending_signup_ids: frozenset[UUID]
    approved_organization_ids: frozenset[UUID]
    approved_storage_object_ids: frozenset[str]
    protected_user_ids: frozenset[UUID]
    backup_evidence: BackupEvidence | None = None


@dataclass(frozen=True)
class CleanSlatePlan:
    environment: str
    users: tuple[str, ...]
    organizations: tuple[str, ...]
    pending_signups: tuple[str, ...]
    dependent_counts: dict[str, int]
    storage_object_ids: tuple[str, ...]
    storage_object_count: int
    missing_referenced_object_count: int
    retained_counts: dict[str, int]
    predicted_post_reset: dict[str, int]

    def as_dict(self) -> dict[str, object]:
        return {
            "environment": self.environment,
            "users": list(self.users),
            "organizations": list(self.organizations),
            "pending_signups": list(self.pending_signups),
            "dependent_counts": self.dependent_counts,
            "storage_object_ids": list(self.storage_object_ids),
            "storage_object_count": self.storage_object_count,
            "missing_referenced_object_count": self.missing_referenced_object_count,
            "retained_counts": self.retained_counts,
            "predicted_post_reset": self.predicted_post_reset,
            "mutations": 0,
        }


HealthCheck = Callable[[], Awaitable[None]]
ProgressCallback = Callable[[dict[str, object]], None]
ObjectLister = Callable[[str, tuple[str, ...]], Awaitable[set[str]]]


def storage_identity(bucket: str, key: str) -> str:
    return hashlib.sha256(f"{bucket}:{key}".encode()).hexdigest()


def verify_artifact_checksum(payload: bytes, expected: str) -> None:
    actual = hashlib.sha256(payload).hexdigest()
    if len(expected) != 64 or not hmac.compare_digest(actual, expected.lower()):
        raise CleanSlateSafetyError("allowlist_checksum_mismatch")


class CleanSlateOrchestrator:
    """Plan exact ownership read-only, then invoke canonical deletion sequentially."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        redis: Redis,
        *,
        object_lister: ObjectLister | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.redis = redis
        self.object_lister = object_lister or self._list_objects

    async def plan(
        self,
        allowlist: CleanSlateAllowlist,
        *,
        require_storage_allowlist: bool = False,
    ) -> CleanSlatePlan:
        environment = self.settings.app_env.value
        if allowlist.schema_version != 1 or allowlist.environment != environment:
            raise CleanSlateSafetyError("allowlist_environment_or_version_mismatch")
        if not allowlist.approved_user_ids:
            raise CleanSlateSafetyError("empty_user_allowlist")

        users = list(
            (
                await self.session.scalars(
                    select(User)
                    .where(User.id.in_(allowlist.approved_user_ids))
                    .order_by(User.id)
                )
            ).all()
        )
        if {user.id for user in users} != set(allowlist.approved_user_ids):
            raise CleanSlateSafetyError("unknown_user_id")
        protected_existing = set(
            (
                await self.session.scalars(
                    select(User.id).where(User.id.in_(allowlist.protected_user_ids))
                )
            ).all()
        )
        if protected_existing != set(allowlist.protected_user_ids):
            raise CleanSlateSafetyError("unknown_protected_identity")
        if environment in {"staging", "production"}:
            required_protected = set(
                (
                    await self.session.scalars(
                        select(User.id).where(
                            User.role != "user",
                            User.deleted_at.is_(None),
                        )
                    )
                ).all()
            )
            if not required_protected.issubset(allowlist.protected_user_ids):
                raise CleanSlateSafetyError("protected_identity_manifest_incomplete")
        if any(
            user.id in allowlist.protected_user_ids or user.role != "user"
            for user in users
        ):
            raise CleanSlateSafetyError("protected_identity_targeted")

        admin_target = await self.session.scalar(
            select(User.id).where(
                User.id.in_(allowlist.approved_user_ids),
                User.role != "user",
            ).limit(1)
        )
        if admin_target is not None:
            raise CleanSlateSafetyError("protected_identity_targeted")

        owner_memberships = list(
            (
                await self.session.execute(
                    select(OrganizationMember.organization_id, OrganizationMember.user_id)
                    .where(
                        OrganizationMember.user_id.in_(allowlist.approved_user_ids),
                        OrganizationMember.role == OrganizationRole.OWNER,
                    )
                    .order_by(OrganizationMember.organization_id)
                )
            ).all()
        )
        creator_org_ids = set(
            (
                await self.session.scalars(
                    select(Organization.id).where(
                        Organization.created_by_user_id.in_(allowlist.approved_user_ids),
                        Organization.closed_at.is_(None),
                    )
                )
            ).all()
        )
        resolved_org_ids = set(
            (
                await self.session.scalars(
                    select(OrganizationDeletionResolution.organization_id)
                    .join(
                        AccountDeletion,
                        AccountDeletion.id == OrganizationDeletionResolution.deletion_id,
                    )
                    .where(
                        AccountDeletion.user_id.in_(allowlist.approved_user_ids),
                        OrganizationDeletionResolution.action.in_({"close", "transfer"}),
                    )
                )
            ).all()
        )
        protected_dependencies = (
            {row.organization_id for row in owner_memberships}
            | creator_org_ids
            | resolved_org_ids
        )
        if not protected_dependencies.issubset(allowlist.approved_organization_ids):
            raise CleanSlateSafetyError("organization_not_allowlisted")
        if not allowlist.approved_organization_ids.issubset(protected_dependencies):
            raise CleanSlateSafetyError("unrelated_organization_allowlisted")

        matched_signup_ids: set[UUID] = set()
        for user in users:
            predicates = [
                PendingSignup.completed_user_id == user.id,
                PendingSignup.email == user.email,
            ]
            if user.phone is not None:
                predicates.append(PendingSignup.phone == user.phone)
            matched_signup_ids.update(
                (
                    await self.session.scalars(
                        select(PendingSignup.id).where(or_(*predicates))
                    )
                ).all()
            )
        approved_signup_ids = set(allowlist.approved_pending_signup_ids)
        if not matched_signup_ids.issubset(approved_signup_ids):
            raise CleanSlateSafetyError("pending_signup_not_allowlisted")
        counts = await self._dependent_counts(allowlist.approved_user_ids)
        scopes, referenced = await self._storage_scope_and_references(
            users,
            allowlist.approved_organization_ids,
        )
        actual_keys = await self.object_lister(self.settings.s3_documents_bucket, tuple(scopes))
        if any(not self._owned_by_any_scope(key, scopes) for key in actual_keys):
            raise CleanSlateSafetyError("unknown_storage_ownership")
        if any(not self._owned_by_any_scope(key, scopes) for key in referenced):
            raise CleanSlateSafetyError("unsafe_storage_reference")
        actual_ids = {
            storage_identity(self.settings.s3_documents_bucket, key) for key in actual_keys
        }
        active_targets = [user for user in users if user.deleted_at is None]
        supplied_storage = allowlist.approved_storage_object_ids
        if require_storage_allowlist and not actual_ids.issubset(supplied_storage):
            raise CleanSlateSafetyError("storage_allowlist_mismatch")
        if (
            require_storage_allowlist
            and len(active_targets) == len(users)
            and supplied_storage != actual_ids
        ):
            raise CleanSlateSafetyError("storage_allowlist_mismatch")
        if require_storage_allowlist and referenced - actual_keys:
            raise CleanSlateSafetyError("referenced_storage_missing")
        if not require_storage_allowlist and supplied_storage and not actual_ids.issubset(
            supplied_storage
        ):
            raise CleanSlateSafetyError("storage_allowlist_mismatch")

        retained = {
            "deletion_requests": int(
                await self.session.scalar(select(func.count()).select_from(AccountDeletion)) or 0
            ),
            "deletion_items": int(
                await self.session.scalar(
                    select(func.count()).select_from(AccountDeletionItem)
                )
                or 0
            ),
            "deleted_user_tombstones": int(
                await self.session.scalar(
                    select(func.count()).select_from(User).where(User.deleted_at.is_not(None))
                ) or 0
            ),
            "non_purgeable_verification_requests": int(
                await self.session.scalar(
                    select(func.count()).select_from(VerificationRequest).where(
                        VerificationRequest.status.not_in(
                            {
                                "draft",
                                "pending_subject_acceptance",
                                "accepted",
                                "pending_subject_submission",
                                "pending_admin_review",
                                "awaiting_subject_corrections",
                                "pending_admin_re_review",
                            }
                        )
                    )
                ) or 0
            ),
        }
        active_users = int(
            await self.session.scalar(
                select(func.count()).select_from(User).where(
                    User.role == "user", User.is_active.is_(True), User.deleted_at.is_(None)
                )
            ) or 0
        )
        predicted = {
            "active_non_admin_users": active_users - sum(user.deleted_at is None for user in users),
            "target_sessions": 0,
            "target_resume_rows": 0,
            "target_digilocker_rows": 0,
            "target_passport_shares": 0,
            "target_storage_objects": 0,
            "catalogue_records": 43119,
        }
        return CleanSlatePlan(
            environment=environment,
            users=tuple(str(user.id) for user in users),
            organizations=tuple(
                str(value) for value in sorted(protected_dependencies, key=str)
            ),
            pending_signups=tuple(
                str(value) for value in sorted(approved_signup_ids, key=str)
            ),
            dependent_counts=counts,
            storage_object_ids=tuple(sorted(actual_ids)),
            storage_object_count=len(actual_keys),
            missing_referenced_object_count=len(referenced - actual_keys),
            retained_counts=retained,
            predicted_post_reset=predicted,
        )

    async def execute(
        self,
        allowlist: CleanSlateAllowlist,
        *,
        confirmation: str,
        backup_verified: bool,
        health_check: HealthCheck,
        progress: ProgressCallback,
    ) -> list[UUID]:
        environment = self.settings.app_env.value
        expected = (
            "EXECUTE PRODUCTION CLEAN SLATE"
            if environment == "production"
            else "EXECUTE STAGING CLEAN SLATE"
        )
        if confirmation != expected:
            raise CleanSlateSafetyError("execution_confirmation_missing")
        if environment == "production" and (
            not backup_verified
            or allowlist.backup_evidence is None
            or not allowlist.backup_evidence.complete()
        ):
            raise CleanSlateSafetyError("production_backup_evidence_missing")
        revision = await self.session.scalar(text("SELECT version_num FROM alembic_version"))
        if revision != "096":
            raise CleanSlateSafetyError("database_revision_mismatch")
        await health_check()
        plan = await self.plan(allowlist, require_storage_allowlist=True)
        deletion_ids: list[UUID] = []
        service = AccountDeletionService(self.session, self.settings, self.redis)
        for raw_user_id in plan.users:
            await health_check()
            user_id = UUID(raw_user_id)
            deletion_id = await service.delete_candidate_account_by_operator(user_id)
            deletion_ids.append(deletion_id)
            progress({
                "event": "clean_slate_user_committed",
                "user_id": raw_user_id,
                "deletion_id": str(deletion_id),
            })
        if allowlist.approved_pending_signup_ids:
            await health_check()
            otp_store = SignupOtpStore(self.redis, self.settings)
            for signup_id in sorted(
                allowlist.approved_pending_signup_ids,
                key=str,
            ):
                await otp_store.clear_all(signup_id)
            await self.session.execute(
                delete(PendingSignup).where(
                    PendingSignup.id.in_(allowlist.approved_pending_signup_ids)
                )
            )
            await self.session.commit()
            progress(
                {
                    "event": "clean_slate_pending_signups_committed",
                    "count": len(allowlist.approved_pending_signup_ids),
                }
            )
        await health_check()
        return deletion_ids

    async def _dependent_counts(self, user_ids: Iterable[UUID]) -> dict[str, int]:
        ids = tuple(user_ids)
        models = {
            "sessions": (RefreshToken, RefreshToken.user_id),
            "social_identities": (UserSocialAccount, UserSocialAccount.user_id),
            "employment": (Employment, Employment.created_by_user_id),
            "education": (Education, Education.user_id),
            "internships": (Internship, Internship.user_id),
            "freelance": (FreelanceContract, FreelanceContract.user_id),
            "gig": (GigPlatform, GigPlatform.user_id),
            "portfolio": (PortfolioItem, PortfolioItem.user_id),
            "certifications": (Certification, Certification.user_id),
            "projects": (Project, Project.user_id),
            "skills": (Skill, Skill.user_id),
            "resume_documents": (ResumeDocument, ResumeDocument.user_id),
            "resume_jobs": (ResumeProcessingJob, ResumeProcessingJob.user_id),
            "resume_results": (ResumeParsedResult, ResumeParsedResult.user_id),
            "resume_reviews": (ResumeReviewSession, ResumeReviewSession.user_id),
            "resume_review_items": (ResumeReviewItem, ResumeReviewItem.user_id),
            "resume_import_batches": (ResumeImportBatch, ResumeImportBatch.user_id),
            "resume_provenance": (ResumeRecordProvenance, ResumeRecordProvenance.user_id),
            "digilocker_connections": (DigiLockerConnection, DigiLockerConnection.user_id),
            "digilocker_verifications": (
                DigiLockerIdentityVerification,
                DigiLockerIdentityVerification.user_id,
            ),
            "passport_shares": (PassportShareLink, PassportShareLink.owner_user_id),
            "notifications": (Notification, Notification.recipient_user_id),
            "trust_scores": (TrustScoreSnapshot, TrustScoreSnapshot.user_id),
        }
        counts = {}
        for name, (model, column) in models.items():
            counts[name] = int(
                await self.session.scalar(
                    select(func.count()).select_from(model).where(column.in_(ids))
                ) or 0
            )
        return counts

    async def _storage_scope_and_references(
        self,
        users: list[User],
        approved_organization_ids: Iterable[UUID],
    ) -> tuple[set[str], set[str]]:
        prefix = self.settings.s3_document_key_prefix.strip("/")
        scopes: set[str] = set()
        references: set[str] = set()
        for user in users:
            uid = user.id
            scopes.update(
                {
                    f"resumes/{uid}/",
                    f"{prefix}/user-documents/{uid}/",
                    f"{prefix}/users/{uid}/employments/",
                    f"{prefix}/users/{uid}/internships/",
                    f"{prefix}/users/{uid}/freelance/",
                    f"{prefix}/certifications/{uid}/",
                    f"{prefix}/portfolio/{uid}/",
                    f"{prefix}/users/{uid}/avatar.",
                }
            )
            education_ids = set(
                (
                    await self.session.scalars(
                        select(Education.id).where(Education.user_id == uid)
                    )
                ).all()
            )
            scopes.update(f"{prefix}/education-documents/{value}/" for value in education_ids)
            pack_ids = set(
                (
                    await self.session.scalars(
                        select(DocumentSharePack.id).where(DocumentSharePack.owner_user_id == uid)
                    )
                ).all()
            )
            scopes.update(f"{prefix}/document-share-packs/{value}/" for value in pack_ids)
            if user.avatar_key:
                references.add(user.avatar_key)
            references.update(
                value
                for value in (
                    await self.session.scalars(
                        select(ResumeDocument.storage_key).where(ResumeDocument.user_id == uid)
                    )
                ).all()
                if value
            )
            references.update(
                value
                for value in (
                    await self.session.scalars(
                        select(UserDocument.object_key).where(UserDocument.user_id == uid)
                    )
                ).all()
                if value
            )
            references.update(
                value
                for value in (
                    await self.session.scalars(
                        select(Certification.object_key).where(Certification.user_id == uid)
                    )
                ).all()
                if value
            )
            references.update(
                value
                for value in (
                    await self.session.scalars(
                        select(PortfolioItem.object_key).where(PortfolioItem.user_id == uid)
                    )
                ).all()
                if value
            )
            employment_ids = select(Employment.id).where(Employment.created_by_user_id == uid)
            education_ids_query = select(Education.id).where(Education.user_id == uid)
            internship_ids = select(Internship.id).where(Internship.user_id == uid)
            freelance_ids = select(FreelanceContract.id).where(FreelanceContract.user_id == uid)
            for model, key_column, predicate in (
                (
                    EmploymentDocument,
                    EmploymentDocument.object_key,
                    EmploymentDocument.employment_id.in_(employment_ids),
                ),
                (
                    EducationDocument,
                    EducationDocument.object_key,
                    EducationDocument.education_id.in_(education_ids_query),
                ),
                (
                    InternshipDocument,
                    InternshipDocument.object_key,
                    InternshipDocument.internship_id.in_(internship_ids),
                ),
                (
                    FreelanceContractDocument,
                    FreelanceContractDocument.object_key,
                    FreelanceContractDocument.freelance_contract_id.in_(freelance_ids),
                ),
            ):
                references.update(
                    value
                    for value in (
                        await self.session.scalars(
                            select(key_column).select_from(model).where(predicate)
                        )
                    ).all()
                    if value
                )
        organization_ids = tuple(approved_organization_ids)
        if organization_ids:
            organization_scope = {
                organization_id: (
                    f"{prefix}/organizations/{organization_id}/logo/"
                )
                for organization_id in organization_ids
            }
            scopes.update(organization_scope.values())
            references.update(
                value
                for value in (
                    await self.session.scalars(
                        select(Organization.logo_object_key).where(
                            Organization.id.in_(organization_ids),
                            Organization.logo_object_key.is_not(None),
                        )
                    )
                ).all()
                if value
            )
            references.update(
                value
                for value in (
                    await self.session.scalars(
                        select(OrganizationLogoUpload.object_key).where(
                            OrganizationLogoUpload.organization_id.in_(organization_ids)
                        )
                    )
                ).all()
                if value
            )
        return scopes, references

    @staticmethod
    def _owned_by_any_scope(key: str, scopes: set[str]) -> bool:
        return safe_key(key) and any(key.startswith(scope) for scope in scopes)

    async def _list_objects(self, bucket: str, scopes: tuple[str, ...]) -> set[str]:
        client = get_s3_client(self.settings)

        def collect() -> set[str]:
            keys: set[str] = set()
            paginator = client.get_paginator("list_objects_v2")
            for scope in scopes:
                for page in paginator.paginate(Bucket=bucket, Prefix=scope):
                    keys.update(item["Key"] for item in page.get("Contents", []))
            return keys

        return await asyncio.to_thread(collect)
