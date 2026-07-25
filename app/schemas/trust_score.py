"""Versioned, explainable Trust Score contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class TrustScoreContributor(BaseModel):
    code: str
    label: str
    points: float
    detail: str


class TrustScoreDomainScore(BaseModel):
    score: float = Field(ge=0, le=100)
    verification_points: float = Field(ge=0)
    fraud_deduction: float = Field(ge=0)
    weight: float = Field(ge=0, le=1)
    positive_contributors: list[TrustScoreContributor] = Field(default_factory=list)
    negative_contributors: list[TrustScoreContributor] = Field(default_factory=list)


class TrustScoreComponentBreakdown(BaseModel):
    """Domain scores. ``documents`` is accepted for old fixtures but never emitted."""

    identity: float = Field(ge=0, le=100)
    employment: float = Field(ge=0, le=100)
    education: float = Field(ge=0, le=100)
    documents: float | None = Field(default=None, exclude=True)


class TrustScoreResponse(BaseModel):
    """Backend-owned Trust Score; the frontend must render, not calculate, it."""

    overall: int | None = Field(default=None, ge=0, le=100)
    breakdown: TrustScoreComponentBreakdown | None = None
    domain_details: dict[str, TrustScoreDomainScore] = Field(default_factory=dict)
    status: Literal["consent_required", "incomplete_verification", "calculated", "critical_manual_fraud_review"] = "calculated"
    positive_contributors: list[TrustScoreContributor] = Field(default_factory=list)
    negative_contributors: list[TrustScoreContributor] = Field(default_factory=list)
    critical_overrides: list[TrustScoreContributor] = Field(default_factory=list)
    manual_review_reason: str | None = None
    score_version: str = "v1"
    last_calculated_at: datetime | None = None
    verification_completeness_percentage: int = Field(default=0, ge=0, le=100)
    # Kept for clients released before V1; it is not part of V1 scoring.
    week_change: int = 0


class TrustScoreConsentRequest(BaseModel):
    consent_version: str = Field(min_length=1, max_length=64)
