"""Freelance contract Pydantic schemas."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel


class FreelanceContractCreateRequest(BaseModel):
    client_name: str
    project_title: str
    description: str | None = None
    start_date: date
    end_date: date | None = None
    is_ongoing: bool = False


class FreelanceContractUpdateRequest(BaseModel):
    client_name: str | None = None
    project_title: str | None = None
    description: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_ongoing: bool | None = None


class FreelanceContractResponse(BaseModel):
    id: UUID
    user_id: UUID
    client_name: str
    project_title: str
    description: str | None
    start_date: date
    end_date: date | None
    is_ongoing: bool
    verification_status: str
    verifier_remarks: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
