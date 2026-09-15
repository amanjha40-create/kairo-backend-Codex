"""Public Trust Passport token resolution and response aggregation."""

from __future__ import annotations

import hashlib
import asyncio
from datetime import UTC, datetime
from urllib.parse import quote, urlsplit, parse_qs

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.education.enums import EducationVerificationStatus
from app.employment.enums import VerificationStatus as EmploymentVerificationStatus
from app.exceptions import NotFoundError
from app.models import (
    Certification,
    Education,
    Employment,
    GigPlatform,
    Internship,
    PortfolioItem,
    Project,
    Skill,
    UserDocument,
    User,
)
from app.models.employment_document import EmploymentDocument
from app.models.freelance_contract import FreelanceContract
from app.models.passport_share_link import PassportShareLink
from app.repositories.passport_share import PassportShareRepository
from app.schemas.passport_share import PassportSharePermissions
from app.schemas.public_passport import (
    PublicPassportCertification,
    PublicPassportDocument,
    PublicPassportEducation,
    PublicPassportEmployment,
    PublicPassportFreelance,
    PublicPassportGigPlatform,
    PublicPassportInternship,
    PublicPassportPortfolioItem,
    PublicPassportProfile,
    PublicPassportProject,
    PublicPassportResponse,
    PublicPassportShareMetadata,
    PublicPassportSkill,
    PublicPassportUserDocument,
    PublicPassportVault,
    PublicPassportTrustScore,
)
from app.services.passport_sharing_policy import resolve_policy
from app.services.trust_score_service import TrustScoreService
from app.services.user_service import UserService


