"""Route-contract tests for Admin Trust & Safety APIs."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.services import get_trust_safety_service
from app.api.dependencies.verification_admin import (
    CurrentUser,
    require_trust_safety_assign,
    require_trust_safety_create,
    require_trust_safety_note,
    require_trust_safety_read,
    require_trust_safety_resolve,
    require_trust_safety_update_severity,
)
from app.auth.deps import get_current_user
from app.main import app
from app.schemas.pagination import Page, PageParams
from app.schemas.trust_safety import (
    RiskSignalResponse,
    TrustSafetyInvestigationDetailResponse,
    TrustSafetyInvestigationEventResponse,
    TrustSafetyInvestigationListItemResponse,
    TrustSafetyInvestigationNoteResponse,
    TrustSafetyOverviewSummaryResponse,
    TrustSafetySubjectContextResponse,
)


def _signal() -> RiskSignalResponse:
    return RiskSignalResponse(
        public_id=UUID("00000000-0000-0000-0000-000000000401"),
        signal_type="repeated_correction_cycles",
        subject_type="verification_request",
        subject_public_id=UUID("00000000-0000-0000-0000-000000000201"),
        severity="high",
        source="verification_workflow",
        summary="Repeated correction loops exceeded the threshold.",
        metadata={"correction_cycles": 3},
        status="active",
        detected_at=datetime.now(tz=UTC),
        resolved_at=None,
        investigation_public_id=UUID("00000000-0000-0000-0000-000000000101"),
    )


def _note() -> TrustSafetyInvestigationNoteResponse:
    return TrustSafetyInvestigationNoteResponse(
        public_id=UUID("00000000-0000-0000-0000-000000000501"),
        author_user_id=UUID("00000000-0000-0000-0000-000000000999"),
        author_display_name="Aman Jha",
        body="Initial triage complete.",
        metadata={},
        created_at=datetime.now(tz=UTC),
    )


def _event() -> TrustSafetyInvestigationEventResponse:
    return TrustSafetyInvestigationEventResponse(
        public_id=UUID("00000000-0000-0000-0000-000000000601"),
        actor_user_id=UUID("00000000-0000-0000-0000-000000000999"),
        actor_display_name="Aman Jha",
        event_type="investigation_created",
        detail="Manual review opened.",
        metadata={},
        created_at=datetime.now(tz=UTC),
    )


def _list_item() -> TrustSafetyInvestigationListItemResponse:
    now = datetime.now(tz=UTC)
    return TrustSafetyInvestigationListItemResponse(
        public_id=UUID("00000000-0000-0000-0000-000000000101"),
        title="Repeated correction cycles",
        summary="Three correction loops in the last seven days.",
        status="open",
        severity="high",
        subject_type="verification_request",
        subject_public_id=UUID("00000000-0000-0000-0000-000000000201"),
        subject_label="Verification 00000000",
        primary_signal_summary="Repeated correction loops exceeded the threshold.",
        assignee=None,
        created_at=now,
        updated_at=now,
    )


def _detail() -> TrustSafetyInvestigationDetailResponse:
    item = _list_item()
    return TrustSafetyInvestigationDetailResponse(
        **item.model_dump(),
        created_by_user_id=UUID("00000000-0000-0000-0000-000000000999"),
        resolved_by_user_id=None,
        resolved_at=None,
        resolution_reason=None,
        dismissed_at=None,
        dismissed_by_user_id=None,
        dismissal_reason=None,
        signals=[_signal()],
        notes=[_note()],
        timeline=[_event()],
        subject_context=TrustSafetySubjectContextResponse(),
    )


class FakeTrustSafetyService:
    def __init__(self) -> None:
        self.created_payload = None

    async def list_signals(self, params):  # noqa: ANN001
        return Page[RiskSignalResponse].create(
            items=[_signal()],
            total=1,
            params=PageParams(page=params.page, page_size=params.page_size),
        )

    async def list_investigations(self, params):  # noqa: ANN001
        return Page[TrustSafetyInvestigationListItemResponse].create(
            items=[_list_item()],
            total=1,
            params=PageParams(page=params.page, page_size=params.page_size),
        )

    async def list_assignees(self, params):  # noqa: ANN001
        return Page.create(
            items=[
                {
                    "user_id": UUID("00000000-0000-0000-0000-000000000999"),
                    "full_name": "Aman Jha",
                    "email": "aman@example.com",
                    "role": "admin",
                }
            ],
            total=1,
            params=PageParams(page=params.page, page_size=params.page_size),
        )

    async def summary(self) -> TrustSafetyOverviewSummaryResponse:
        return TrustSafetyOverviewSummaryResponse(
            open_investigations=3,
            high_or_critical_investigations=2,
            unassigned_investigations=1,
            active_signals=4,
        )

    async def create_investigation(self, actor, payload):  # noqa: ANN001
        self.created_payload = (actor, payload)
        return _detail()

    async def get_detail(self, actor, investigation_public_id):  # noqa: ANN001, ARG002
        return _detail()

    async def assign(self, actor, investigation_public_id, payload):  # noqa: ANN001, ARG002
        return _detail()

    async def update_severity(
        self,
        actor,
        investigation_public_id,
        payload,
    ):  # noqa: ANN001, ARG002
        return _detail().model_copy(update={"severity": payload.severity})

    async def add_note(self, actor, investigation_public_id, payload):  # noqa: ANN001, ARG002
        return _note().model_copy(update={"body": payload.body})

    async def update_status(
        self,
        actor,
        investigation_public_id,
        payload,
    ):  # noqa: ANN001, ARG002
        return _detail().model_copy(update={"status": payload.status})

    async def resolve(self, actor, investigation_public_id, payload):  # noqa: ANN001, ARG002
        return _detail().model_copy(
            update={"status": "resolved", "resolution_reason": payload.reason}
        )

    async def dismiss(self, actor, investigation_public_id, payload):  # noqa: ANN001, ARG002
        return _detail().model_copy(
            update={"status": "dismissed", "dismissal_reason": payload.reason}
        )


async def _allow_admin() -> SimpleNamespace:
    return SimpleNamespace(
        id=UUID("00000000-0000-0000-0000-000000000999"),
        email="admin@kairo.test",
        role="admin",
    )


async def _candidate_user() -> CurrentUser:
    return CurrentUser(id=uuid4(), email="candidate@kairo.test", role="user")


@pytest.mark.asyncio
async def test_trust_safety_list_and_summary_routes_return_backend_pages() -> None:
    app.dependency_overrides[get_trust_safety_service] = lambda: FakeTrustSafetyService()
    app.dependency_overrides[require_trust_safety_read] = _allow_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        list_response = await client.get(
            "/api/v1/admin/trust-safety/investigations?page=1&page_size=10"
        )
        signals_response = await client.get(
            "/api/v1/admin/trust-safety/signals?page=1&page_size=10"
        )
        assignees_response = await client.get(
            "/api/v1/admin/trust-safety/assignees?page=1&page_size=10"
        )
        summary_response = await client.get("/api/v1/admin/trust-safety/summary")

    app.dependency_overrides.clear()

    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["title"] == "Repeated correction cycles"
    assert signals_response.status_code == 200
    assert signals_response.json()["items"][0]["signal_type"] == "repeated_correction_cycles"
    assert assignees_response.status_code == 200
    assert assignees_response.json()["items"][0]["email"] == "aman@example.com"
    assert summary_response.status_code == 200
    assert summary_response.json()["high_or_critical_investigations"] == 2


@pytest.mark.asyncio
async def test_trust_safety_detail_and_mutation_routes_return_safe_payloads() -> None:
    service = FakeTrustSafetyService()
    app.dependency_overrides[get_trust_safety_service] = lambda: service
    app.dependency_overrides[require_trust_safety_read] = _allow_admin
    app.dependency_overrides[require_trust_safety_create] = _allow_admin
    app.dependency_overrides[require_trust_safety_assign] = _allow_admin
    app.dependency_overrides[require_trust_safety_update_severity] = _allow_admin
    app.dependency_overrides[require_trust_safety_note] = _allow_admin
    app.dependency_overrides[require_trust_safety_resolve] = _allow_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        detail = await client.get(
            "/api/v1/admin/trust-safety/investigations/00000000-0000-0000-0000-000000000101"
        )
        created = await client.post(
            "/api/v1/admin/trust-safety/investigations",
            json={
                "subject_type": "verification_request",
                "subject_public_id": "00000000-0000-0000-0000-000000000201",
                "summary": "Open a manual review.",
                "severity": "medium",
                "signal_type": "manual_review",
            },
        )
        assigned = await client.post(
            "/api/v1/admin/trust-safety/investigations/00000000-0000-0000-0000-000000000101/assign",
            json={"assignee_user_id": "00000000-0000-0000-0000-000000000999"},
        )
        note = await client.post(
            "/api/v1/admin/trust-safety/investigations/00000000-0000-0000-0000-000000000101/notes",
            json={"body": "Escalate if another loop appears."},
        )
        resolved = await client.post(
            "/api/v1/admin/trust-safety/investigations/00000000-0000-0000-0000-000000000101/resolve",
            json={"reason": "Manual review completed."},
        )

    app.dependency_overrides.clear()

    assert detail.status_code == 200
    assert detail.json()["signals"][0]["signal_type"] == "repeated_correction_cycles"
    assert created.status_code == 201
    assert service.created_payload is not None
    assert created.json()["public_id"] == "00000000-0000-0000-0000-000000000101"
    assert assigned.status_code == 200
    assert note.status_code == 201
    assert note.json()["body"] == "Escalate if another loop appears."
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"


@pytest.mark.asyncio
async def test_trust_safety_routes_require_authentication_and_permission() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        unauthenticated = await client.get("/api/v1/admin/trust-safety/investigations")

    app.dependency_overrides[get_current_user] = _candidate_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        forbidden = await client.get("/api/v1/admin/trust-safety/investigations")
    app.dependency_overrides.clear()

    assert unauthenticated.status_code == 401
    assert forbidden.status_code == 403
