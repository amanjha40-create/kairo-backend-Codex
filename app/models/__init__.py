"""Import models for Alembic metadata discovery."""

from app.models.certification import Certification
from app.models.credential_verification_request import CredentialVerificationRequest
from app.models.education import Education
from app.models.freelance_contract import FreelanceContract
from app.models.freelance_contract_document import FreelanceContractDocument
from app.models.gig_platform import GigPlatform
from app.models.internship import Internship
from app.models.internship_document import InternshipDocument
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.passport_share_link import PassportShareLink
from app.models.passport_share_view import PassportShareView
from app.models.password_reset_token import PasswordResetToken
from app.models.portfolio import PortfolioItem
from app.models.education_document import EducationDocument
from app.models.employer_verification_request import EmployerVerificationRequest
from app.models.employment import Employment
from app.models.employment_document import EmploymentDocument
from app.models.pending_signup import PendingSignup
from app.models.profile_view import ProfileView
from app.models.refresh_token import RefreshToken
from app.models.trust_invitation import TrustInvitation
from app.models.user import User
from app.models.user_document import UserDocument
from app.models.user_social_account import UserSocialAccount
from app.models.verification_request_evidence import VerificationRequestEvidence
from app.models.verification_request import VerificationRequest
from app.models.verification_request_event import VerificationRequestEvent
from app.models.verification_request_review import VerificationRequestReview
from app.models.verification_audit import VerificationAuditEvent
from app.models.verification_review_correction import VerificationReviewCorrection
from app.models.verification_review_note import VerificationReviewNote

__all__ = [
    "Certification",
    "CredentialVerificationRequest",
    "Education",
    "EducationDocument",
    "EmployerVerificationRequest",
    "Employment",
    "EmploymentDocument",
    "FreelanceContract",
    "FreelanceContractDocument",
    "GigPlatform",
    "Internship",
    "InternshipDocument",
    "Organization",
    "OrganizationMember",
    "PassportShareLink",
    "PassportShareView",
    "PasswordResetToken",
    "PendingSignup",
    "ProfileView",
    "PortfolioItem",
    "RefreshToken",
    "TrustInvitation",
    "User",
    "UserDocument",
    "UserSocialAccount",
    "VerificationRequestEvidence",
    "VerificationRequest",
    "VerificationRequestEvent",
    "VerificationRequestReview",
    "VerificationAuditEvent",
    "VerificationReviewCorrection",
    "VerificationReviewNote",
]