class PublicPassportService:
    _PUBLIC_EMPLOYMENT_STATUSES = frozenset(
        {
            EmploymentVerificationStatus.DRAFT.value,
            EmploymentVerificationStatus.SUBMITTED.value,
            EmploymentVerificationStatus.UNDER_REVIEW.value,
            EmploymentVerificationStatus.ADDITIONAL_INFO_REQUESTED.value,
            EmploymentVerificationStatus.APPROVED.value,
            EmploymentVerificationStatus.VERIFIED.value,
            EmploymentVerificationStatus.UNABLE_TO_VERIFY.value,
        }
    )
    _PUBLIC_EDUCATION_STATUSES = frozenset(
        {
            EducationVerificationStatus.DRAFT.value,
            EducationVerificationStatus.PENDING.value,
            EducationVerificationStatus.SUBMITTED.value,
            EducationVerificationStatus.UNDER_REVIEW.value,
            EducationVerificationStatus.VERIFIED.value,
            EducationVerificationStatus.UNABLE_TO_VERIFY.value,
        }
    )

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._shares = PassportShareRepository(session)
        self._users = UserService(session, settings)
        self._trust = TrustScoreService(session)

    async def get_by_token(self, raw_token: str) -> PublicPassportResponse:
        link = await self._resolve_active_share(raw_token)
        policy = resolve_policy(link.permissions)
        permissions = policy.permissions

        profile = await self._users.get_public_profile(link.owner_user_id)
        trust_score = None
        if permissions.show_trust_score:
            score = await self._trust.calculate_trust_score(link.owner_user_id)
            trust_score = PublicPassportTrustScore.model_validate(score.model_dump())

        vault = await self.build_vault_for_user(
            link.owner_user_id, permissions, public_only=True,
            sharing_mode=policy.mode if policy.version == 2 else None,
        )
        return PublicPassportResponse(
            profile=PublicPassportProfile(
                full_name=profile.full_name,
                headline=profile.headline if permissions.include_profile else None,
                location=profile.location if permissions.include_profile else None,
                avatar_url=(f"/api/v1/public/passport/{quote(raw_token, safe='')}/photo"
                            if permissions.show_photo and permissions.include_profile and profile.avatar_url else None),
                profile_slug=profile.profile_slug if permissions.include_profile else None,
            ),
            trust_score=trust_score,
            vault=vault,
            share=PublicPassportShareMetadata(
                id=link.id,
                label=link.label,
                expires_at=link.expires_at,
                track_views=link.track_views,
                permissions=permissions,
                policy_version=policy.version,
                sharing_mode=policy.mode,
            ),
        )

    async def get_photo_by_token(self, raw_token: str) -> tuple[bytes, str]:
        link = await self._resolve_active_share(raw_token)
        permissions = resolve_policy(link.permissions).permissions
        if not permissions.include_profile or not permissions.show_photo:
            raise NotFoundError("Trust Passport not found")
        user = (await self._session.execute(select(User).where(
            User.id == link.owner_user_id, User.deleted_at.is_(None),
        ))).scalar_one_or_none()
        if user is None or not user.avatar_key or not self._settings.s3_documents_bucket:
            raise NotFoundError("Photo not found")

        def read_photo():
            from app.infrastructure.s3.client import get_s3_client
            response = get_s3_client(self._settings).get_object(
                Bucket=self._settings.s3_documents_bucket, Key=user.avatar_key,
            )
            body = response["Body"]
            try:
                content_type = str(response.get("ContentType", "")).split(";")[0].lower()
                if content_type not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
                    raise NotFoundError("Photo not found")
                content = body.read(5 * 1024 * 1024 + 1)
                if not content or len(content) > 5 * 1024 * 1024:
                    raise NotFoundError("Photo not found")
                return content, content_type
            finally:
                body.close()
        try:
            return await asyncio.to_thread(read_photo)
        except Exception as exc:
            raise NotFoundError("Photo not found") from exc

    async def _resolve_active_share(self, raw_token: str) -> PassportShareLink:
        link = await self._shares.get_by_token_hash(self._hash_token(raw_token))
        if link is None:
            raise NotFoundError("Trust Passport not found")
        if link.revoked_at is not None:
            raise NotFoundError("Trust Passport not found")
        if link.expires_at is not None and link.expires_at <= datetime.now(tz=UTC):
            raise NotFoundError("Trust Passport not found")
        return link

    async def build_vault_for_user(
        self,
        user_id,
        permissions: PassportSharePermissions,
        *,
        public_only: bool = False,
        sharing_mode: str | None = None,
    ) -> PublicPassportVault:
        show_documents = permissions.show_documents

        employments: list[PublicPassportEmployment] = []
        if permissions.include_employments:
            employment_query = (
                select(Employment)
                .where(
                    Employment.created_by_user_id == user_id,
                    Employment.deleted_at.is_(None),
                )
                .order_by(Employment.start_date.desc())
            )
            if public_only:
                employment_query = employment_query.where(
                    Employment.verification_status.in_({"verified"} if sharing_mode == "verified_only" else self._PUBLIC_EMPLOYMENT_STATUSES),
                )
            emp_rows = (await self._session.execute(employment_query)).scalars().all()

            doc_rows: list[EmploymentDocument] = []
            emp_ids = [row.id for row in emp_rows]
            if show_documents and emp_ids:
                doc_rows = (await self._session.execute(
                    select(EmploymentDocument).where(
                        EmploymentDocument.employment_id.in_(emp_ids),
                        EmploymentDocument.deleted_at.is_(None),
                    )
                )).scalars().all()

            docs_by_emp: dict = {row.id: [] for row in emp_rows}
            for doc in doc_rows:
                docs_by_emp[doc.employment_id].append(
                    PublicPassportDocument(
                        id=doc.id,
                        document_type=str(doc.document_type),
                        original_filename=doc.original_filename,
                        byte_size=doc.byte_size,
                        verification_status=doc.verification_status,
                    )
                )

            employments = [
                PublicPassportEmployment(
                    id=row.id,
                    employer_legal_name=(
                        row.employer_legal_name if permissions.show_employer_names else None
                    ),
                    job_title=row.job_title,
                    start_date=row.start_date,
                    end_date=row.end_date,
                    verification_status=row.verification_status,
                    verification_method=row.verification_method,
                    documents=docs_by_emp.get(row.id, []),
                )
                for row in emp_rows
            ]

        educations: list[PublicPassportEducation] = []
        if permissions.include_educations:
            education_query = (
                select(Education)
                .where(Education.user_id == user_id, Education.deleted_at.is_(None))
                .order_by(Education.start_date.desc())
            )
            if public_only:
                education_query = education_query.where(
                    Education.verification_status.in_({"verified"} if sharing_mode == "verified_only" else self._PUBLIC_EDUCATION_STATUSES),
                )
            edu_rows = (await self._session.execute(education_query)).scalars().all()
            educations = [
                PublicPassportEducation(
                    id=row.id,
                    institution_name=row.institution_name,
                    degree=row.degree,
                    field_of_study=row.field_of_study,
                    education_level=row.education_level,
                    grade=row.grade,
                    start_date=row.start_date,
                    start_date_precision=row.start_date_precision,
                    end_date=row.end_date,
                    end_date_precision=row.end_date_precision,
                    is_currently_studying=row.is_currently_studying,
                    verification_status=row.verification_status,
                )
                for row in edu_rows
            ]

        internships: list[PublicPassportInternship] = []
        if permissions.include_internships:
            rows = (await self._session.execute(
                select(Internship)
                .where(Internship.user_id == user_id, Internship.deleted_at.is_(None))
                .order_by(Internship.start_date.desc())
            )).scalars().all()
            internships = [
                PublicPassportInternship(
                    id=row.id,
                    company_name=row.company_name,
                    role=row.role,
                    description=row.description,
                    start_date=row.start_date,
                    end_date=row.end_date,
                    is_ongoing=row.is_ongoing,
                    verification_status=row.verification_status,
                )
                for row in rows
            ]

        freelance: list[PublicPassportFreelance] = []
        if permissions.include_freelance:
            rows = (await self._session.execute(
                select(FreelanceContract)
                .where(FreelanceContract.user_id == user_id, FreelanceContract.deleted_at.is_(None))
                .order_by(FreelanceContract.start_date.desc())
            )).scalars().all()
            freelance = [
                PublicPassportFreelance(
                    id=row.id,
                    client_name=row.client_name,
                    project_title=row.project_title,
                    description=row.description,
                    start_date=row.start_date,
                    end_date=row.end_date,
                    is_ongoing=row.is_ongoing,
                    verification_status=row.verification_status,
                )
                for row in rows
            ]

        gig_platforms: list[PublicPassportGigPlatform] = []
        if permissions.include_gig_platforms:
            rows = (await self._session.execute(
                select(GigPlatform)
                .where(GigPlatform.user_id == user_id, GigPlatform.deleted_at.is_(None))
                .order_by(GigPlatform.started_at.desc())
            )).scalars().all()
            gig_platforms = [
                PublicPassportGigPlatform(
                    id=row.id,
                    platform_name=row.platform_name,
                    partner_role=row.partner_role,
                    started_at=row.started_at,
                    ended_at=row.ended_at,
                    is_active=row.is_active,
                    rating=float(row.rating) if row.rating is not None else None,
                    verification_status=row.verification_status,
                )
                for row in rows
            ]

        portfolio: list[PublicPassportPortfolioItem] = []
        if permissions.include_portfolio:
            rows = (await self._session.execute(
                select(PortfolioItem)
                .where(PortfolioItem.user_id == user_id, PortfolioItem.deleted_at.is_(None))
                .order_by(PortfolioItem.created_at.desc())
            )).scalars().all()
            portfolio = [
                PublicPassportPortfolioItem(
                    id=row.id,
                    title=row.title,
                    description=row.description,
                    url=row.url,
                    tags=[tag.strip() for tag in (row.tags or "").split(",") if tag.strip()],
                    verification_status=row.verification_status,
                )
                for row in rows
            ]

        certifications: list[PublicPassportCertification] = []
        if permissions.include_certifications:
            rows = (await self._session.execute(
                select(Certification)
                .where(Certification.user_id == user_id, Certification.deleted_at.is_(None))
                .order_by(Certification.issued_date.desc())
            )).scalars().all()
            certifications = [
                PublicPassportCertification(
                    id=row.id,
                    title=row.title,
                    issuing_organization=row.issuing_organization,
                    issued_date=row.issued_date,
                    expiry_date=row.expiry_date,
                    does_not_expire=row.does_not_expire,
                    credential_id=row.credential_id,
                    credential_url=row.credential_url,
                    verification_status=row.verification_status,
                )
                for row in rows
            ]

        user_documents: list[PublicPassportUserDocument] = []
        if permissions.include_user_documents and show_documents:
            rows = (await self._session.execute(
                select(UserDocument)
                .where(UserDocument.user_id == user_id, UserDocument.deleted_at.is_(None))
                .order_by(UserDocument.created_at.desc())
            )).scalars().all()
            user_documents = [
                PublicPassportUserDocument(
                    id=row.id,
                    document_type=row.document_type,
                    original_filename=row.original_filename,
                    byte_size=row.byte_size,
                    verification_status=row.verification_status,
                    expires_at=row.expires_at,
                )
                for row in rows
            ]

        skills = []
        if permissions.include_skills:
            skill_rows = (
                await self._session.execute(
                    select(Skill)
                    .where(Skill.user_id == user_id, Skill.deleted_at.is_(None))
                    .order_by(Skill.name.asc())
                )
            ).scalars().all()
            skills = [
                PublicPassportSkill(name=row.name, verification_status=row.verification_status)
                for row in skill_rows
            ]

        projects = []
        if permissions.include_projects:
            project_rows = (
                await self._session.execute(
                    select(Project)
                    .where(Project.user_id == user_id, Project.deleted_at.is_(None))
                    .order_by(
                        Project.is_ongoing.desc(),
                        Project.start_date.desc().nullslast(),
                        Project.created_at.desc(),
                    )
                )
            ).scalars().all()
            projects = [
                PublicPassportProject(
                    id=row.id,
                    title=row.title,
                    role=row.role,
                    description=row.description,
                    start_date=row.start_date,
                    end_date=row.end_date,
                    is_ongoing=row.is_ongoing,
                    project_url=row.project_url,
                    repository_url=row.repository_url,
                    organization_name=row.organization_name,
                    verification_status=row.verification_status,
                )
                for row in project_rows
            ]

        vault = PublicPassportVault(
            employments=employments,
            educations=educations,
            internships=internships,
            freelance=freelance,
            gig_platforms=gig_platforms,
            portfolio=portfolio,
            certifications=certifications,
            user_documents=user_documents,
            skills=skills,
            projects=projects,
        )
        if public_only:
            for category in type(vault).model_fields:
                for record in getattr(vault, category):
                    if sharing_mode is not None:
                        if category not in {"employments", "educations"} or record.verification_status == "approved":
                            record.verification_status = "self_declared"
                    for field in ("url", "credential_url", "project_url", "repository_url"):
                        if hasattr(record, field):
                            setattr(record, field, safe_recipient_url(getattr(record, field)))
        return vault

    def _hash_token(self, raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def safe_recipient_url(value: str | None) -> str | None:
    if not value:
        return None
    try:
        url = urlsplit(value)
        host = (url.hostname or "").lower()
        query = {key.lower() for key in parse_qs(url.query)}
        if url.scheme != "https" or not host or url.username or url.password:
            return None
        if host.endswith(("amazonaws.com", "amazonaws.com.cn")) or any(key.startswith("x-amz-") for key in query):
            return None
        return value
    except ValueError:
        return None
