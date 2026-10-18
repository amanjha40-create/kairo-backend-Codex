"""Privacy-safe API DTOs for Admin Operations V1.1."""

from __future__ import annotations

from datetime import datetime
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


class AdminCreateCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    phone: str | None = Field(default=None, min_length=8, max_length=32)
    headline: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
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


CareerClaimType = Literal["employment", "education", "internship", "freelance", "certification"]


class AdminCareerMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_type: CareerClaimType
    payload: dict[str, Any]
    source: Literal[
        ProfileProvenanceSource.ADMIN_ENTERED,
        ProfileProvenanceSource.CV_EXTRACTED,
    ] = ProfileProvenanceSource.ADMIN_ENTERED


class AdminCareerMutationResponse(BaseModel):
    candidate_id: UUID
    claim_type: CareerClaimType
    record_id: UUID
    updated_fields: list[str]
    provenance_source: ProfileProvenanceSource
    verification_status: str


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
