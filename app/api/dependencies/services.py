"""Service-layer dependency wiring — keeps route signatures minimal."""

from __future__ import annotations

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_session
from app.infrastructure.redis.deps import get_redis
from app.services import (
    AdminVerificationService,
    AuthService,
    CredentialVerificationService,
    DocumentUploadService,
    EmployerVerificationService,
    EmploymentDocumentService,
    EmploymentService,
    OrganizationService,
    PassportEngineService,
    PassportShareService,
    PassportShareViewService,
    PublicPassportService,
    TrustScoreService,
    TrustInvitationService,
    UserService,
    VerificationQueueService,
    VerificationService,
)


def get_auth_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    redis: Redis = Depends(get_redis),
) -> AuthService:
    return AuthService(session, settings, redis)


def get_user_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> UserService:
    return UserService(session, settings)


def get_employment_service(session: AsyncSession = Depends(get_session)) -> EmploymentService:
    return EmploymentService(session)


def get_employer_verification_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> EmployerVerificationService:
    return EmployerVerificationService(session, settings)


def get_credential_verification_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> CredentialVerificationService:
    return CredentialVerificationService(session, settings)


def get_employment_document_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> EmploymentDocumentService:
    return EmploymentDocumentService(session, settings)


def get_document_upload_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> DocumentUploadService:
    return DocumentUploadService(session, settings)


def get_admin_verification_service(session: AsyncSession = Depends(get_session)) -> AdminVerificationService:
    return AdminVerificationService(session)


def get_verification_service(session: AsyncSession = Depends(get_session)) -> VerificationService:
    return VerificationService(session)


def get_verification_queue_service(session: AsyncSession = Depends(get_session)) -> VerificationQueueService:
    return VerificationQueueService(session)


def get_user_document_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    from app.services.user_document_service import UserDocumentService
    return UserDocumentService(session, settings)


def get_education_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    from app.services.education_service import EducationService
    return EducationService(session, settings)


def get_trust_score_service(session: AsyncSession = Depends(get_session)) -> TrustScoreService:
    return TrustScoreService(session)


def get_organization_service(session: AsyncSession = Depends(get_session)) -> OrganizationService:
    return OrganizationService(session)


def get_trust_invitation_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TrustInvitationService:
    return TrustInvitationService(session, settings)


def get_passport_share_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> PassportShareService:
    return PassportShareService(session, settings)


def get_passport_engine_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> PassportEngineService:
    return PassportEngineService(session, settings)


def get_public_passport_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> PublicPassportService:
    return PublicPassportService(session, settings)


def get_passport_share_view_service(
    session: AsyncSession = Depends(get_session),
) -> PassportShareViewService:
    return PassportShareViewService(session)


def get_portfolio_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    from app.services.portfolio_service import PortfolioService
    return PortfolioService(session, settings)


def get_freelance_contract_service(session: AsyncSession = Depends(get_session)):
    from app.services.freelance_contract_service import FreelanceContractService
    return FreelanceContractService(session)


def get_internship_service(session: AsyncSession = Depends(get_session)):
    from app.services.internship_service import InternshipService
    return InternshipService(session)


def get_gig_platform_service(session: AsyncSession = Depends(get_session)):
    from app.services.gig_platform_service import GigPlatformService
    return GigPlatformService(session)


def get_certification_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    from app.services.certification_service import CertificationService
    return CertificationService(session, settings)


def get_secondary_doc_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    from app.services.secondary_doc_service import SecondaryDocService
    return SecondaryDocService(session, settings)


def get_profile_view_service(session: AsyncSession = Depends(get_session)):
    from app.services.profile_view_service import ProfileViewService
    return ProfileViewService(session)
