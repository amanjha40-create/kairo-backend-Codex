"""Employment location persistence regression coverage."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.employment.enums import WorkArrangement
from app.models.employment import Employment
from app.schemas.employment import EmploymentPublic
from app.schemas.employment.requests import CreateEmploymentRequest, UpdateEmploymentRequest
from app.services.employment_service import EmploymentService


def _employment(**overrides: object) -> Employment:
    values = {
        "created_by_user_id": uuid4(),
        "subject_full_name": "Synthetic Candidate",
        "subject_email": "candidate@example.invalid",
        "employer_legal_name": "Synthetic Employer",
        "job_title": "Engineer",
        "employment_type": "full_time",
        "start_date": date(2024, 1, 1),
        "work_location_city": "Mumbai",
        "work_location_country": "IN",
        "work_location_region": "Maharashtra",
        "work_arrangement": "hybrid",
        "verification_method": "document",
        "verification_status": "draft",
    }
    values.update(overrides)
    row = Employment(**values)
    row.id = uuid4()
    row.created_at = datetime.now(UTC)
    row.updated_at = row.created_at
    return row


@pytest.mark.asyncio
async def test_employment_service_create_maps_city_country_and_arrangement() -> None:
    service = EmploymentService.__new__(EmploymentService)
    captured: list[Employment] = []

    class Repository:
        async def create(self, row: Employment) -> Employment:
            captured.append(row)
            row.id = uuid4()
            row.created_at = datetime.now(UTC)
            row.updated_at = row.created_at
            return row

    service._employment = Repository()
    service._emit_audit = AsyncMock()
    service._users = SimpleNamespace(
        mark_employment_onboarding_completed_if_needed=AsyncMock()
    )
    service._session = SimpleNamespace(commit=AsyncMock())

    response = await service.create(
        uuid4(),
        CreateEmploymentRequest(
            subject_full_name="Synthetic Candidate",
            employer_legal_name="Synthetic Employer",
            job_title="Engineer",
            start_date=date(2024, 1, 1),
            work_location_city="Mumbai",
            work_location_country="in",
            work_location_region="Maharashtra",
            work_arrangement=WorkArrangement.HYBRID,
        ),
    )

    assert captured[0].work_location_city == "Mumbai"
    assert captured[0].work_location_country == "IN"
    assert captured[0].work_arrangement == "hybrid"
    assert response.work_location_city == "Mumbai"
    assert response.work_location_country == "IN"
    assert response.work_arrangement == "hybrid"


@pytest.mark.asyncio
async def test_employment_service_update_persists_city_and_arrangement() -> None:
    row = _employment(work_location_city="Pune", work_arrangement="onsite")
    service = EmploymentService.__new__(EmploymentService)
    service._employment = SimpleNamespace(get_owned_active=AsyncMock(return_value=row))
    service._verification_requests = SimpleNamespace(
        get_latest_for_subject_employment=AsyncMock(return_value=None),
        get_active_for_employment=AsyncMock(return_value=None),
    )
    service._verification_workflow = SimpleNamespace(record_action=AsyncMock())
    service._emit_audit = AsyncMock()
    service._session = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())

    response = await service.update(
        row.created_by_user_id,
        row.id,
        UpdateEmploymentRequest(
            work_location_city="Mumbai",
            work_arrangement=WorkArrangement.REMOTE,
        ),
    )

    assert row.work_location_city == "Mumbai"
    assert row.work_arrangement == "remote"
    assert response.work_location_city == "Mumbai"
    assert response.work_arrangement == "remote"


def test_employment_response_serializes_location_and_accepts_nulls() -> None:
    response = EmploymentPublic.model_validate(_employment())

    assert response.model_dump(mode="json")["work_location_city"] == "Mumbai"
    assert response.model_dump(mode="json")["work_arrangement"] == "hybrid"

    blank = CreateEmploymentRequest(
        subject_full_name="Synthetic Candidate",
        employer_legal_name="Synthetic Employer",
        job_title="Engineer",
        start_date=date(2024, 1, 1),
        work_location_city=" ",
        work_location_country=None,
        work_location_region="",
        work_arrangement="",
    )
    assert blank.work_location_city is None
    assert blank.work_location_country is None
    assert blank.work_location_region is None
    assert blank.work_arrangement is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_employment_location_columns_persist_in_postgresql() -> None:
    from app.db.session import async_session_factory
    from app.models.user import User

    async with async_session_factory() as session:
        transaction = await session.begin()
        user = User(
            email=f"employment-location-{uuid4()}@example.invalid",
            full_name="Synthetic Candidate",
            role="user",
            is_active=True,
        )
        session.add(user)
        await session.flush()
        row = _employment(created_by_user_id=user.id)
        session.add(row)
        await session.flush()
        await session.refresh(row)

        assert row.work_location_city == "Mumbai"
        assert row.work_location_country == "IN"
        assert row.work_arrangement == "hybrid"
        await transaction.rollback()
