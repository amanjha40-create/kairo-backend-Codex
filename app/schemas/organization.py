"""Organization engine DTOs."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.organization.enums import OrganizationRole, OrganizationType


def _normalize_capabilities(values: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        item = value.strip().lower()
        if not item:
            raise ValueError("verification_capabilities cannot contain empty values")
        if len(item) > 64:
            raise ValueError("verification_capabilities values must be 64 characters or fewer")
        if item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return normalized


class OrganizationCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=255)
    organization_type: OrganizationType
    verification_capabilities: list[str] = Field(default_factory=list, max_length=25)

    @field_validator("verification_capabilities")
    @classmethod
    def validate_capabilities(cls, value: list[str]) -> list[str]:
        return _normalize_capabilities(value)


class OrganizationResponse(BaseModel):
    public_id: UUID
    name: str
    organization_type: OrganizationType
    verification_capabilities: list[str]
    my_role: OrganizationRole
    member_count: int
    created_at: datetime
    updated_at: datetime


class OrganizationMemberCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    role: OrganizationRole = Field(default=OrganizationRole.MEMBER)

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: OrganizationRole) -> OrganizationRole:
        if value == OrganizationRole.OWNER:
            raise ValueError("owner role cannot be assigned through member creation")
        return value


class OrganizationMemberUpdateRequest(BaseModel):
    role: OrganizationRole

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: OrganizationRole) -> OrganizationRole:
        if value == OrganizationRole.OWNER:
            raise ValueError("owner role cannot be assigned through member updates")
        return value


class OrganizationMemberResponse(BaseModel):
    public_id: UUID
    organization_public_id: UUID
    role: OrganizationRole
    user_email: EmailStr
    user_full_name: str | None
    created_at: datetime
    updated_at: datetime
