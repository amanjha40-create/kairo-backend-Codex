"""Service-layer dependency wiring — keeps route signatures minimal."""

from __future__ import annotations

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_session
from app.infrastructure.redis.deps import get_redis
from app.services import (
    AdminDirectoryService,
    AdminVerificationService,
    AuthService,
    ConnectorExecutionService,
    ConnectorRegistryService,
    ConnectorResultNormalizer,
    ConnectorSelectionService,
    CredentialVerificationService,
    DocumentUploadService,
    EmailDeliveryService,
    EmployerVerificationService,
    EmploymentDocumentService,
    EmploymentService,
    NotificationChannelRegistry,
    NotificationDispatcher,
    NotificationEmailChannel,
    NotificationPreferenceService,
    NotificationService,
    NotificationTemplateResolver,
    OrganizationService,
    PassportEngineService,
    PassportShareService,
    PassportShareViewService,
    PublicPassportService,
    TrustScoreService,
    TrustInvitationService,
    TrustRegistryResolutionService,
    TrustRegistrySearchService,
    TrustRegistryService,
    UserService,
    VerificationRequestAdminReviewService,
    VerificationRequestService,
    VerificationQueueService,
    VerificationService,
)
from app.services.resume_service import ResumeService


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


def get_resume_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ResumeService:
    return ResumeService(session, settings)


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


def get_admin_directory_service(session: AsyncSession = Depends(get_session)) -> AdminDirectoryService:
    return AdminDirectoryService(session)


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


def get_notification_preference_service(
    session: AsyncSession = Depends(get_session),
) -> NotificationPreferenceService:
    return NotificationPreferenceService(session)


def get_notification_template_resolver() -> NotificationTemplateResolver:
    return NotificationTemplateResolver()


def get_notification_channel_registry(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> NotificationChannelRegistry:
    return NotificationChannelRegistry(
        handlers=(
            NotificationEmailChannel(EmailDeliveryService(session, settings)),
        ),
    )


def get_notification_dispatcher(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> NotificationDispatcher:
    registry = NotificationChannelRegistry(
        handlers=(
            NotificationEmailChannel(EmailDeliveryService(session, settings)),
        ),
    )
    return NotificationDispatcher(registry)


def get_notification_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> NotificationService:
    preferences = NotificationPreferenceService(session)
    template_resolver = NotificationTemplateResolver()
    registry = NotificationChannelRegistry(
        handlers=(
            NotificationEmailChannel(EmailDeliveryService(session, settings)),
        ),
    )
    dispatcher = NotificationDispatcher(registry)
    return NotificationService(
        session,
        settings=settings,
        preferences=preferences,
        template_resolver=template_resolver,
        channel_registry=registry,
        dispatcher=dispatcher,
    )


def get_trust_registry_service(session: AsyncSession = Depends(get_session)) -> TrustRegistryService:
    return TrustRegistryService(session)


def get_trust_registry_search_service(session: AsyncSession = Depends(get_session)) -> TrustRegistrySearchService:
    return TrustRegistrySearchService(session)


def get_trust_registry_resolution_service(
    session: AsyncSession = Depends(get_session),
) -> TrustRegistryResolutionService:
    return TrustRegistryResolutionService(session)


def get_verification_request_service(
    session: AsyncSession = Depends(get_session),
) -> VerificationRequestService:
    return VerificationRequestService(session)


def get_connector_registry_service(
    session: AsyncSession = Depends(get_session),
) -> ConnectorRegistryService:
    return ConnectorRegistryService(session)


def get_connector_selection_service(
    session: AsyncSession = Depends(get_session),
) -> ConnectorSelectionService:
    registry = ConnectorRegistryService(session)
    return ConnectorSelectionService(registry)


def get_connector_result_normalizer() -> ConnectorResultNormalizer:
    return ConnectorResultNormalizer()


def get_connector_execution_service(
    session: AsyncSession = Depends(get_session),
) -> ConnectorExecutionService:
    registry = ConnectorRegistryService(session)
    normalizer = ConnectorResultNormalizer()
    return ConnectorExecutionService(session, registry, normalizer)


def get_verification_request_admin_review_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> VerificationRequestAdminReviewService:
    return VerificationRequestAdminReviewService(session, settings)


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
