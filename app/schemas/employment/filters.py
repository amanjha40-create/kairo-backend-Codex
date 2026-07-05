"""Query / filter models for employment verification list endpoints."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.employment.enums import VerificationStatus


class EmploymentListFilters(BaseModel):
    """Applicant-scoped listing filters — maps to repository `list_for_owner` parameters."""

    model_config = ConfigDict(str_strip_whitespace=True)

    statuses: list[VerificationStatus] | None = Field(
        default=None,
        description="Restrict to one or more verification states",
    )
    employer_search: str | None = Field(default=None, max_length=200, description="ILIKE match on employer name")
    submitted_after: date | None = None
    submitted_before: date | None = None


class AdminEmploymentListFilters(BaseModel):
    """Reviewer queue filters — maps to `list_admin`."""

    model_config = ConfigDict(str_strip_whitespace=True)

    statuses: list[VerificationStatus] | None = None
    employer_search: str | None = Field(default=None, max_length=200)
    created_after: date | None = None
    created_before: date | None = None
