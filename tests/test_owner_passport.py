"""Route-contract tests for the owner-facing Trust Passport endpoint."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_passport_engine_service
from app.main import app
from app.schemas.passport_engine import (
    OwnerPassportResponse,
    PassportMetadata,
    PassportSectionStatusSummary,
    PassportSharingSummary,
    PassportVerificationSummary,
)
from app.schemas.public_passport import (
    PublicPassportCertification,
    PublicPassportDocument,
    PublicPassportEducation,
    PublicPassportEmployment,
    PublicPassportFreelance,
    PublicPassportGigPlatform,
    PublicPassportInternship,
    PublicPassportPortfolioItem,
    PublicPassportUserDocument,
    PublicPassportVault,
)
from app.schemas.trust_score import TrustScoreComponentBreakdown, TrustScoreResponse
from app.schemas.user import UserPublic


class FakePassportEngineService:
    async def get_owner_passport(self, user_id) -> OwnerPassportResponse:  # noqa: ANN001
        now = datetime.now(tz=UTC)
        return OwnerPassportResponse(
            profile=UserPublic(
                id=user_id,
                email="owner@example.com",
                full_name="Owner User",
                profile_slug="owner-user",
                phone=None,
                location="Bengaluru",
                headline="Engineer",
                bio=None,
                date_of_birth=None,
                avatar_url=None,
                role="user",
                is_active=True,
                employment_onboarding_completed_at=now,
                created_at=now,
            ),
            trust_score=TrustScoreResponse(
                overall=80,
                breakdown=TrustScoreComponentBreakdown(
                    identity=100,
                    employment=75,
                    education=70,
                    documents=75,
                ),
                week_change=0,
            ),
            vault=PublicPassportVault(
                employments=[
                    PublicPassportEmployment(
                        id=uuid4(),
                        employer_legal_name="Example Co",
                        job_title="Backend Engineer",
                        start_date=now.date(),
                        end_date=None,
                        verification_status="approved",
                        verification_method="document",
                        documents=[
                            PublicPassportDocument(
                                id=uuid4(),
                                document_type="offer_letter",
                                original_filename="offer.pdf",
                                byte_size=123,
                                verification_status="verified",
                            )
                        ],
                    )
                ],
                educations=[
                    PublicPassportEducation(
                        id=uuid4(),
                        institution_name="Example University",
                        degree="B.Tech",
                        field_of_study="CS",
                        education_level="bachelors",
                        grade=None,
                        start_date=now.date(),
                        end_date=None,
                        is_currently_studying=False,
                        verification_status="verified",
                    )
                ],
                internships=[
                    PublicPassportInternship(
                        id=uuid4(),
                        company_name="Example Intern Co",
                        role="Intern",
                        description=None,
                        start_date=now.date(),
                        end_date=None,
                        is_ongoing=True,
                        verification_status="verified",
                    )
                ],
                freelance=[
                    PublicPassportFreelance(
                        id=uuid4(),
                        client_name="Client",
                        project_title="Project",
                        description=None,
                        start_date=now.date(),
                        end_date=None,
                        is_ongoing=True,
                        verification_status="pending",
                    )
                ],
                gig_platforms=[
                    PublicPassportGigPlatform(
                        id=uuid4(),
                        platform_name="Platform",
                        partner_role="Driver",
                        started_at=now.date(),
                        ended_at=None,
                        is_active=True,
                        rating=4.8,
                        verification_status="verified",
                    )
                ],
                portfolio=[
                    PublicPassportPortfolioItem(
                        id=uuid4(),
                        title="Platform Work",
                        description=None,
                        url="https://example.com",
                        tags=["backend"],
                        verification_status="pending",
                    )
                ],
                certifications=[
                    PublicPassportCertification(
                        id=uuid4(),
                        title="AWS",
                        issuing_organization="AWS",
                        issued_date=now.date(),
                        expiry_date=None,
                        does_not_expire=False,
                        credential_id=None,
                        credential_url=None,
                        verification_status="verified",
                    )
                ],
                user_documents=[
                    PublicPassportUserDocument(
                        id=uuid4(),
                        document_type="pan",
                        original_filename="pan.pdf",
                        byte_size=456,
                        verification_status="verified",
                        expires_at=None,
                    )
                ],
            ),
            passport_metadata=PassportMetadata(
                owner_user_id=user_id,
                profile_slug="owner-user",
                is_email_verified=True,
                is_onboarding_complete=True,
                created_at=now,
                updated_at=now,
                employment_onboarding_completed_at=now,
            ),
            sharing_summary=PassportSharingSummary(
                total_links=2,
                active_links=1,
                revoked_links=1,
                expired_links=0,
                total_views=5,
                unique_views=3,
                latest_share_created_at=now,
                last_viewed_at=now,
            ),
            verification_summary=PassportVerificationSummary(
                overall=PassportSectionStatusSummary(total=8, statuses={"verified": 5, "pending": 3}),
                employments=PassportSectionStatusSummary(total=1, statuses={"approved": 1}),
                educations=PassportSectionStatusSummary(total=1, statuses={"verified": 1}),
                internships=PassportSectionStatusSummary(total=1, statuses={"verified": 1}),
                freelance=PassportSectionStatusSummary(total=1, statuses={"pending": 1}),
                gig_platforms=PassportSectionStatusSummary(total=1, statuses={"verified": 1}),
                portfolio=PassportSectionStatusSummary(total=1, statuses={"pending": 1}),
                certifications=PassportSectionStatusSummary(total=1, statuses={"verified": 1}),
                user_documents=PassportSectionStatusSummary(total=1, statuses={"verified": 1}),
            ),
        )


async def _override_current_user() -> CurrentUser:
    return CurrentUser(id=uuid4(), email="owner@example.com", role="user")


@pytest.mark.asyncio
async def test_get_my_passport_returns_canonical_owner_payload() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_passport_engine_service] = lambda: FakePassportEngineService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/passport/me")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["profile"]["full_name"] == "Owner User"
    assert body["trust_score"]["overall"] == 80
    assert body["sharing_summary"]["total_links"] == 2
    assert body["verification_summary"]["overall"]["total"] == 8
