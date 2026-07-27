"""Admin Portal session DTOs."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr


class AdminSessionAccount(BaseModel):
    """Backend-authoritative identity and permissions for Admin Portal entry."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    name: str | None
    initials: str
    role_key: str
    permissions: list[str]
    is_active: bool


class AdminSessionResponse(BaseModel):
    account: AdminSessionAccount
