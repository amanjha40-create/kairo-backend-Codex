"""Phase-1 client compatibility coverage for nullable Employment types."""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.config import Settings
from app.employment.client_compatibility import (
    NULLABLE_EMPLOYMENT_TYPE_CAPABILITY,
    ClientMetadata,
    EmploymentClientClass,
    bind_client_metadata,
    parse_client_metadata,
    reset_client_metadata,
)
from app.employment.enums import EmploymentType
from app.exceptions import EmploymentClientUpgradeRequiredError
from app.exceptions.handlers import app_exception_handler
from app.models.employment import Employment
from app.schemas.employer_verification import EmployerPortalEmployment
from app.schemas.employment.requests import CreateEmploymentRequest, UpdateEmploymentRequest
from app.schemas.employment.responses import EmploymentResponse
from app.schemas.hr_v2 import VerificationReportEmploymentItem
from app.schemas.verification_request import VerificationRequestEmploymentClaimResponse
from app.services.employment_service import EmploymentService
from app.services.resume_review_service import ResumeReviewService


@contextmanager
def client(*, capable: bool):
    capabilities = (
        frozenset({NULLABLE_EMPLOYMENT_TYPE_CAPABILITY}) if capable else frozenset()
    )
    token = bind_client_metadata(ClientMetadata(capabilities=capabilities))
    try:
        yield
    finally:
        reset_client_metadata(token)


def test_client_metadata_parser_handles_capabilities_absence_and_malformed_values() -> None:
    parsed = parse_client_metadata(
        {
            "x-kairoid-platform": "android",
            "x-kairoid-package": "com.kairoid.app.qa",
            "x-kairoid-version-code": "6",
            "x-kairoid-version-name": "1.0",
            "x-kairoid-capabilities": (
                "future-capability, NULLABLE-EMPLOYMENT-TYPE-V1, future-capability"
            ),
        }
    )
    assert parsed.capabilities == frozenset(
        {"future-capability", NULLABLE_EMPLOYMENT_TYPE_CAPABILITY}
    )
    assert parsed.client_class is EmploymentClientClass.NULLABLE_EMPLOYMENT_CAPABLE

    absent = parse_client_metadata({})
    assert absent.client_class is EmploymentClientClass.LEGACY_OR_UNKNOWN

    malformed = parse_client_metadata(
        {"x-kairoid-capabilities": "x" * 2049}
    )
    assert malformed.capabilities == frozenset()
    assert malformed.client_class is EmploymentClientClass.LEGACY_OR_UNKNOWN


def test_nullable_write_flag_defaults_off_and_accepts_explicit_enable(monkeypatch) -> None:
    monkeypatch.delenv("ENABLE_NULLABLE_EMPLOYMENT_TYPE_WRITES", raising=False)
    assert Settings().enable_nullable_employment_type_writes is False
    monkeypatch.setenv("ENABLE_NULLABLE_EMPLOYMENT_TYPE_WRITES", "true")
    assert Settings().enable_nullable_employment_type_writes is True


def _employment_response(value: str | None) -> EmploymentResponse:
    now = datetime.now(UTC)
    return EmploymentResponse.model_validate(
        SimpleNamespace(
            id=uuid4(),
            subject_full_name="Synthetic Candidate",
            subject_email=None,
            employer_legal_name="Synthetic Employer",
            employer_trade_name=None,
            job_title="Engineer",
            employment_type=value,
            start_date=date(2024, 1, 1),
            end_date=None,
            work_location_city=None,
            work_location_country=None,
            work_location_region=None,
            work_arrangement=None,
            verification_method="document",
            verification_status="draft",
            submitted_at=None,
            reviewed_at=None,
            verified_at=None,
            assigned_reviewer_user_id=None,
            assigned_at=None,
            created_at=now,
            updated_at=now,
        )
    )


