"""Repository layer — async data access on top of SQLAlchemy 2 `AsyncSession`."""

from app.repositories.admin import AdminRepository
from app.repositories.base import BaseRepository
from app.repositories.criteria import EmploymentDocumentSortField, EmploymentSortField, SortOrder
from app.repositories.email_delivery_log import EmailDeliveryLogRepository
from app.repositories.employment import EmploymentRepository
from app.repositories.employment_document import EmploymentDocumentRepository
from app.repositories.organization import OrganizationRepository
from app.repositories.password_reset_token import PasswordResetTokenRepository
from app.repositories.passport_share import PassportShareRepository
from app.repositories.passport_share_view import PassportShareViewRepository
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.trust_invitation import TrustInvitationRepository
from app.repositories.user import UserRepository
from app.repositories.verification_connector import VerificationConnectorRepository, VerificationConnectorRunRepository
from app.repositories.verification_request_evidence import VerificationRequestEvidenceRepository
from app.repositories.verification_request import VerificationRequestRepository
from app.repositories.verification_request_review import VerificationRequestReviewRepository
from app.repositories.verification import VerificationRepository
from app.repositories.verification_audit import VerificationAuditRepository

__all__ = [
    "AdminRepository",
    "BaseRepository",
    "EmailDeliveryLogRepository",
    "EmploymentDocumentRepository",
    "EmploymentDocumentSortField",
    "EmploymentRepository",
    "EmploymentSortField",
    "OrganizationRepository",
    "PasswordResetTokenRepository",
    "PassportShareRepository",
    "PassportShareViewRepository",
    "RefreshTokenRepository",
    "SortOrder",
    "TrustInvitationRepository",
    "UserRepository",
    "VerificationConnectorRepository",
    "VerificationConnectorRunRepository",
    "VerificationRequestEvidenceRepository",
    "VerificationRequestRepository",
    "VerificationRequestReviewRepository",
    "VerificationAuditRepository",
    "VerificationRepository",
]
