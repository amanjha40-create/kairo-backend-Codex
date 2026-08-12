"""Trust Registry DTOs."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.pagination import ListQueryParams, Page
from app.trust_registry.enums import (
    TrustRegistryAliasType,
    TrustRegistryCapabilityStatus,
    TrustRegistryIdentifierStatus,
    TrustRegistryLifecycleStatus,
    TrustRegistryRelationshipStatus,
    TrustRegistryRelationshipType,
    TrustRegistryResolutionMethod,
    TrustRegistryResolutionState,
    TrustRegistrySourceType,
    TrustRegistryTrustStatus,
)


def _normalize_key(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("value cannot be empty")
    return normalized


class TrustRegistryRecordCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    legal_name: str = Field(min_length=1, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    organization_type: str = Field(min_length=1, max_length=64)
    country: str = Field(min_length=2, max_length=2)
    state_province: str | None = Field(default=None, max_length=128)
    website: str | None = Field(default=None, max_length=2048)
    lifecycle_status: TrustRegistryLifecycleStatus = TrustRegistryLifecycleStatus.DRAFT
    trust_status: TrustRegistryTrustStatus = TrustRegistryTrustStatus.UNREVIEWED
    registry_confidence_score: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    trust_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("organization_type")
    @classmethod
    def validate_org_type(cls, value: str) -> str:
        return _normalize_key(value)

    @field_validator("country")
    @classmethod
    def validate_country(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 2:
            raise ValueError("country must be a 2-letter ISO code")
        return normalized


class TrustRegistryRecordUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    legal_name: str | None = Field(default=None, min_length=1, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    organization_type: str | None = Field(default=None, min_length=1, max_length=64)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    state_province: str | None = Field(default=None, max_length=128)
    website: str | None = Field(default=None, max_length=2048)
    lifecycle_status: TrustRegistryLifecycleStatus | None = None
    trust_status: TrustRegistryTrustStatus | None = None
    registry_confidence_score: Decimal | None = Field(default=None, ge=0, le=100)
    trust_metadata: dict[str, Any] | None = None


class AdminTrustRegistryListParams(ListQueryParams):
    organization_type: str | None = Field(default=None, max_length=64)
    lifecycle_status: str | None = Field(default=None, max_length=32)
    trust_status: str | None = Field(default=None, max_length=32)
    verification_state: str | None = Field(default=None, max_length=32)


class TrustRegistryCapabilityCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    capability_key: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    description: str | None = None

    @field_validator("capability_key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        return _normalize_key(value)


class TrustRegistryRecordCapabilityCreateRequest(BaseModel):
    capability_key: str = Field(min_length=1, max_length=64)
    display_name: str | None = Field(default=None, max_length=128)
    description: str | None = None
    status: TrustRegistryCapabilityStatus = TrustRegistryCapabilityStatus.ACTIVE
    source_type: TrustRegistrySourceType
    source_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("capability_key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        return _normalize_key(value)


class TrustRegistryDomainCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    domain: str = Field(min_length=1, max_length=255)
    is_primary: bool = False
    is_verified: bool = False
    source_type: TrustRegistrySourceType
    source_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value: str) -> str:
        return value.strip().lower()


class TrustRegistryAliasCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    alias_name: str = Field(min_length=1, max_length=255)
    alias_type: TrustRegistryAliasType
    source_type: TrustRegistrySourceType
    source_metadata: dict[str, Any] = Field(default_factory=dict)


class TrustRegistryIdentifierCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    identifier_type: str = Field(min_length=1, max_length=64)
    identifier_value: str = Field(min_length=1, max_length=255)
    issuing_country: str | None = Field(default=None, min_length=2, max_length=2)
    issuing_authority: str | None = Field(default=None, max_length=255)
    is_primary: bool = False
    is_verified: bool = False
    status: TrustRegistryIdentifierStatus = TrustRegistryIdentifierStatus.ACTIVE
    source_type: TrustRegistrySourceType
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("identifier_type")
    @classmethod
    def normalize_identifier_type(cls, value: str) -> str:
        return _normalize_key(value)

    @field_validator("issuing_country")
    @classmethod
    def normalize_issuing_country(cls, value: str | None) -> str | None:
        return value.strip().upper() if value is not None else None


class TrustRegistryRelationshipCreateRequest(BaseModel):
    child_registry_record_public_id: UUID
    relationship_type: TrustRegistryRelationshipType
    status: TrustRegistryRelationshipStatus = TrustRegistryRelationshipStatus.ACTIVE
    metadata: dict[str, Any] = Field(default_factory=dict)


class TrustRegistryMergeRequest(BaseModel):
    target_registry_record_public_id: UUID
    merge_reason: str | None = Field(default=None, max_length=5000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TrustRegistryResolutionRequest(BaseModel):
    registry_record_public_id: UUID
    resolution_method: TrustRegistryResolutionMethod = TrustRegistryResolutionMethod.MANUAL
    resolution_confidence: Decimal | None = Field(default=None, ge=0, le=100)
    resolution_metadata: dict[str, Any] = Field(default_factory=dict)


class TrustRegistryCreateAndResolveRequest(BaseModel):
    record: TrustRegistryRecordCreateRequest
    resolution_method: TrustRegistryResolutionMethod = TrustRegistryResolutionMethod.CREATED_NEW
    resolution_confidence: Decimal | None = Field(default=None, ge=0, le=100)
    resolution_metadata: dict[str, Any] = Field(default_factory=dict)


class TrustRegistryDeferResolutionRequest(BaseModel):
    resolution_metadata: dict[str, Any] = Field(default_factory=dict)


class TrustRegistryLookupQuery(BaseModel):
    name: str | None = None
    domain: str | None = None
    identifier_type: str | None = None
    identifier_value: str | None = None

    @model_validator(mode="after")
    def validate_lookup(self) -> "TrustRegistryLookupQuery":
        if not any((self.name, self.domain, self.identifier_type and self.identifier_value)):
            raise ValueError("Provide name, domain, or identifier_type with identifier_value")
        return self


class TrustRegistryCapabilityResponse(BaseModel):
    public_id: UUID
    capability_key: str
    display_name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class TrustRegistryRecordCapabilityResponse(BaseModel):
    public_id: UUID
    capability: TrustRegistryCapabilityResponse
    status: str
    source_type: str
    source_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class TrustRegistryDomainResponse(BaseModel):
    public_id: UUID
    domain: str
    is_primary: bool
    is_verified: bool
    source_type: str
    source_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class TrustRegistryAliasResponse(BaseModel):
    public_id: UUID
    alias_name: str
    alias_type: str
    source_type: str
    source_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class TrustRegistryIdentifierResponse(BaseModel):
    public_id: UUID
    identifier_type: str
    identifier_value: str
    issuing_country: str | None
    issuing_authority: str | None
    is_primary: bool
    is_verified: bool
    status: str
    source_type: str
    source_metadata: dict[str, Any]
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class TrustRegistryRelationshipResponse(BaseModel):
    public_id: UUID
    parent_registry_record_public_id: UUID
    child_registry_record_public_id: UUID
    relationship_type: str
    status: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class TrustRegistryMergeResponse(BaseModel):
    public_id: UUID
    source_registry_record_public_id: UUID
    target_registry_record_public_id: UUID
    merge_reason: str | None
    metadata: dict[str, Any]
    created_at: datetime


class TrustRegistryRecordResponse(BaseModel):
    public_id: UUID
    registry_code: str
    legal_name: str
    display_name: str | None
    organization_type: str
    country: str
    state_province: str | None
    website: str | None
    lifecycle_status: str
    trust_status: str
    registry_confidence_score: Decimal
    trust_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class TrustRegistryDetailResponse(TrustRegistryRecordResponse):
    domains: list[TrustRegistryDomainResponse]
    aliases: list[TrustRegistryAliasResponse]
    identifiers: list[TrustRegistryIdentifierResponse]
    capabilities: list[TrustRegistryRecordCapabilityResponse]


class TrustRegistrySearchResponse(Page[TrustRegistryRecordResponse]):
    pass


class TrustRegistryAdminContactResponse(BaseModel):
    """Privacy-safe contact projection for the Admin Registry workspace."""

    public_id: UUID
    name: str | None
    role: str | None
    email_masked: str
    state: str
    added_by: str
    added_at: datetime
    last_successful_use: datetime | None = None


class TrustRegistryAdminActivityResponse(BaseModel):
    public_id: UUID
    at: datetime
    kind: str
    actor: str
    description: str


class TrustRegistryAdminRelationshipResponse(BaseModel):
    public_id: UUID
    direction: str
    relationship_type: str
    status: str
    related_registry_record_public_id: UUID
    related_registry_record_name: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class TrustRegistryAdminVerificationLinkResponse(BaseModel):
    public_id: UUID
    request_type: str
    status: str
    organization_public_id: UUID | None = None
    organization_name: str | None = None
    linked_record_public_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class TrustRegistryAdminOrganizationLinkResponse(BaseModel):
    public_id: UUID
    name: str
    organization_type: str
    verification_state: str
    registry_resolution_status: str
    verification_capabilities: list[str] = Field(default_factory=list)
    domain: str | None = None
    setup_completed_at: datetime | None = None
    suspended_at: datetime | None = None
    suspension_reason: str | None = None
    member_count: int = 0
    created_at: datetime
    updated_at: datetime


class TrustRegistryAdminMergeHistoryResponse(BaseModel):
    public_id: UUID
    direction: str
    other_registry_record_public_id: UUID
    other_registry_record_name: str
    merged_by_user_id: UUID | None = None
    merge_reason: str | None = None
    metadata: dict[str, Any]
    created_at: datetime


class TrustRegistryAdminRecordResponse(TrustRegistryRecordResponse):
    """Admin-facing registry summary; the canonical record remains the source of truth."""

    aliases: list[str] = Field(default_factory=list)
    domain: str | None = None
    state: str
    active_case_count: int
    total_verifications: int
    aliases_count: int = 0
    identifiers_count: int = 0
    relationship_count: int = 0
    capabilities_count: int = 0
    linked_organization_count: int = 0
    possible_duplicate_ids: list[UUID] = Field(default_factory=list)
    registry_flags: list[str] = Field(default_factory=list)


class TrustRegistryAdminDetailResponse(TrustRegistryAdminRecordResponse):
    domains: list[TrustRegistryDomainResponse] = Field(default_factory=list)
    alias_items: list[TrustRegistryAliasResponse] = Field(default_factory=list)
    identifiers: list[TrustRegistryIdentifierResponse] = Field(default_factory=list)
    capabilities: list[TrustRegistryRecordCapabilityResponse] = Field(default_factory=list)
    relationships: list[TrustRegistryAdminRelationshipResponse] = Field(default_factory=list)
    linked_organizations: list[TrustRegistryAdminOrganizationLinkResponse] = Field(
        default_factory=list
    )
    verification_requests: list[TrustRegistryAdminVerificationLinkResponse] = Field(
        default_factory=list
    )
    merge_history: list[TrustRegistryAdminMergeHistoryResponse] = Field(default_factory=list)
    contacts: list[TrustRegistryAdminContactResponse] = Field(default_factory=list)
    activity: list[TrustRegistryAdminActivityResponse] = Field(default_factory=list)


class TrustRegistryAdminMetricsResponse(BaseModel):
    total: int
    employers: int = 0
    institutions: int = 0
    verified: int
    unverified: int
    duplicates: int
    unresolved_organizations: int = 0
    linked_organizations: int = 0
    contacts_approved: int
    contacts_bounced: int


class TrustRegistryLookupResponse(BaseModel):
    resolution_state: TrustRegistryResolutionState
    matches: list[TrustRegistryRecordResponse]
    match_reason: str


class TrustRegistryOrganizationResolutionResponse(BaseModel):
    organization_public_id: UUID
    registry_record_public_id: UUID | None
    resolution_state: TrustRegistryResolutionState
    resolution_method: str | None
    resolution_confidence: float | None
    resolution_metadata: dict[str, Any]


class TrustRegistryVerificationRequestResolutionResponse(BaseModel):
    verification_request_public_id: UUID
    registry_record_public_id: UUID | None
    resolution_state: TrustRegistryResolutionState
    resolution_method: str | None
    resolution_confidence: float | None
    resolution_metadata: dict[str, Any]