@pytest.mark.parametrize("capable", [False, True])
def test_non_null_type_is_never_shimmed(capable: bool) -> None:
    with client(capable=capable):
        response = _employment_response("full_time")
        assert response.model_dump(mode="json")["employment_type"] == "full_time"


def test_null_response_is_shimmed_for_legacy_but_canonical_model_stays_null() -> None:
    with client(capable=False):
        response = _employment_response(None)
        assert response.employment_type is None
        assert response.model_dump(mode="json")["employment_type"] == "other"
        assert response.employment_type is None

    with client(capable=True):
        response = _employment_response(None)
        assert response.model_dump(mode="json")["employment_type"] is None


@pytest.mark.parametrize(
    "projection",
    [
        EmployerPortalEmployment(
            employer_name="Synthetic Employer",
            job_title="Engineer",
            employment_type=None,
            country=None,
        ),
        VerificationRequestEmploymentClaimResponse(employment_type=None),
        VerificationReportEmploymentItem(
            organization="Synthetic Employer",
            employment_type=None,
            status="PENDING",
        ),
    ],
)
def test_employer_organization_admin_and_hr_projections_share_the_shim(projection) -> None:
    with client(capable=False):
        assert projection.model_dump(mode="json")["employment_type"] == "other"
    with client(capable=True):
        assert projection.model_dump(mode="json")["employment_type"] is None


def _employment(value: str | None) -> Employment:
    row = Employment(
        created_by_user_id=uuid4(),
        subject_full_name="Synthetic Candidate",
        employer_legal_name="Synthetic Employer",
        job_title="Engineer",
        employment_type=value,
        start_date=date(2024, 1, 1),
        verification_method="document",
        verification_status="draft",
    )
    row.id = uuid4()
    row.created_at = datetime.now(UTC)
    row.updated_at = row.created_at
    return row


def _update_service(row: Employment, *, enabled: bool) -> EmploymentService:
    service = EmploymentService.__new__(EmploymentService)
    service._settings = SimpleNamespace(enable_nullable_employment_type_writes=enabled)
    service._employment = SimpleNamespace(get_owned_active=AsyncMock(return_value=row))
    service._verification_requests = SimpleNamespace(
        get_latest_for_subject_employment=AsyncMock(return_value=None),
        get_active_for_employment=AsyncMock(return_value=None),
    )
    service._verification_workflow = SimpleNamespace(record_action=AsyncMock())
    service._emit_audit = AsyncMock()
    service._session = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())
    return service


@pytest.mark.asyncio
async def test_legacy_null_mutation_is_blocked_before_any_mutation() -> None:
    row = _employment(None)
    service = _update_service(row, enabled=False)

    with client(capable=False), pytest.raises(
        EmploymentClientUpgradeRequiredError,
        match="Update KairoID",
    ) as caught:
        await service.update(
            row.created_by_user_id,
            row.id,
            UpdateEmploymentRequest(job_title="Mutated"),
        )

    assert caught.value.code == "client_upgrade_required"
    assert row.job_title == "Engineer"
    service._verification_requests.get_latest_for_subject_employment.assert_not_awaited()
    service._emit_audit.assert_not_awaited()
    service._session.commit.assert_not_awaited()
    service._session.refresh.assert_not_awaited()

    response = await app_exception_handler(None, caught.value)
    assert response.status_code == 409
    assert json.loads(response.body)["error"]["code"] == "client_upgrade_required"


@pytest.mark.asyncio
async def test_capable_client_can_preserve_or_replace_canonical_null_when_enabled() -> None:
    row = _employment(None)
    service = _update_service(row, enabled=True)

    with client(capable=True):
        await service.update(
            row.created_by_user_id,
            row.id,
            UpdateEmploymentRequest(job_title="Lead"),
        )
        assert row.employment_type is None
        await service.update(
            row.created_by_user_id,
            row.id,
            UpdateEmploymentRequest(employment_type=EmploymentType.CONTRACT),
        )
        assert row.employment_type == "contract"


