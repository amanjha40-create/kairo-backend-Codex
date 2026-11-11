"""Admin Client operations contracts."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.pagination import ListQueryParams, Page


class AdminOrganizationListParams(ListQueryParams):
    organization_type: str | None = None


class AdminOrganizationVerificationListParams(ListQueryParams):
    verification_type: str | None = None


class AdminOrganizationListItem(BaseModel):
    public_id: UUID
    name: str
    domain: str | None = None
    organization_type: str
    registry_record_public_id: UUID | None = None
    registry_record_name: str | None = None
    account_status: str
    verification_state: str
    is_workspace_customer: bool
    people_count: int = 0
    request_count: int = 0
    verified_count: int = 0
    pending_count: int = 0
    in_progress_count: int = 0
    needs_attention_count: int = 0
    team_size: int = 0
    updated_at: datetime


class AdminOrganizationDetailResponse(BaseModel):
    public_id: UUID
    name: str
    domain: str | None = None
    website: str | None = None
    organization_type: str
    industry: str | None = None
    location: str | None = None
    organization_size: str | None = None
    account_status: str
    verification_state: str
    onboarding_status: str
    is_workspace_customer: bool
    primary_owner_name: str | None = None
    primary_owner_email_masked: str | None = None
    team_size: int = 0
    people_count: int = 0
    registry_record_public_id: UUID | None = None
    registry_record_name: str | None = None
    registry_record_organization_type: str | None = None
    registry_record_primary_domain: str | None = None
    created_at: datetime
    updated_at: datetime
    last_activity_at: datetime | None = None


class AdminOrganizationCompanyRecordConnectRequest(BaseModel):
    registry_record_public_id: UUID
    idempotency_key: UUID


class AdminOrganizationCompanyRecordCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    idempotency_key: UUID
    legal_name: str = Field(min_length=1, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    organization_type: str = Field(min_length=1, max_length=64)
    country: str = Field(min_length=2, max_length=2)
    state_province: str | None = Field(default=None, max_length=128)
    website: str | None = Field(default=None, max_length=2048)
    primary_domain: str | None = Field(default=None, max_length=255)

    @field_validator("organization_type")
    @classmethod
    def normalize_organization_type(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("country")
    @classmethod
    def normalize_country(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("primary_domain")
    @classmethod
    def normalize_primary_domain(cls, value: str | None) -> str | None:
        return value.strip().lower() if value else None


class AdminOrganizationCompanyRecordResponse(BaseModel):
    organization_public_id: UUID
    registry_record_public_id: UUID
    registry_record_name: str
    registry_record_organization_type: str
    registry_record_primary_domain: str | None = None
    lifecycle_status: str
    trust_status: str
    created: bool
    already_connected: bool


class AdminOrganizationOverviewResponse(BaseModel):
    people_count: int = 0
    verification_total: int = 0
    verified_count: int = 0
    pending_count: int = 0
    in_progress_count: int = 0
    needs_attention_count: int = 0
    cancelled_count: int = 0
    withdrawn_count: int = 0
    completion_rate: float | None = None
    completion_rate_numerator: int = 0
    completion_rate_denominator: int = 0
    status_counts: dict[str, int] = Field(default_factory=dict)
    type_counts: dict[str, int] = Field(default_factory=dict)


class AdminOrganizationPersonItem(BaseModel):
    public_id: UUID
    linked_user_public_id: UUID | None = None
    display_name: str
    email_masked: str | None = None
    relationship: str
    lifecycle_status: str
    invitation_status: str
    verification_request_count: int = 0
    verified_count: int = 0
    pending_count: int = 0
    last_activity_at: datetime | None = None


class AdminOrganizationVerificationItem(BaseModel):
    public_id: UUID
    organization_person_public_id: UUID | None = None
    candidate_name: str
    candidate_email_masked: str
    request_type: str
    requested_by: str | None = None
    created_at: datetime
    status: str
    completed_at: datetime | None = None
    updated_at: datetime


class AdminOrganizationTeamItem(BaseModel):
    public_id: UUID
    user_public_id: UUID
    display_name: str
    email_masked: str
    role: str
    status: str
    joined_at: datetime
    last_activity_at: datetime | None = None


class AdminOrganizationActivityItem(BaseModel):
    public_id: UUID
    occurred_at: datetime
    event_type: str
    source: str
    actor_name: str | None = None
    actor_role: str | None = None
    actor_email_masked: str | None = None
    organization_name: str
    on_behalf_of_organization_name: str | None = None
    subject_public_id: str | None = None
    previous_status: str | None = None
    new_status: str | None = None


class AdminOrganizationPage(Page[AdminOrganizationListItem]):
    pass


class AdminOrganizationPeoplePage(Page[AdminOrganizationPersonItem]):
    pass


class AdminOrganizationVerificationPage(Page[AdminOrganizationVerificationItem]):
    pass


class AdminOrganizationTeamPage(Page[AdminOrganizationTeamItem]):
    pass


class AdminOrganizationActivityPage(Page[AdminOrganizationActivityItem]):
    pass
