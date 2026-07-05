"""Gig platform Pydantic schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class GigPlatformCreateRequest(BaseModel):
    platform_name: str
    partner_role: str
    started_at: date
    ended_at: date | None = None
    is_active: bool = True
    partner_id: str | None = None
    rating: Decimal | None = None


class GigPlatformUpdateRequest(BaseModel):
    platform_name: str | None = None
    partner_role: str | None = None
    started_at: date | None = None
    ended_at: date | None = None
    is_active: bool | None = None
    partner_id: str | None = None
    rating: Decimal | None = None


class GigPlatformResponse(BaseModel):
    id: UUID
    user_id: UUID
    platform_name: str
    partner_role: str
    started_at: date
    ended_at: date | None
    is_active: bool
    partner_id: str | None
    rating: Decimal | None
    verification_status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
