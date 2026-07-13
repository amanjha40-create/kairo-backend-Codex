"""Route-contract test for the backend-owned dashboard endpoint."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_passport_engine_service
from app.main import app
from app.schemas.passport_engine import (
    DashboardActivePassportShares,
    DashboardActivityItem,
    DashboardResponse,
    DashboardShareAnalyticsItem,
    DashboardShareSummaryItem,
    DashboardVaultSummary,
    OnboardingStatusResponse,
    PassportSectionStatusSummary,
    PassportVerificationSummary,
)
from app.schemas.trust_score import TrustScoreComponentBreakdown, TrustScoreResponse


class FakePassportEngineService:
    async def get_dashboard(self, user_id) -> DashboardResponse:  # noqa: ANN001
        now = datetime.now(tz=UTC)
        return DashboardResponse(
            profile_completion=OnboardingStatusResponse(
                current_step="complete_profile",
                email_verified=True,
                phone_verified=True,
                passport_ready=False,
                completed_steps=["verify_email", "complete_profile"],
                missing_requirements=["add_employment_or_work_history"],
                next_recommended_step="add_employment_or_work_history",
                completion_percentage=40,
                is_onboarding_complete=False,
            ),
            trust_score=TrustScoreResponse(
                overall=72,
                breakdown=TrustScoreComponentBreakdown(
                    identity=100,
                    employment=60,
                    education=50,
                    documents=75,
                ),
                week_change=0,
            ),
            verification_summary=PassportVerificationSummary(
                overall=PassportSectionStatusSummary(total=4, statuses={"verified": 2, "pending": 2}),
                employments=PassportSectionStatusSummary(total=1, statuses={"approved": 1}),
                educations=PassportSectionStatusSummary(total=1, statuses={"verified": 1}),
                internships=PassportSectionStatusSummary(total=0, statuses={}),
                freelance=PassportSectionStatusSummary(total=0, statuses={}),
                gig_platforms=PassportSectionStatusSummary(total=0, statuses={}),
                portfolio=PassportSectionStatusSummary(total=1, statuses={"pending": 1}),
                certifications=PassportSectionStatusSummary(total=0, statuses={}),
                user_documents=PassportSectionStatusSummary(total=1, statuses={"verified": 1}),
            ),
            vault_summary=DashboardVaultSummary(
                total_items=4,
                employments=1,
                educations=1,
                internships=0,
                freelance=0,
                gig_platforms=0,
                portfolio=1,
                certifications=0,
                user_documents=1,
            ),
            active_passport_shares=DashboardActivePassportShares(
                count=1,
                items=[
                    DashboardShareSummaryItem(
                        share_id=uuid4(),
                        label="Hiring manager link",
                        state="active",
                        expires_at=None,
                        last_viewed_at=now,
                        created_at=now,
                    )
                ],
            ),
            recent_share_analytics=[
                DashboardShareAnalyticsItem(
                    share_id=uuid4(),
                    label="Hiring manager link",
                    state="active",
                    total_views=3,
                    unique_views=2,
                    last_viewed_at=now,
                )
            ],
            recent_activity=[
                DashboardActivityItem(
                    occurred_at=now,
                    category="passport_share",
                    action="share_viewed",
                    title="Trust Passport share viewed",
                    detail="Hiring manager link",
                    subject_id=user_id,
                )
            ],
        )


async def _override_current_user() -> CurrentUser:
    return CurrentUser(id=uuid4(), email="owner@example.com", role="user")


@pytest.mark.asyncio
async def test_get_dashboard_returns_backend_owned_summary() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_passport_engine_service] = lambda: FakePassportEngineService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/dashboard")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["profile_completion"]["completion_percentage"] == 40
    assert body["trust_score"]["overall"] == 72
    assert body["active_passport_shares"]["count"] == 1
    assert body["recent_share_analytics"][0]["total_views"] == 3
