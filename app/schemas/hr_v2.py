"""HR Workspace V2 additive request and response contracts."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.organization_people.enums import OrganizationPersonEmploymentStatus
from app.schemas.pagination import Page, PageParams

SUPPORTED_VERIFICATION_PREFERENCE_CHECKS = frozenset(
    {"identity", "employment", "education", "references", "address"}
)
DEFAULT_VERIFICATION_PREFERENCES: dict[str, object] = {
    "version": 1,
    "checks": {
        "identity": False,
        "employment": False,
        "education": False,
        "references": False,
        "address": False,
    },
    "reference_count": 0,
}


class EmployeeLifecycleUpdateRequest(BaseModel):
    employment_status: OrganizationPersonEmploymentStatus
    last_working_day: date | None = None

    @model_validator(mode="after")
    def require_exit_date(self):
        if (
            self.employment_status == OrganizationPersonEmploymentStatus.EX_EMPLOYEE
            and self.last_working_day is None
        ):
            raise ValueError("last_working_day is required when employment_status is ex_employee")
        return self


class EmployeeLifecycleResponse(BaseModel):
    person_public_id: UUID
    employment_status: OrganizationPersonEmploymentStatus
    last_working_day: date | None
    updated_at: datetime


def normalize_role_name(value: str) -> str:
    return " ".join(value.strip().split()).casefold()


class OrganizationJobRoleCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    department: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    work_mode: Literal["onsite", "hybrid", "remote"] | None = None
    mode: Literal["draft", "submit"] = "submit"


class OrganizationJobRoleUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    department: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    work_mode: Literal["onsite", "hybrid", "remote"] | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("At least one role field must be supplied")
        return self


class HRUserSummary(BaseModel):
    display_name: str
    email: str


class OrganizationJobRoleResponse(BaseModel):
    public_id: UUID
    name: str
    description: str | None
    department: str | None = None
    location: str | None = None
    work_mode: str | None = None
    status: str = "active"
    created_by_user_id: UUID | None = None
    approved_by_user_id: UUID | None = None
    created_by: HRUserSummary | None = None
    approved_by: HRUserSummary | None = None
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    archived_at: datetime | None = None
    is_active: bool
    assigned_people_count: int = 0
    created_at: datetime
    updated_at: datetime


class HiringRoleDecisionRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str | None = Field(default=None, max_length=1000)


class FormerEmployeeCorrectionCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    proposed_changes: dict[str, Any]
    reason: str = Field(min_length=3, max_length=2000)

    @field_validator("proposed_changes")
    @classmethod
    def validate_changes(cls, value: dict[str, Any]) -> dict[str, Any]:
        allowed = {"role_id", "department", "joining_date", "last_working_day"}
        if not value or set(value) - allowed:
            raise ValueError("Only historical employment fields may be corrected")
        if value.get("role_id") is not None:
            try:
                UUID(str(value["role_id"]))
            except ValueError as exc:
                raise ValueError("role_id must be a valid Hiring Role ID") from exc
        for field in ("joining_date", "last_working_day"):
            raw = value.get(field)
            if raw is None or isinstance(raw, date):
                continue
            try:
                date.fromisoformat(str(raw))
            except ValueError as exc:
                raise ValueError(f"{field} must be an ISO date") from exc
        return value


class FormerEmployeeCorrectionDecisionRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    decision_reason: str | None = Field(default=None, max_length=2000)


class FormerEmployeeCorrectionResponse(BaseModel):
    public_id: UUID
    person_public_id: UUID
    proposed_changes: dict[str, Any]
    before_snapshot: dict[str, Any]
    after_snapshot: dict[str, Any] | None
    reason: str
    status: str
    requested_by_user_id: UUID
    decided_by_user_id: UUID | None
    decided_at: datetime | None
    decision_reason: str | None
    created_at: datetime
    updated_at: datetime


class FormerEmployeeCorrectionListQuery(PageParams):
    status: Literal["pending", "approved", "rejected"] = "pending"


class FormerEmployeeCorrectionPersonSummary(BaseModel):
    public_id: UUID
    display_name: str


class FormerEmployeeCorrectionListItem(BaseModel):
    public_id: UUID
    person: FormerEmployeeCorrectionPersonSummary
    current_values: dict[str, Any]
    proposed_values: dict[str, Any]
    reason: str
    requester: HRUserSummary
    submitted_at: datetime
    status: Literal["pending", "approved", "rejected"]
    reviewer: HRUserSummary | None = None
    decided_at: datetime | None = None
    decision_reason: str | None = None
    updated_at: datetime


class FormerEmployeeCorrectionPage(Page[FormerEmployeeCorrectionListItem]):
    pass


class OrganizationRoleAssignmentRequest(BaseModel):
    role_id: UUID | None = None
    department: str | None = Field(default=None, max_length=255)
    joining_date: date | None = None

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("At least one employment profile field must be supplied")
        return self


class OrganizationRoleAssignmentResponse(BaseModel):
    person_public_id: UUID
    role_id: UUID | None
    role: str | None
    department: str | None
    joining_date: date | None


class OrganizationLogoUploadIntentRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    content_type: str = Field(min_length=1, max_length=64)
    byte_size: int = Field(ge=1, le=5_000_000)


class OrganizationLogoUploadIntentResponse(BaseModel):
    upload_id: UUID
    upload_url: str = Field(repr=False)
    expires_in_seconds: int
    headers_required: dict[str, str]


class OrganizationLogoConfirmRequest(BaseModel):
    upload_id: UUID


class OrganizationLogoResponse(BaseModel):
    has_logo: bool
    display_url: str | None = Field(default=None, repr=False)
    display_url_expires_in_seconds: int | None = None
    content_type: str | None = None
    byte_size: int | None = None
    updated_at: datetime | None = None


class OrganizationVerificationPreferencesUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checks: dict[str, bool]
    reference_count: int = Field(default=0, ge=0, le=10)

    @field_validator("checks")
    @classmethod
    def validate_checks(cls, value: dict[str, bool]) -> dict[str, bool]:
        unsupported = sorted(set(value) - SUPPORTED_VERIFICATION_PREFERENCE_CHECKS)
        if unsupported:
            raise ValueError(
                f"Unsupported verification preference checks: {', '.join(unsupported)}"
            )
        normalized = dict(DEFAULT_VERIFICATION_PREFERENCES["checks"])
        normalized.update(value)
        return normalized

    @model_validator(mode="after")
    def validate_reference_count(self):
        if not self.checks.get("references") and self.reference_count:
            raise ValueError("reference_count requires references to be enabled")
        return self


class OrganizationVerificationPreferencesResponse(BaseModel):
    version: int = 1
    checks: dict[str, bool]
    reference_count: int = 0
    updated_at: datetime | None = None


class VerificationReportStatus(StrEnum):
    INTERIM = "INTERIM"
    FINAL = "FINAL"


class VerificationReportCheckStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    DETAILS_MATCHED = "DETAILS_MATCHED"
    DISCREPANCY = "DISCREPANCY"
    PENDING = "PENDING"
    AWAITING_RESPONSE = "AWAITING_RESPONSE"
    UNABLE_TO_VERIFY = "UNABLE_TO_VERIFY"
    REJECTED = "REJECTED"
    NOT_ORDERED = "NOT_ORDERED"


class VerificationReportHeader(BaseModel):
    person_name: str
    role: str | None = None
    person_id: UUID
    initiated_at: datetime | None = None
    requested_by_organization: str
    masked_email: str | None = None
    masked_phone: str | None = None
    consent_at: datetime | None = None
    trust_score: int | None = Field(default=None, ge=0, le=100)
    report_updated_at: datetime
    report_status: VerificationReportStatus


class VerificationReportCheckSummary(BaseModel):
    check: str
    status: VerificationReportCheckStatus
    updated_at: datetime | None = None
    display_text: str


class VerificationReportIdentityItem(BaseModel):
    declared_values: dict[str, str | None] = Field(default_factory=dict)
    verified_values: dict[str, str | None] = Field(default_factory=dict)
    source: str | None = None
    reviewed_at: datetime | None = None
    evidence_id: UUID | None = None
    status: VerificationReportCheckStatus
    remarks: str | None = None


class VerificationReportEmploymentItem(BaseModel):
    organization: str
    masked_employee_id: str | None = None
    declared_title: str | None = None
    confirmed_title: str | None = None
    declared_start_date: date | None = None
    declared_end_date: date | None = None
    confirmed_start_date: date | None = None
    confirmed_end_date: date | None = None
    employment_type: str | None = None
    confirmed_by: str | None = None
    source: str | None = None
    received_at: datetime | None = None
    evidence_id: UUID | None = None
    reviewer: str | None = None
    remarks: str | None = None
    status: VerificationReportCheckStatus


class VerificationReportEducationItem(BaseModel):
    qualification: str | None = None
    institution: str | None = None
    university: str | None = None
    completion_year: int | None = None
    declared_values: dict[str, str | None] = Field(default_factory=dict)
    confirmed_values: dict[str, str | None] = Field(default_factory=dict)
    source: str | None = None
    confirmation_date: datetime | None = None
    evidence_id: UUID | None = None
    status: VerificationReportCheckStatus


class VerificationReportReferenceItem(BaseModel):
    name: str | None = None
    title_or_relationship: str | None = None
    organization: str | None = None
    known_for: str | None = None
    request_date: datetime | None = None
    follow_up_dates: list[datetime] = Field(default_factory=list)
    response_date: datetime | None = None
    status: VerificationReportCheckStatus
    strengths: str | None = None
    development_areas: str | None = None
    rehire_response: str | None = None
    comments: str | None = None
    evidence_id: UUID | None = None


class VerificationReportAddressItem(BaseModel):
    declared_address: str | None = None
    verification_method: str | None = None
    verified_at: datetime | None = None
    status: VerificationReportCheckStatus
    scope: str | None = None
    physical_visit_performed: bool = False
    evidence_id: UUID | None = None


class VerificationReportCourtSearchItem(BaseModel):
    safe_subject_display: str | None = None
    scope: str | None = None
    search_period: str | None = None
    searched_at: datetime | None = None
    source: str | None = None
    finding: str | None = None
    evidence_id: UUID | None = None
    reviewer: str | None = None
    remarks: str | None = None
    limitations: str | None = None
    status: VerificationReportCheckStatus = VerificationReportCheckStatus.NOT_ORDERED


class VerificationReportOpenItem(BaseModel):
    code: str
    check: str
    display_text: str
    request_public_id: UUID | None = None


class VerificationReportResponse(BaseModel):
    schema_version: Literal["hr_verification_report_v1"] = "hr_verification_report_v1"
    header: VerificationReportHeader
    check_summaries: list[VerificationReportCheckSummary]
    identity: list[VerificationReportIdentityItem] = Field(default_factory=list)
    employment: list[VerificationReportEmploymentItem] = Field(default_factory=list)
    education: list[VerificationReportEducationItem] = Field(default_factory=list)
    references: list[VerificationReportReferenceItem] = Field(default_factory=list)
    address: list[VerificationReportAddressItem] = Field(default_factory=list)
    court_search: list[VerificationReportCourtSearchItem] = Field(default_factory=list)
    open_items: list[VerificationReportOpenItem] = Field(default_factory=list)
    hr_review_required: bool
    metadata: dict[str, Any] = Field(default_factory=dict)
