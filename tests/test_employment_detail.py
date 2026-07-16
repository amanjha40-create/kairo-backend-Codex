"""Regression coverage for async employment-detail relationship loading."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.db.session import async_session_factory, get_session
from app.employment.enums import DocumentVerificationStatus
from app.main import app
from app.models.employment import Employment
from app.models.employment_document import EmploymentDocument
from app.models.user import User
from app.schemas.employment import EmploymentPublic


def test_employment_response_accepts_legacy_missing_country() -> None:
    now = datetime.now(UTC)
    employment = SimpleNamespace(
        id=uuid4(),
        subject_full_name="Legacy Employment Test",
        subject_email=None,
        employer_legal_name="Legacy Company",
        employer_trade_name=None,
        job_title="Test Engineer",
        employment_type="full_time",
        start_date=date(2024, 1, 1),
        end_date=None,
        work_location_country=None,
        work_location_region=None,
        verification_method="document",
        verification_status="draft",
        submitted_at=None,
        reviewed_at=None,
        assigned_reviewer_user_id=None,
        assigned_at=None,
        created_at=now,
        updated_at=now,
    )

    response = EmploymentPublic.model_validate(employment)

    assert response.work_location_country is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_owned_employment_detail_eagerly_loads_documents() -> None:
    async with async_session_factory() as session:
        transaction = await session.begin()
        user = User(
            email=f"employment-detail-{uuid4()}@example.com",
            full_name="Employment Detail Test",
            role="user",
            is_active=True,
        )
        session.add(user)
        await session.flush()

        employment = Employment(
            created_by_user_id=user.id,
            subject_full_name="Employment Detail Test",
            subject_email=user.email,
            employer_legal_name="Detail Test Company",
            job_title="Test Engineer",
            employment_type="full_time",
            start_date=date(2024, 1, 1),
            work_location_country="IN",
            verification_method="document",
            verification_status="draft",
        )
        session.add(employment)
        await session.flush()

        document = EmploymentDocument(
            employment_id=employment.id,
            uploaded_by_user_id=user.id,
            document_type="offer_letter",
            object_key=f"tests/{uuid4()}/offer-letter.pdf",
            original_filename="offer-letter.pdf",
            content_type="application/pdf",
            byte_size=128,
            checksum_sha256="a" * 64,
            verification_status=DocumentVerificationStatus.PENDING_REVIEW.value,
            extraction_status="pending",
        )
        session.add(document)
        await session.flush()

        async def override_session():
            yield session

        async def override_user() -> CurrentUser:
            return CurrentUser(id=user.id, email=user.email, role="user")

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_current_user] = override_user
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                response = await client.get(f"/api/v1/employments/{employment.id}")
        finally:
            app.dependency_overrides.clear()
            await transaction.rollback()

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(employment.id)
    assert len(payload["documents"]) == 1
    assert payload["documents"][0]["id"] == str(document.id)
    assert payload["documents"][0]["original_filename"] == "offer-letter.pdf"
