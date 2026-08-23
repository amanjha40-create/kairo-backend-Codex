"""Admin settings and administration DTOs."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.permissions import ADMIN_PORTAL_ROLES
from app.schemas.pagination import ListQueryParams


def _normalize_role(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("value cannot be empty")
    return normalized


class AdminSettingsSessionResponse(BaseModel):
    id: UUID
    created_at: datetime
    expires_at: datetime
    last_active_at: datetime
    current: bool = False
    status: str
    revoked_at: datetime | None = None


class AdminSettingsMeResponse(BaseModel):
    id: UUID
    full_name: str | None
    email: EmailStr
    role_key: str
    role_label: str
    account_status: str
    permissions: list[str]
    email_verified: bool
    joined_at: datetime
    last_sign_in_at: datetime | None = None
    last_activity_at: datetime | None = None


class AdminSettingsMeUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    full_name: str = Field(min_length=1, max_length=255)


class AdminSettingsNotificationCategoryResponse(BaseModel):
    key: str
    label: str
    description: str
    enabled: bool
    required: bool = False
    event_types: list[str]


class AdminSettingsNotificationPreferencesResponse(BaseModel):
    categories: list[AdminSettingsNotificationCategoryResponse]


class AdminSettingsNotificationCategoryUpdate(BaseModel):
    key: str = Field(min_length=1, max_length=128)
    enabled: bool

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        return _normalize_role(value)


class AdminSettingsNotificationPreferencesUpdateRequest(BaseModel):
    categories: list[AdminSettingsNotificationCategoryUpdate]


class AdminAdministratorActionCapabilities(BaseModel):
    can_change_role: bool
    can_deactivate: bool
    can_restore: bool


class AdminAdministratorListParams(ListQueryParams):
    role: str | None = Field(default=None, description="Sanctioned Admin role filter.")

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = _normalize_role(value)
        if normalized not in ADMIN_PORTAL_ROLES:
            raise ValueError("role must be a sanctioned Admin role")
        return normalized

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = _normalize_role(value)
        if normalized not in {"active", "suspended"}:
            raise ValueError("status must be 'active' or 'suspended'")
        return normalized


class AdminAccessAuditEventResponse(BaseModel):
    id: UUID
    actor_user_id: UUID | None = None
    actor_display_name: str | None = None
    actor_role: str | None = None
    subject_user_id: UUID | None = None
    subject_email: str | None = None
    action: str
    summary: str
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


class AdminAdministratorListItemResponse(BaseModel):
    id: UUID
    full_name: str | None = None
    email: EmailStr
    role_key: str
    role_label: str
    account_status: str
    email_verified: bool
    joined_at: datetime
    last_sign_in_at: datetime | None = None
    last_activity_at: datetime | None = None


class AdminAdministratorDetailResponse(AdminAdministratorListItemResponse):
    permissions: list[str]
    sessions: list[AdminSettingsSessionResponse]
    access_history: list[AdminAccessAuditEventResponse]
    capabilities: AdminAdministratorActionCapabilities
    is_current_actor: bool = False


class AdminRoleResponse(BaseModel):
    key: str
    label: str
    description: str
    permissions: list[str]
    assignable: bool = True


class AdminAdministratorRoleUpdateRequest(BaseModel):
    role_key: str = Field(min_length=1, max_length=32)

    @field_validator("role_key")
    @classmethod
    def validate_role_key(cls, value: str) -> str:
        return _normalize_role(value)


class AdminAdministratorDeactivateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str = Field(min_length=1, max_length=512)


class AdminAdministratorRestoreRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str | None = Field(default=None, max_length=512)


class AdminAccessInvitationResponse(BaseModel):
    id: UUID
    email: EmailStr
    role_key: str
    role_label: str
    status: str
    invited_by_display_name: str | None = None
    accepted_by_display_name: str | None = None
    created_at: datetime
    expires_at: datetime
    sent_at: datetime | None = None
    accepted_at: datetime | None = None
    revoked_at: datetime | None = None
    resend_count: int


class AdminAccessInvitationCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    role_key: str = Field(min_length=1, max_length=32)

    @field_validator("role_key")
    @classmethod
    def validate_role_key(cls, value: str) -> str:
        return _normalize_role(value)


class AdminInvitationAcceptRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    token: str = Field(min_length=32)
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=255)
