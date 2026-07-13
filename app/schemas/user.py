"""User-facing DTOs."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.constants import Role


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    profile_slug: str | None = None
    phone: str | None = None
    current_role: str | None = None
    industry: str | None = None
    years_of_experience: int | None = None
    location: str | None = None
    headline: str | None = None
    bio: str | None = None
    date_of_birth: date | None = None
    avatar_url: str | None = None
    role: Role
    is_active: bool
    phone_verified_at: datetime | None = None
    employment_onboarding_completed_at: datetime | None = None
    created_at: datetime


class AvatarUploadIntentResponse(BaseModel):
    upload_url: str
    avatar_url: str
    expires_in_seconds: int


class UserUpdate(BaseModel):
    """Profile fields a user may edit. Email is intentionally excluded (login identity)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    full_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    current_role: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=255)
    years_of_experience: int | None = Field(default=None, ge=0, le=80)
    location: str | None = Field(default=None, max_length=255)
    headline: str | None = Field(default=None, max_length=255)
    bio: str | None = Field(default=None, max_length=500)
    date_of_birth: date | None = None


class UserCreateInternal(BaseModel):
    """Internal service payload — not exposed on HTTP."""

    email: EmailStr
    password_hash: str
    full_name: str | None = None
    role: Role = Field(default=Role.USER)
