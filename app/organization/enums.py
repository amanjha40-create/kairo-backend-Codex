"""Organization domain enums."""

from __future__ import annotations

from enum import StrEnum


class OrganizationType(StrEnum):
    EMPLOYER = "employer"
    UNIVERSITY = "university"
    STAFFING_AGENCY = "staffing_agency"
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
