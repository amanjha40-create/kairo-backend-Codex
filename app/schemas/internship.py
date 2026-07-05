"""Internship Pydantic schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class InternshipCreateRequest(BaseModel):
    company_name: str
    role: str
    description: str | None = None
    start_date: date
    end_date: date | None = None
    is_ongoing: bool = False
    is_paid: bool = False
    stipend_amount: Decimal | None = None
    stipend_currency: str = "INR"


class InternshipUpdateRequest(BaseModel):
    company_name: str | None = None
    role: str | None = None
    description: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_ongoing: bool | None = None
    is_paid: bool | None = None
    stipend_amount: Decimal | None = None
    stipend_currency: str | None = None


class InternshipResponse(BaseModel):
    id: UUID
    user_id: UUID
    company_name: str
    role: str
    description: str | None
    start_date: date
    end_date: date | None
    is_ongoing: bool
    is_paid: bool
    stipend_amount: Decimal | None
    stipend_currency: str
    verification_status: str
    verifier_remarks: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
