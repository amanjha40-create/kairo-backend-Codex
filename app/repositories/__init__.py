"""Repository layer — async data access on top of SQLAlchemy 2 `AsyncSession`."""

from app.repositories.admin import AdminRepository
from app.repositories.base import BaseRepository
from app.repositories.criteria import EmploymentDocumentSortField, EmploymentSortField, SortOrder
from app.repositories.employment import EmploymentRepository
from app.repositories.employment_document import EmploymentDocumentRepository
from app.repositories.organization import OrganizationRepository
from app.repositories.password_reset_token import PasswordResetTokenRepository
from app.repositories.passport_share import PassportShareRepository
from app.repositories.passport_share_view import PassportShareViewRepository
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.trust_invitation import TrustInvitationRepository
from app.repositories.user import UserRepository
from app.repositories.verification import VerificationRepository
from app.repositories.verification_audit import VerificationAuditRepository

__all__ = [
    "AdminRepository",
    "BaseRepository",
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
    "VerificationAuditRepository",
    "VerificationRepository",
]
