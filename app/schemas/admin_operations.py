"""Privacy-safe API DTOs for Admin Operations V1.1."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.admin_operations.enums import (
    CandidateClaimStatus,
    CourtCheckStatus,
    InPersonVerificationResult,
    InPersonVerificationType,
    ProfileProvenanceSource,
)
from app.organization.enums import OrganizationRole, OrganizationType
from app.organization_people.enums import OrganizationPersonRelationship
from app.schemas.admin_career import payload_contract, validate_payload
from app.schemas.gig_platform import GigPlatformResponse
from app.schemas.portfolio import PortfolioItemResponse
from app.schemas.project import ProjectResponse
from app.schemas.skill import SkillResponse


class AdminCreateCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    phone: str | None = Field(default=None, min_length=8, max_length=32)
    headline: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    idempotency_key: UUID


class AdminClientPersonCreateRequest(BaseModel):
    """Create a client-scoped Person without creating a login account."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    phone: str | None = Field(default=None, min_length=8, max_length=32)
    relationship: OrganizationPersonRelationship = OrganizationPersonRelationship.EMPLOYEE
    role_id: UUID | None = None
    department: str | None = Field(default=None, max_length=255)
    division: str | None = Field(default=None, max_length=255)
    joining_date: date | None = None

    @model_validator(mode="after")
    def validate_joining_date(self) -> "AdminClientPersonCreateRequest":
        if self.relationship == OrganizationPersonRelationship.FUTURE_EMPLOYEE:
            if self.joining_date is None:
                raise ValueError("joining_date is required for a future employee")
            if self.joining_date <= datetime.now(tz=UTC).date():
                raise ValueError("joining_date must be in the future for a future employee")
        return self


class AdminClientPersonResponse(BaseModel):
    organization_id: UUID
    person_id: UUID
    linked_candidate_id: UUID | None = None
    full_name: str
    email_masked: str
    relationship: OrganizationPersonRelationship
    role_id: UUID | None = None
    department: str | None = None
    division: str | None = None
    joining_date: date | None = None
    invitation_status: str
    created_at: datetime


class AdminClientPersonActivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: UUID


class AdminCandidateResponse(BaseModel):
    candidate_id: UUID
    full_name: str | None
    email_masked: str
    phone_masked: str | None = None
    claim_status: CandidateClaimStatus
    password_configured: bool
    email_verified: bool
    phone_verified: bool
    activation_expires_at: datetime | None = None
    activation_last_sent_at: datetime | None = None
    created_at: datetime


class CandidateActivationResponse(BaseModel):
    candidate_id: UUID
    claim_status: CandidateClaimStatus
    email_masked: str
    expires_at: datetime
    last_sent_at: datetime
    resend_available_at: datetime
    delivery_state: Literal["queued", "failed"]


class AdminCandidateInvitationResponse(BaseModel):
    invitation_id: UUID
    candidate_id: UUID
    candidate_name: str | None
    email_masked: str
    organization_id: UUID | None = None
    organization_name: str | None = None
    person_id: UUID | None = None
    status: Literal["pending", "expired", "revoked", "delivery_failed"]
    sent_at: datetime
    expires_at: datetime


class CandidateActivationValidationResponse(BaseModel):
    candidate_id: UUID
    claim_status: CandidateClaimStatus
    full_name: str | None
    email_masked: str
    expires_at: datetime
    password_required: bool = True
    email_verification_via_activation: bool = True


class CandidateActivationTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=32, max_length=512, repr=False)


class CandidateClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=32, max_length=512, repr=False)
    password: str = Field(min_length=12, max_length=128, repr=False)
    confirm_password: str = Field(min_length=12, max_length=128, repr=False)

    @field_validator("password", "confirm_password", mode="before")
    @classmethod
    def normalize_password(cls, value: Any) -> Any:
        # Login and the existing Candidate password flows strip outer whitespace.
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def passwords_match(self) -> "CandidateClaimRequest":
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self


class CandidateClaimResponse(BaseModel):
    candidate_id: UUID
    claim_status: Literal[CandidateClaimStatus.CLAIMED]
    claimed_at: datetime
    email_verified: bool
    phone_verified: bool
    next_action: Literal["sign_in"] = "sign_in"


class AdminProfileMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, min_length=8, max_length=32)
    current_role: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=255)
    years_of_experience: int | None = Field(default=None, ge=0, le=80)
    location: str | None = Field(default=None, max_length=255)
    location_city: str | None = Field(default=None, max_length=128)
    location_region: str | None = Field(default=None, max_length=128)
    location_country: str | None = Field(default=None, min_length=2, max_length=2)
    headline: str | None = Field(default=None, max_length=255)
    bio: str | None = Field(default=None, max_length=500)
    source: Literal[
        ProfileProvenanceSource.ADMIN_ENTERED,
        ProfileProvenanceSource.CV_EXTRACTED,
    ] = ProfileProvenanceSource.ADMIN_ENTERED

    @model_validator(mode="after")
    def at_least_one_field(self) -> "AdminProfileMutationRequest":
        values = self.model_dump(exclude={"source"}, exclude_unset=True)
        if not values:
            raise ValueError("At least one profile field is required")
        return self


