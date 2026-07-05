"""Trust score schemas for displaying user profile completeness."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TrustScoreComponentBreakdown(BaseModel):
    """Individual trust score component."""

    identity: int = Field(ge=0, le=100, description="Identity verification score (0-100)")
    employment: int = Field(ge=0, le=100, description="Employment verification score (0-100)")
    education: int = Field(ge=0, le=100, description="Education verification score (0-100)")
    documents: int = Field(ge=0, le=100, description="Document verification score (0-100)")


class TrustScoreResponse(BaseModel):
    """Overall trust score with component breakdown."""

    overall: int = Field(ge=0, le=100, description="Overall trust score (0-100)")
    breakdown: TrustScoreComponentBreakdown
    week_change: int = Field(description="Change in score over the past week")
