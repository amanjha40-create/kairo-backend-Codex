"""Route-contract tests for public Trust Passport token access."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.services import get_public_passport_service
from app.exceptions import NotFoundError
from app.main import app
from app.schemas.passport_share import PassportSharePermissions
from app.schemas.public_passport import (
    PublicPassportCertification,
    PublicPassportEducation,
    PublicPassportEmployment,
    PublicPassportFreelance,
    PublicPassportGigPlatform,
    PublicPassportInternship,
    PublicPassportPortfolioItem,
    PublicPassportProfile,
    PublicPassportResponse,
    PublicPassportShareMetadata,
    PublicPassportVault,
)
from app.schemas.trust_score import TrustScoreComponentBreakdown, TrustScoreResponse


class FakePublicPassportService:
    async def get_by_token(self, token: str) -> PublicPassportResponse:
        if token == "missing":
            raise NotFoundError("Trust Passport not found")

        return PublicPassportResponse(
            profile=PublicPassportProfile(
                full_name="Investor Demo",
                headline="Engineer",
                location="Bengaluru",
                avatar_url=None,
                profile_slug="investor-demo",
            ),
            trust_score=TrustScoreResponse(
                overall=75,
                breakdown=TrustScoreComponentBreakdown(
                    identity=80,
                    employment=70,
                    education=75,
                    documents=74,
                ),
                week_change=0,
            ),
            vault=PublicPassportVault(
                employments=[
                    PublicPassportEmployment(
                        id=uuid4(),
                        employer_legal_name=None,
                        job_title="Backend Engineer",
                        start_date=date(2024, 1, 1),
                        end_date=None,
                        verification_status="approved",
                        verification_method="document",
                        documents=[],
                    )
                ],
                educations=[
                    PublicPassportEducation(
                        id=uuid4(),
                        institution_name="Example University",
                        degree="B.Tech",
                        field_of_study="Computer Science",
                        education_level="bachelors",
                        grade=None,
                        start_date=date(2019, 1, 1),
                        end_date=date(2023, 1, 1),
                        is_currently_studying=False,
                        verification_status="verified",
                    )
                ],
                internships=[
                    PublicPassportInternship(
                        id=uuid4(),
                        company_name="Example Co",
                        role="Intern",
                        description=None,
                        start_date=date(2022, 5, 1),
                        end_date=date(2022, 7, 1),
                        is_ongoing=False,
                        verification_status="verified",
                    )
                ],
                freelance=[
                    PublicPassportFreelance(
                        id=uuid4(),
                        client_name="Acme",
                        project_title="Payments",
                        description=None,
                        start_date=date(2023, 2, 1),
                        end_date=date(2023, 5, 1),
                        is_ongoing=False,
                        verification_status="verified",
                    )
                ],
                gig_platforms=[
                    PublicPassportGigPlatform(
                        id=uuid4(),
                        platform_name="PlatformX",
                        partner_role="Driver",
                        started_at=date(2021, 1, 1),
                        ended_at=None,
                        is_active=True,
                        rating=4.9,
                        verification_status="verified",
                    )
                ],
                portfolio=[
                    PublicPassportPortfolioItem(
                        id=uuid4(),
                        title="Trust Platform",
                        description=None,
                        url="https://example.com",
                        tags=["trust", "backend"],
                        verification_status="pending",
                    )
                ],
                certifications=[
                    PublicPassportCertification(
                        id=uuid4(),
                        title="AWS SA",
                        issuing_organization="AWS",
                        issued_date=date(2024, 3, 1),
                        expiry_date=None,
                        does_not_expire=False,
                        credential_id=None,
                        credential_url=None,
                        verification_status="verified",
                    )
                ],
                user_documents=[],
            ),
            share=PublicPassportShareMetadata(
                id=uuid4(),
                label="Investor Link",
                expires_at=datetime.now(tz=UTC) + timedelta(days=7),
                track_views=True,
                permissions=PassportSharePermissions(
                    show_employer_names=False,
                    show_documents=False,
                ),
            ),
        )


@pytest.mark.asyncio
async def test_get_public_passport_returns_backend_authoritative_payload() -> None:
    app.dependency_overrides[get_public_passport_service] = lambda: FakePublicPassportService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/public/passport/demo-token")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["profile"]["full_name"] == "Investor Demo"
    assert body["trust_score"]["overall"] == 75
    assert body["vault"]["employments"][0]["employer_legal_name"] is None
    assert body["share"]["permissions"]["show_employer_names"] is False


@pytest.mark.asyncio
async def test_get_public_passport_fails_closed_for_missing_token() -> None:
    app.dependency_overrides[get_public_passport_service] = lambda: FakePublicPassportService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/public/passport/missing")

    app.dependency_overrides.clear()
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["message"] == "Trust Passport not found"