class AdminProfileMutationResponse(BaseModel):
    candidate_id: UUID
    claim_status: CandidateClaimStatus
    updated_fields: list[str]
    provenance_source: ProfileProvenanceSource
    candidate_confirmation_required: bool


CareerClaimType = Literal[
    "employment",
    "education",
    "internship",
    "freelance",
    "certification",
    "portfolio",
    "project",
    "skill",
    "gig_platform",
]


class AdminCareerMutationRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_extra=lambda schema: payload_contract(schema)
    )

    claim_type: CareerClaimType
    payload: dict[str, Any]
    source: Literal[
        ProfileProvenanceSource.ADMIN_ENTERED,
        ProfileProvenanceSource.CV_EXTRACTED,
    ] = ProfileProvenanceSource.ADMIN_ENTERED

    @model_validator(mode="after")
    def validate_canonical_payload(self):
        self.payload = validate_payload(
            self.claim_type, self.payload, update=isinstance(self, AdminCareerUpdateRequest)
        )
        return self


class AdminCareerUpdateRequest(AdminCareerMutationRequest):
    model_config = ConfigDict(
        extra="forbid", json_schema_extra=lambda schema: payload_contract(schema, update=True)
    )


class AdminCareerMutationResponse(BaseModel):
    candidate_id: UUID
    claim_type: CareerClaimType
    record_id: UUID
    updated_fields: list[str]
    provenance_source: ProfileProvenanceSource
    verification_status: str


class AdminCareerRecordResponse(BaseModel):
    candidate_id: UUID
    claim_type: CareerClaimType
    record: (
        dict[str, Any]
        | PortfolioItemResponse
        | ProjectResponse
        | SkillResponse
        | GigPlatformResponse
    )


class AdminCareerDeleteResponse(BaseModel):
    candidate_id: UUID
    claim_type: CareerClaimType
    record_id: UUID
    deleted: Literal[True] = True


class AdminCareerDocumentUploadIntentRequest(BaseModel):
    claim_type: Literal["employment", "education"]
    career_record_id: UUID
    document_type: str = Field(min_length=1, max_length=48)
    evidence_role: Literal["primary", "supporting"] | None = None
    original_filename: str = Field(min_length=1, max_length=512)
    content_type: str = Field(min_length=3, max_length=255)
    byte_size: int = Field(gt=0, le=500_000_000)

    @model_validator(mode="after")
    def validate_document_contract(self) -> AdminCareerDocumentUploadIntentRequest:
        from app.education.enums import EducationDocumentType
        from app.employment.enums import EmploymentDocumentType

        enum_type = (
            EmploymentDocumentType if self.claim_type == "employment" else EducationDocumentType
        )
        try:
            enum_type(self.document_type)
        except ValueError as exc:
            raise ValueError(f"Unsupported {self.claim_type} document type") from exc
        if self.claim_type == "employment" and self.evidence_role is None:
            raise ValueError("evidence_role is required for employment documents")
        if self.claim_type == "education" and self.evidence_role is not None:
            raise ValueError("evidence_role is only valid for employment documents")
        return self


class AdminCareerDocumentCompleteUploadRequest(BaseModel):
    claim_type: Literal["employment", "education"]
    career_record_id: UUID
    checksum_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class AdminCareerDocumentResponse(BaseModel):
    id: UUID
    claim_type: Literal["employment", "education"]
    career_record_id: UUID
    document_type: str
    original_filename: str
    content_type: str
    byte_size: int
    verification_status: str
    evidence_role: Literal["primary", "supporting"] | None = None
    created_at: datetime
    updated_at: datetime


class CandidateProvenanceConfirmationItem(BaseModel):
    record_type: str = Field(min_length=1, max_length=32)
    record_id: UUID
    field_name: str = Field(min_length=1, max_length=128)


class CandidateProvenanceConfirmationRequest(BaseModel):
    items: list[CandidateProvenanceConfirmationItem] = Field(min_length=1, max_length=100)


class CandidateProvenanceConfirmationResponse(BaseModel):
    confirmed_count: int
    confirmed_at: datetime


class AdminOrganizationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=255)
    organization_type: OrganizationType
    website: str | None = Field(default=None, max_length=512)
    industry: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    work_email: EmailStr | None = None
    domain: str | None = Field(default=None, max_length=255)
    organization_size: str | None = Field(default=None, max_length=64)
    idempotency_key: UUID

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower().removeprefix("@")
        return normalized or None


