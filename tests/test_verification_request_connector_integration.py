"""Unit tests for verification request connector integration."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.exceptions import ServiceUnavailableError
from app.models.organization import Organization
from app.models.verification_connector import VerificationConnector
from app.models.verification_connector_run import VerificationConnectorRun
from app.models.verification_request import VerificationRequest
from app.schemas.verification_connector import VerificationConnectorResult
from app.schemas.verification_request import VerificationRequestActionPayload, VerificationRequestResponse
from app.services.verification_request_service import VerificationRequestService
from app.verification_requests.enums import (
    VerificationRequestEventSource,
    VerificationRequestOriginType,
    VerificationRequestStatus,
    VerificationRequestType,
)


def _build_request() -> VerificationRequest:
    request = VerificationRequest(
        organization_id=uuid4(),
        subject_name="Aman Jha",
        subject_email="aman3@test.com",
        request_type=VerificationRequestType.EMPLOYMENT,
        status=VerificationRequestStatus.ACCEPTED,
        requested_by_user_id=uuid4(),
        trust_context={},
    )
    request.public_id = uuid4()
    request.created_at = datetime.now(tz=UTC)
    request.updated_at = request.created_at
    request.organization = Organization(
        name="Kairo Labs",
        organization_type="employer",
        verification_capabilities=["employment"],
        created_by_user_id=uuid4(),
    )
    request.organization.public_id = uuid4()
    return request


def _build_connector() -> VerificationConnector:
    connector = VerificationConnector(
        connector_key="mock_connector",
        display_name="Mock Verification Connector",
        connector_type="custom",
        supported_capabilities=["employment"],
        supported_registry_types=["*"],
        version="v1",
        health_status="healthy",
        enabled=True,
        priority=100,
        config={},
    )
    connector.public_id = uuid4()
    return connector


def _build_run() -> VerificationConnectorRun:
    run = VerificationConnectorRun(
        connector_key="mock_connector",
        verification_request_id=uuid4(),
        registry_record_id=None,
        status="succeeded",
        started_at=datetime.now(tz=UTC),
        completed_at=datetime.now(tz=UTC),
        execution_time_ms=100,
        normalized_result={},
        raw_metadata={},
        evidence_references=[],
        error={},
        retry_count=0,
    )
    run.public_id = uuid4()
    return run


def _to_response(request: VerificationRequest) -> VerificationRequestResponse:
    return VerificationRequestResponse(
        public_id=request.public_id,
        origin_type=VerificationRequestOriginType.ORGANIZATION_CREATED,
        organization_public_id=request.organization.public_id,
        trust_invitation_public_id=None,
        subject_name=request.subject_name,
        subject_email=request.subject_email,
        target_organization_name=None,
        target_organization_email=None,
        request_type=request.request_type,
        status=request.status,
        due_date=None,
        trust_context=request.trust_context,
        created_at=request.created_at,
        updated_at=request.updated_at,
    )


class FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0

    async def commit(self) -> None:
        self.commit_count += 1


class FakeWorkflow:
    def __init__(self) -> None:
        self.events: list[tuple[str, VerificationRequestEventSource, str | None]] = []

    async def record_action(self, request, *, actor_user_id, event_type, event_source, metadata=None):  # noqa: ANN001
        self.events.append((event_type, event_source, metadata.get("connector_key") if metadata else None))

    async def transition(  # noqa: ANN001
        self,
        request,
        *,
        target_status,
        actor_user_id,
        event_type,
        event_source,
        metadata=None,
    ):
        request.status = target_status
        self.events.append((event_type, event_source, metadata.get("connector_key") if metadata else None))


class FakeSelector:
    def __init__(self, connector: VerificationConnector) -> None:
        self.connector = connector
        self.called = False

    async def select_for_request(self, request):  # noqa: ANN001
        self.called = True
        return self.connector


class FakeExecutor:
    def __init__(self, outcome) -> None:  # noqa: ANN001
        self.outcome = outcome
        self.called = False

    async def execute(self, *, connector, request, actor_user_id, metadata):  # noqa: ANN001
        self.called = True
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


@pytest.mark.asyncio
async def test_verify_uses_connector_and_marks_request_verified() -> None:
    session = FakeSession()
    request = _build_request()
    connector = _build_connector()
    run = _build_run()
    result = VerificationConnectorResult(
        status="verified",
        confidence=97,
        normalized_data={},
        raw_metadata={},
        evidence_references=[],
        errors=[],
        occurred_at=datetime.now(tz=UTC),
        completed_at=datetime.now(tz=UTC),
    )
    service = VerificationRequestService(session=session)  # type: ignore[arg-type]
    service._workflow = FakeWorkflow()  # type: ignore[assignment]
    service._connector_selector = FakeSelector(connector)  # type: ignore[assignment]
    service._connector_executor = FakeExecutor((run, result))  # type: ignore[assignment]

    async def _require_manageable_request(actor_user_id: UUID, verification_request_public_id: UUID) -> VerificationRequest:  # noqa: ARG001
        return request

    async def _transition_to_in_progress_if_needed(req, actor_user_id, metadata, *, allowed_current_statuses):  # noqa: ANN001
        if req.status in allowed_current_statuses:
            req.status = VerificationRequestStatus.IN_PROGRESS

    async def _commit_and_reload(request_public_id: UUID) -> VerificationRequestResponse:
        return _to_response(request)

    service._require_manageable_request = _require_manageable_request  # type: ignore[assignment]
    service._transition_to_in_progress_if_needed = _transition_to_in_progress_if_needed  # type: ignore[assignment]
    service._commit_and_reload = _commit_and_reload  # type: ignore[assignment]

    response = await service.verify(
        actor_user_id=uuid4(),
        verification_request_public_id=request.public_id,
        payload=VerificationRequestActionPayload(note="Verified", metadata={"connector_mode": "success"}),
    )

    assert service._connector_selector.called is True  # type: ignore[attr-defined]
    assert service._connector_executor.called is True  # type: ignore[attr-defined]
    assert response.status == VerificationRequestStatus.VERIFIED
    assert any(event[0] == "verification_connector_selected" for event in service._workflow.events)  # type: ignore[attr-defined]
    assert any(event[0] == "verification_request_verified" for event in service._workflow.events)  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_verify_marks_request_rejected_for_negative_connector_result() -> None:
    session = FakeSession()
    request = _build_request()
    connector = _build_connector()
    run = _build_run()
    result = VerificationConnectorResult(
        status="failed",
        confidence=20,
        normalized_data={},
        raw_metadata={},
        evidence_references=[],
        errors=[{"code": "verification_failed", "message": "negative match"}],
        occurred_at=datetime.now(tz=UTC),
        completed_at=datetime.now(tz=UTC),
    )
    service = VerificationRequestService(session=session)  # type: ignore[arg-type]
    service._workflow = FakeWorkflow()  # type: ignore[assignment]
    service._connector_selector = FakeSelector(connector)  # type: ignore[assignment]
    service._connector_executor = FakeExecutor((run, result))  # type: ignore[assignment]

    async def _require_manageable_request(actor_user_id: UUID, verification_request_public_id: UUID) -> VerificationRequest:  # noqa: ARG001
        return request

    async def _transition_to_in_progress_if_needed(req, actor_user_id, metadata, *, allowed_current_statuses):  # noqa: ANN001
        if req.status in allowed_current_statuses:
            req.status = VerificationRequestStatus.IN_PROGRESS

    async def _commit_and_reload(request_public_id: UUID) -> VerificationRequestResponse:  # noqa: ARG001
        return _to_response(request)

    service._require_manageable_request = _require_manageable_request  # type: ignore[assignment]
    service._transition_to_in_progress_if_needed = _transition_to_in_progress_if_needed  # type: ignore[assignment]
    service._commit_and_reload = _commit_and_reload  # type: ignore[assignment]

    response = await service.verify(
        actor_user_id=uuid4(),
        verification_request_public_id=request.public_id,
        payload=VerificationRequestActionPayload(note=None, metadata={"connector_mode": "failed"}),
    )

    assert response.status == VerificationRequestStatus.REJECTED
    assert any(event[0] == "verification_request_rejected" for event in service._workflow.events)  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_verify_preserves_fail_closed_behavior_for_unavailable_connector() -> None:
    session = FakeSession()
    request = _build_request()
    connector = _build_connector()
    service = VerificationRequestService(session=session)  # type: ignore[arg-type]
    service._workflow = FakeWorkflow()  # type: ignore[assignment]
    service._connector_selector = FakeSelector(connector)  # type: ignore[assignment]
    service._connector_executor = FakeExecutor(ServiceUnavailableError("mock unavailable"))  # type: ignore[assignment]

    async def _require_manageable_request(actor_user_id: UUID, verification_request_public_id: UUID) -> VerificationRequest:  # noqa: ARG001
        return request

    async def _transition_to_in_progress_if_needed(req, actor_user_id, metadata, *, allowed_current_statuses):  # noqa: ANN001
        if req.status in allowed_current_statuses:
            req.status = VerificationRequestStatus.IN_PROGRESS

    service._require_manageable_request = _require_manageable_request  # type: ignore[assignment]
    service._transition_to_in_progress_if_needed = _transition_to_in_progress_if_needed  # type: ignore[assignment]

    with pytest.raises(ServiceUnavailableError, match="mock unavailable"):
        await service.verify(
            actor_user_id=uuid4(),
            verification_request_public_id=request.public_id,
            payload=VerificationRequestActionPayload(note=None, metadata={"connector_mode": "unavailable"}),
        )

    assert session.commit_count == 1
    assert any(event[0] == "verification_connector_run_unavailable" for event in service._workflow.events)  # type: ignore[attr-defined]
