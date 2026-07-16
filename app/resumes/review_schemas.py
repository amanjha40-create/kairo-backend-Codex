from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter, model_validator

from app.education.enums import EducationLevel
from app.resumes.review_enums import ResumeImportAction


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ReviewLocation(StrictModel):
    city: str | None = Field(default=None, max_length=128)
    region: str | None = Field(default=None, max_length=128)
    country: str | None = Field(default=None, min_length=2, max_length=128)


class DatedClaim(StrictModel):
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> "DatedClaim":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date_before_start_date")
        if self.is_current and self.end_date:
            raise ValueError("current_claim_has_end_date")
        return self


class ProfileReviewClaim(StrictModel):
    claim_type: Literal["profile"]
    full_name: str | None = Field(default=None, max_length=255)
    professional_headline: str | None = Field(default=None, max_length=255)
    summary: str | None = Field(default=None, max_length=4000)
    location: ReviewLocation | None = None
    profile_links: list[HttpUrl] = Field(default_factory=list, max_length=20)


class EmploymentReviewClaim(DatedClaim):
    claim_type: Literal["employment"]
    company_name: str | None = Field(default=None, max_length=512)
    role_title: str | None = Field(default=None, max_length=255)
    employment_type: str | None = Field(default=None, max_length=32)
    work_arrangement: Literal["onsite", "hybrid", "remote"] | None = None
    location: ReviewLocation | None = None
    description: str | None = Field(default=None, max_length=4000)


class EducationReviewClaim(DatedClaim):
    claim_type: Literal["education"]
    institution_name: str | None = Field(default=None, max_length=512)
    degree: str | None = Field(default=None, max_length=255)
    field_of_study: str | None = Field(default=None, max_length=255)
    education_level: EducationLevel | None = None
    grade: str | None = Field(default=None, max_length=64)


class InternshipReviewClaim(DatedClaim):
    claim_type: Literal["internship"]
    company_name: str | None = Field(default=None, max_length=512)
    role: str | None = Field(default=None, max_length=512)
    description: str | None = Field(default=None, max_length=4000)


class FreelanceReviewClaim(DatedClaim):
    claim_type: Literal["freelance"]
    client_name: str | None = Field(default=None, max_length=512)
    project_title: str | None = Field(default=None, max_length=512)
    description: str | None = Field(default=None, max_length=4000)


class GigReviewClaim(DatedClaim):
    claim_type: Literal["gig_platform"]
    platform_name: str | None = Field(default=None, max_length=256)
    partner_role: str | None = Field(default=None, max_length=256)
    partner_id: str | None = Field(default=None, max_length=256)


class CertificationReviewClaim(StrictModel):
    claim_type: Literal["certification"]
    title: str | None = Field(default=None, max_length=512)
    issuing_organization: str | None = Field(default=None, max_length=512)
    issued_date: date | None = None
    expiry_date: date | None = None
    credential_id: str | None = Field(default=None, max_length=256)
    credential_url: HttpUrl | None = None


class PortfolioReviewClaim(StrictModel):
    claim_type: Literal["portfolio"]
    title: str | None = Field(default=None, max_length=512)
    description: str | None = Field(default=None, max_length=4000)
    url: HttpUrl
    tags: list[str] = Field(default_factory=list, max_length=20)


class ProjectReviewClaim(StrictModel):
    claim_type: Literal["project"]
    title: str | None = Field(default=None, max_length=512)
    description: str | None = Field(default=None, max_length=4000)
    url: HttpUrl | None = None


class SkillReviewClaim(StrictModel):
    claim_type: Literal["skill"]
    name: str = Field(min_length=1, max_length=128)


ReviewClaim = Annotated[
    ProfileReviewClaim | EmploymentReviewClaim | EducationReviewClaim | InternshipReviewClaim
    | FreelanceReviewClaim | GigReviewClaim | CertificationReviewClaim | PortfolioReviewClaim
    | ProjectReviewClaim | SkillReviewClaim,
    Field(discriminator="claim_type"),
]
review_claim_adapter = TypeAdapter(ReviewClaim)


class ReviewItemUpdateRequest(StrictModel):
    expected_version: int = Field(ge=1)
    selected: bool | None = None
    import_action: ResumeImportAction | None = None
    target_record_id: UUID | None = None
    edited_payload: dict[str, Any] | None = None


class ReviewSessionUpdateRequest(StrictModel):
    expected_version: int = Field(ge=1)
    status: Literal["reviewing"] = "reviewing"


class ReviewValidateRequest(StrictModel):
    expected_version: int = Field(ge=1)


class ReviewImportRequest(StrictModel):
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=128)
    confirmed: Literal[True]


class ReviewItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    claim_type: str
    source_claim_id: str
    original_payload: dict[str, Any]
    edited_payload: dict[str, Any]
    selected: bool
    review_status: str
    duplicate_status: str
    duplicate_candidates: list[dict[str, Any]]
    conflict_warnings: list[str]
    import_action: str
    target_record_id: UUID | None
    imported_record_type: str | None
    imported_record_id: UUID | None
    source_reference: str | None
    confidence: float | None
    version: int


class ReviewSessionResponse(BaseModel):
    id: UUID
    resume_id: UUID
    parsed_result_id: UUID
    status: str
    schema_version: str
    version: int
    items: list[ReviewItemResponse]
    created_at: datetime
    updated_at: datetime


class ReviewPlanItem(BaseModel):
    item_id: UUID
    claim_type: str
    action: str
    target_model: str | None
    duplicate_status: str
    target_record_id: UUID | None
    fields_to_create: list[str]
    fields_ignored: list[str]
    blockers: list[str]
    warnings: list[str]
    verified_record_protected: bool


class ReviewPlanResponse(BaseModel):
    session_id: UUID
    ready: bool
    version: int
    items: list[ReviewPlanItem]


class ImportResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    review_item_id: UUID
    outcome: str
    record_type: str | None
    record_id: UUID | None
    sanitized_error_code: str | None
    warnings: list[str]


class ImportBatchResponse(BaseModel):
    id: UUID
    review_session_id: UUID
    status: str
    total_count: int
    imported_count: int
    linked_count: int
    skipped_count: int
    failed_count: int
    blocked_count: int
    results: list[ImportResultResponse]
    created_at: datetime
    updated_at: datetime
