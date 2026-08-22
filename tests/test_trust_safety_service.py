"""Focused regression tests for Trust & Safety service behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.schemas.admin_directory import AdminReviewerPage, AdminReviewerResponse
from app.schemas.pagination import PageParams
from app.schemas.trust_safety import (
    TrustSafetyInvestigationEventResponse,
    TrustSafetyInvestigationNoteResponse,
    TrustSafetyListParams,
    TrustSafetySubjectContextResponse,
)
from app.services.admin_directory_service import AdminDirectoryService
from app.services.trust_safety_service import TrustSafetyService


@pytest.mark.asyncio
async def test_list_assignees_maps_admin_directory_items(monkeypatch: pytest.MonkeyPatch) -> None:
    params = TrustSafetyListParams(page=1, page_size=10)
    reviewer_page = AdminReviewerPage.create(
        items=[
            AdminReviewerResponse(
                user_id=UUID("00000000-0000-0000-0000-000000000901"),
                full_name="Aman Jha",
                email="aman@example.com",
                role="admin",
            )
        ],
        total=1,
        params=PageParams(page=1, page_size=10),
    )

    async def fake_list(self, incoming_params):  # noqa: ANN001, ARG001
        return reviewer_page

    monkeypatch.setattr(
        AdminDirectoryService,
        "list_trust_safety_assignees",
        fake_list,
    )

    service = TrustSafetyService(session=object(), settings=None)

    page = await service.list_assignees(params)

    assert page.total == 1
    assert page.items[0].user_id == UUID("00000000-0000-0000-0000-000000000901")
    assert page.items[0].email == "aman@example.com"
    assert page.items[0].role == "admin"


@pytest.mark.asyncio
async def test_get_detail_reloads_investigation_without_refreshing_relationships(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NoRefreshSession:
        async def refresh(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("get_detail should not refresh the investigation instance")

    now = datetime.now(tz=UTC)
    signal = SimpleNamespace(
        public_id=UUID("00000000-0000-0000-0000-000000000401"),
        signal_type="manual_review",
        subject_type="user",
        subject_public_id=UUID("00000000-0000-0000-0000-000000000201"),
        severity="high",
        source="manual",
        summary="Disposable QA user requires review.",
        metadata_payload={},
        status="active",
        detected_at=now,
        resolved_at=None,
        investigation=None,
    )
    note = SimpleNamespace(public_id=UUID("00000000-0000-0000-0000-000000000501"))
    event = SimpleNamespace(public_id=UUID("00000000-0000-0000-0000-000000000601"))
    investigation = SimpleNamespace(
        public_id=UUID("00000000-0000-0000-0000-000000000101"),
        title="Disposable QA review",
        summary="Disposable QA user requires review.",
        status="open",
        severity="high",
        subject_type="user",
        subject_public_id=UUID("00000000-0000-0000-0000-000000000201"),
        assigned_admin_user_id=None,
        created_by_user_id=UUID("00000000-0000-0000-0000-000000000999"),
        resolved_by_user_id=None,
        resolved_at=None,
        resolution_reason=None,
        dismissed_at=None,
        dismissed_by_user_id=None,
        dismissal_reason=None,
        created_at=now,
        updated_at=now,
        signals=[signal],
        notes=[note],
        events=[event],
    )
    ensure_calls: list[tuple[str, UUID]] = []

    async def fake_get_required(self, investigation_public_id):  # noqa: ANN001, ARG001
        return investigation

    async def fake_ensure(self, subject_type, subject_public_id):  # noqa: ANN001
        ensure_calls.append((subject_type, subject_public_id))

    async def fake_subject_label(self, subject_type, subject_public_id):  # noqa: ANN001, ARG001
        return "Disposable QA User"

    async def fake_assignee(self, assignee_user_id):  # noqa: ANN001, ARG001
        return None

    async def fake_note(self, item):  # noqa: ANN001, ARG001
        return TrustSafetyInvestigationNoteResponse(
            public_id=UUID("00000000-0000-0000-0000-000000000501"),
            author_user_id=UUID("00000000-0000-0000-0000-000000000999"),
            author_display_name="Aman Jha",
            body="Initial triage complete.",
            metadata={},
            created_at=now,
        )

    async def fake_event(self, item):  # noqa: ANN001, ARG001
        return TrustSafetyInvestigationEventResponse(
            public_id=UUID("00000000-0000-0000-0000-000000000601"),
            actor_user_id=UUID("00000000-0000-0000-0000-000000000999"),
            actor_display_name="Aman Jha",
            event_type="investigation_created",
            detail="Manual investigation opened.",
            metadata={},
            created_at=now,
        )

    async def fake_subject_context(self, actor, item):  # noqa: ANN001, ARG001
        return TrustSafetySubjectContextResponse()

    monkeypatch.setattr(TrustSafetyService, "_get_required_investigation", fake_get_required)
    monkeypatch.setattr(TrustSafetyService, "_ensure_subject_automatic_signals", fake_ensure)
    monkeypatch.setattr(TrustSafetyService, "_subject_label", fake_subject_label)
    monkeypatch.setattr(TrustSafetyService, "_assignee_response", fake_assignee)
    monkeypatch.setattr(TrustSafetyService, "_to_note_response", fake_note)
    monkeypatch.setattr(TrustSafetyService, "_to_event_response", fake_event)
    monkeypatch.setattr(TrustSafetyService, "_subject_context", fake_subject_context)

    service = TrustSafetyService(session=NoRefreshSession(), settings=None)

    detail = await service.get_detail(
        actor=SimpleNamespace(
            id=UUID("00000000-0000-0000-0000-000000000999"),
            email="admin@kairo.test",
            full_name="Aman Jha",
            role="admin",
        ),
        investigation_public_id=investigation.public_id,
    )

    assert ensure_calls == [("user", UUID("00000000-0000-0000-0000-000000000201"))]
    assert detail.public_id == investigation.public_id
    assert detail.subject_label == "Disposable QA User"
    assert len(detail.signals) == 1
    assert detail.signals[0].summary == "Disposable QA user requires review."
    assert len(detail.notes) == 1
    assert len(detail.timeline) == 1
