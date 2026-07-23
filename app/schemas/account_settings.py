"""Authenticated account and settings DTOs."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.notification import NotificationPreferenceResponse, NotificationPreferenceUpsertRequest
from app.schemas.user import UserPublic


class TrustScoreConsentSummary(BaseModel):
    status: str
    version: str | None = None
    consented_at: datetime | None = None


class AccountSettingsResponse(BaseModel):
    profile: UserPublic
    trust_score_consent: TrustScoreConsentSummary
    notification_preferences: list[NotificationPreferenceResponse]
    app_version: str
    api_version: str
    trust_score_version: str


class AccountSettingsUpdate(BaseModel):
    notification_preferences: list[NotificationPreferenceUpsertRequest] | None = None
    withdraw_trust_score_consent: bool = False


class AccountSessionResponse(BaseModel):
    id: UUID
    created_at: datetime
    expires_at: datetime
    last_active_at: datetime
    current: bool = False