@pytest.mark.asyncio
async def test_phase1_explicit_clear_is_coerced_to_other_without_creating_null() -> None:
    row = _employment("contract")
    service = _update_service(row, enabled=False)

    with client(capable=True):
        await service.update(
            row.created_by_user_id,
            row.id,
            UpdateEmploymentRequest(employment_type=None),
        )

    assert row.employment_type == "other"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("enabled", "capable", "expected"),
    [
        (False, True, "other"),
        (True, False, "other"),
        (True, True, None),
    ],
)
async def test_manual_missing_type_is_flag_and_capability_gated(
    enabled: bool,
    capable: bool,
    expected: str | None,
) -> None:
    service = EmploymentService.__new__(EmploymentService)
    service._settings = SimpleNamespace(enable_nullable_employment_type_writes=enabled)
    captured: list[Employment] = []

    async def create(row: Employment) -> Employment:
        captured.append(row)
        row.id = uuid4()
        row.created_at = datetime.now(UTC)
        row.updated_at = row.created_at
        return row

    service._employment = SimpleNamespace(create=create)
    service._emit_audit = AsyncMock()
    service._users = SimpleNamespace(
        mark_employment_onboarding_completed_if_needed=AsyncMock()
    )
    service._session = SimpleNamespace(commit=AsyncMock())

    with client(capable=capable):
        await service.create(
            uuid4(),
            CreateEmploymentRequest(
                subject_full_name="Synthetic Candidate",
                employer_legal_name="Synthetic Employer",
                job_title="Engineer",
                start_date=date(2024, 1, 1),
            ),
        )
    assert captured[0].employment_type == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("enabled", "capable", "source", "expected"),
    [
        (False, True, None, "other"),
        (False, True, "seasonal", "other"),
        (False, True, "other", "other"),
        (False, True, "Full-time", "full_time"),
        (True, True, None, None),
        (True, True, "seasonal", None),
        (True, True, "other", "other"),
        (True, True, "Full-time", "full_time"),
        (True, False, None, "other"),
        (True, False, "seasonal", "other"),
        (True, False, "other", "other"),
        (True, False, "Full-time", "full_time"),
    ],
)
async def test_resume_write_behavior_is_feature_gated(
    enabled: bool,
    capable: bool,
    source: str | None,
    expected: str | None,
) -> None:
    class Session:
        async def get(self, _model, _user_id):
            return SimpleNamespace(
                full_name="Synthetic Candidate",
                email="candidate@example.invalid",
            )

    service = ResumeReviewService(
        Session(),
        SimpleNamespace(enable_nullable_employment_type_writes=enabled),
    )
    with client(capable=capable):
        record = await service._create_record(
            uuid4(),
            "employment",
            {
                "company_name": "Synthetic Employer",
                "role_title": "Engineer",
                "employment_type": source,
            },
        )
    assert record.employment_type == expected


def test_telemetry_contains_only_aggregate_compatibility_dimensions(caplog) -> None:
    from app.employment.client_compatibility import (
        observe_capable_nullable_write,
        observe_client_request,
        observe_employment_type_fallback_write,
        observe_legacy_mutation_blocked,
        observe_legacy_response_shim,
    )

    with caplog.at_level(logging.INFO), client(capable=False):
        observe_client_request(nullable_writes_enabled=False)
        observe_capable_nullable_write(source="manual_create")
        observe_employment_type_fallback_write(source="resume_import")
        observe_legacy_response_shim()
        observe_legacy_mutation_blocked()

    records = [
        record
        for record in caplog.records
        if record.name.endswith("client_compatibility")
    ]
    assert len(records) == 5
    for record in records:
        assert record.count == 1
        assert record.client_class in {
            "legacy_or_unknown",
            "nullable_employment_capable",
        }
        for forbidden in ("email", "candidate_id", "employment_id", "company", "token"):
            assert not hasattr(record, forbidden)