class AdminOrganizationCreateResponse(BaseModel):
    organization_public_id: UUID
    name: str
    organization_type: OrganizationType
    lifecycle_state: Literal["awaiting_first_hr_claim"] = "awaiting_first_hr_claim"
    verification_state: str
    setup_completed: bool = False
    owner_membership_present: bool = False
    created_at: datetime


class AdminFirstHRInvitationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    role: Literal[OrganizationRole.OWNER] = OrganizationRole.OWNER


class AdminFirstHRInvitationResponse(BaseModel):
    invitation_public_id: UUID
    organization_public_id: UUID
    invitee_email_masked: str
    role: Literal[OrganizationRole.OWNER]
    status: str
    expires_at: datetime
    last_sent_at: datetime
    acceptance_path: Literal["/team-invitations/accept?token={opaque_token}"] = (
        "/team-invitations/accept?token={opaque_token}"
    )


class AdminFirstHRInvitationStatus(BaseModel):
    invitation_public_id: UUID
    invitee_email_masked: str
    status: str
    effective_status: str
    expires_at: datetime | None
    last_sent_at: datetime | None
    delivery_failed_at: datetime | None


class AdminOrganizationProvisioningStatus(BaseModel):
    organization_public_id: UUID
    member_present: bool
    owner_membership_present: bool
    first_hr_invitation: AdminFirstHRInvitationStatus | None


class CourtCheckWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status: CourtCheckStatus = CourtCheckStatus.PENDING
    searched_at: datetime | None = None
    jurisdiction: str = Field(min_length=1, max_length=255)
    coverage: str = Field(min_length=1, max_length=1000)
    search_period: str | None = Field(default=None, max_length=255)
    source: str = Field(min_length=1, max_length=512)
    finding: str | None = Field(default=None, max_length=1000)
    remarks: str | None = Field(default=None, max_length=4000)
    limitations: str = Field(min_length=1, max_length=2000)
    evidence_document_ids: list[UUID] = Field(default_factory=list, max_length=20)
    idempotency_key: UUID

    @model_validator(mode="after")
    def validate_result_fields(self) -> "CourtCheckWriteRequest":
        if self.status != CourtCheckStatus.PENDING and self.searched_at is None:
            raise ValueError("searched_at is required for a result")
        finding_required = {
            CourtCheckStatus.MATCH_FOUND,
            CourtCheckStatus.REVIEW_REQUIRED,
        }
        if self.status in finding_required and not self.finding:
            raise ValueError("finding is required for match or review-required results")
        return self


class CourtCheckUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status: CourtCheckStatus | None = None
    searched_at: datetime | None = None
    jurisdiction: str | None = Field(default=None, min_length=1, max_length=255)
    coverage: str | None = Field(default=None, min_length=1, max_length=1000)
    search_period: str | None = Field(default=None, max_length=255)
    source: str | None = Field(default=None, min_length=1, max_length=512)
    finding: str | None = Field(default=None, max_length=1000)
    remarks: str | None = Field(default=None, max_length=4000)
    limitations: str | None = Field(default=None, min_length=1, max_length=2000)
    evidence_document_ids: list[UUID] | None = Field(default=None, max_length=20)


class CourtCheckResponse(BaseModel):
    public_id: UUID
    organization_public_id: UUID
    person_public_id: UUID
    status: CourtCheckStatus
    searched_at: datetime | None
    jurisdiction: str
    coverage: str
    search_period: str | None
    source: str
    finding: str | None
    remarks: str | None
    limitations: str
    reviewer_user_id: UUID | None
    evidence_document_ids: list[UUID]
    finalized_at: datetime | None
    created_at: datetime
    updated_at: datetime
    semantic_notice: str = (
        "A no-match result is limited to the stated court-record scope and is not police "
        "verification or criminal clearance."
    )


class InPersonVerificationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    verification_type: InPersonVerificationType
    performed_at: datetime
    person_met: str | None = Field(default=None, max_length=255)
    relationship: str | None = Field(default=None, max_length=255)
    result: InPersonVerificationResult
    notes: str | None = Field(default=None, max_length=4000)
    evidence_document_ids: list[UUID] = Field(default_factory=list, max_length=20)
    idempotency_key: UUID


class InPersonVerificationResponse(BaseModel):
    public_id: UUID
    organization_public_id: UUID
    person_public_id: UUID
    verification_type: InPersonVerificationType
    method: Literal["in_person"] = "in_person"
    performed_at: datetime
    performed_by_user_id: UUID
    person_met: str | None
    relationship: str | None
    result: InPersonVerificationResult
    notes: str | None
    evidence_document_ids: list[UUID]
    changes_canonical_verification_status: Literal[False] = False
    permanent_address_check_credit: Literal[0] = 0
    created_at: datetime
