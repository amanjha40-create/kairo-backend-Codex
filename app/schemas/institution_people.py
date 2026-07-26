"""Backend-owned Institution People and Alumni response contracts."""

from __future__ import annotations

from datetime import date as DateType
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.institution_people.enums import (
    InstitutionCredentialStatus,
    InstitutionPersonLifecycleStatus,
    InstitutionProfessionalField,
    InstitutionVerificationStatus,
)
from app.schemas.pagination import PageParams


class InstitutionPeopleListQuery(PageParams):
    search: str | None = None
    lifecycle_status: InstitutionPersonLifecycleStatus | None = None
    programme: str | None = None
    department: str | None = None
    graduation_period: str | None = None
    student_id: str | None = None
    verification_status: InstitutionVerificationStatus | None = None


class InstitutionPeriod(BaseModel):
    date: DateType | None = None
    period: str | None = None


class InstitutionProfessionalFieldValue(BaseModel):
    field: InstitutionProfessionalField
    value: str
    consented_at: datetime
    expires_at: datetime | None = None


class InstitutionPersonListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: UUID
    display_name: str
    student_id_masked: str | None = None
    lifecycle_status: InstitutionPersonLifecycleStatus
    degree: str | None = None
    programme: str | None = None
    department: str | None = None
    admission: InstitutionPeriod = Field(default_factory=InstitutionPeriod)
    graduation: InstitutionPeriod = Field(default_factory=InstitutionPeriod)
    verification_status: InstitutionVerificationStatus
    active_verification_count: int = 0
    professional_information: list[InstitutionProfessionalFieldValue] = Field(default_factory=list)


class InstitutionPeopleListResponse(BaseModel):
    items: list[InstitutionPersonListItem]
    total: int
    page: int
    page_size: int
    total_pages: int
    offset: int
    limit: int


class InstitutionVerificationEvent(BaseModel):
    public_id: UUID
    request_public_id: UUID
    event_type: str
    event_source: str
    previous_status: str | None = None
    new_status: str | None = None
    created_at: datetime


class InstitutionCredentialEventResponse(BaseModel):
    public_id: UUID
    event_type: str
    previous_status: InstitutionCredentialStatus | None = None
    new_status: InstitutionCredentialStatus | None = None
    created_at: datetime


class InstitutionCredentialResponse(BaseModel):
    public_id: UUID
    credential_type: str
    title: str
    degree: str | None = None
    programme: str | None = None
    department: str | None = None
    issued: InstitutionPeriod = Field(default_factory=InstitutionPeriod)
    credential_number: str | None = None
    status: InstitutionCredentialStatus
    version: int
    events: list[InstitutionCredentialEventResponse] = Field(default_factory=list)


class InstitutionPersonDetailResponse(InstitutionPersonListItem):
    student_id: str | None = None
    consented_professional_fields: list[InstitutionProfessionalField] = Field(default_factory=list)
    verification_history: list[InstitutionVerificationEvent] = Field(default_factory=list)
    credentials: list[InstitutionCredentialResponse] = Field(default_factory=list)
    lifecycle_events: list[dict[str, object]] = Field(default_factory=list)
