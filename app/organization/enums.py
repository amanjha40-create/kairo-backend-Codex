"""Organization domain enums."""

from __future__ import annotations

from enum import StrEnum


class OrganizationType(StrEnum):
    EMPLOYER = "employer"
    UNIVERSITY = "university"
    STAFFING_AGENCY = "staffing_agency"
    BACKGROUND_VERIFICATION_PARTNER = "background_verification_partner"
    GOVERNMENT = "government"
    CERTIFICATION_BODY = "certification_body"
    HOSPITAL = "hospital"
    GIG_PLATFORM = "gig_platform"
    FINANCIAL_INSTITUTION = "financial_institution"
    OTHER = "other"


class OrganizationRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    REVIEWER = "reviewer"


class OrganizationVerificationState(StrEnum):
    SETUP_INCOMPLETE = "setup_incomplete"
    VERIFICATION_PENDING = "verification_pending"
    VERIFIED = "verified"
    ADDITIONAL_INFORMATION_REQUIRED = "additional_information_required"


class OrganizationInvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
