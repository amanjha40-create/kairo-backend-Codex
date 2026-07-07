"""Unit tests for the verification connector framework."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.exceptions import ServiceUnavailableError
from app.models.organization import Organization
from app.models.verification_connector import VerificationConnector
from app.models.verification_request import VerificationRequest
from app.models.trust_registry_record import TrustRegistryRecord
from app.schemas.verification_connector import VerificationConnectorResult
from app.services.connector_execution_service import ConnectorExecutionService
from app.services.connector_result_normalizer import ConnectorResultNormalizer
from app.services.connector_selection_service import ConnectorSelectionService
from app.verification_connectors.contracts import VerificationConnectorExecutionContext
from app.verification_connectors.mock_connector import MockVerificationConnector
from app.verification_connectors.providers import get_connector_implementations
from app.verification_requests.enums import VerificationRequestStatus, VerificationRequestType


def _build_request(*, trust_context: dict | None = None) -> VerificationRequest:
    request = VerificationRequest(
        organization_id=uuid4(),
        subject_name="Aman Jha",
        subject_email="aman3@test.com",
        request_type=VerificationRequestType.EMPLOYMENT,
        status=VerificationRequestStatus.ACCEPTED,
        requested_by_user_id=uuid4(),
        trust_context=trust_context or {},
    )
    request.public_id = uuid4()
    request.organization = Organization(
        name="Kairo Labs",
        organization_type="employer",
        verification_capabilities=["employment"],
        created_by_user_id=uuid4(),
    )
    request.organization.public_id = uuid4()
    return request


def _build_connector(*, capabilities: list[str] | None = None, registry_types: list[str] | None = None) -> VerificationConnector:
    connector = VerificationConnector(
        connector_key="mock_connector",
        display_name="Mock Verification Connector",
        connector_type="custom",
        supported_capabilities=capabilities or ["employment"],
        supported_registry_types=registry_types or ["*"],
        version="v1",
        health_status="healthy",
        enabled=True,
        priority=100,
        config={},
    )
    connector.public_id = uuid4()
    return connector


class FakeRegistry:
    def __init__(self, connectors=None, implementation=None) -> None:  # noqa: ANN001
        self._connectors = connectors or []
        self._implementation = implementation

    async def list_enabled_connectors(self):  # noqa: ANN001
        return self._connectors

    def get_implementation(self, connector_key: str):  # noqa: ARG002
        return self._implementation


class FakeRunRepository:
    def __init__(self) -> None:
        self.runs = []

    async def create(self, run):  # noqa: ANN001
        run.public_id = uuid4()
        self.runs.append(run)
        return run


class FailingConnector:
    connector_key = "mock_connector"
    display_name = "Failing Mock Connector"
    supported_capabilities = ("employment",)
    supported_registry_types = ("*",)
    version = "v1"

    async def execute(self, context: VerificationConnectorExecutionContext) -> VerificationConnectorResult:  # noqa: ARG002
        raise RuntimeError("mock connector exploded")


def test_provider_registry_includes_mock_connector() -> None:
    implementations = get_connector_implementations()

    assert any(implementation.connector_key == "mock_connector" for implementation in implementations)


@pytest.mark.asyncio
async def test_selection_picks_exact_registry_type_match_first() -> None:
    wildcard = _build_connector(registry_types=["*"])
    wildcard.priority = 100
    exact = _build_connector(registry_types=["employer"])
    exact.priority = 100
    request = _build_request()
    request.registry_record = TrustRegistryRecord(
        registry_code="KR-TEST-0001",
        legal_name="Kairo Labs Pvt Ltd",
        display_name="Kairo Labs",
        organization_type="employer",
        country="IN",
        lifecycle_status="active",
        trust_status="trusted",
        registry_confidence_score=90,
        trust_metadata={},
    )

    service = ConnectorSelectionService(FakeRegistry(connectors=[wildcard, exact]))

    selected = await service.select_for_request(request)

    assert selected is exact


@pytest.mark.asyncio
async def test_selection_rejects_unsupported_capability() -> None:
    connector = _build_connector(capabilities=["education"])
    request = _build_request()
    request.request_type = "employment"

    service = ConnectorSelectionService(FakeRegistry(connectors=[connector]))

    with pytest.raises(ServiceUnavailableError, match="No enabled verification connector"):
        await service.select_for_request(request)


@pytest.mark.asyncio
async def test_selection_rejects_when_all_connectors_disabled() -> None:
    request = _build_request()

    service = ConnectorSelectionService(FakeRegistry(connectors=[]))

    with pytest.raises(ServiceUnavailableError, match="No enabled verification connector"):
        await service.select_for_request(request)


def test_result_normalizer_backfills_completed_at() -> None:
    normalizer = ConnectorResultNormalizer()
    result = VerificationConnectorResult(
        status=" VERIFIED ",
        confidence=98,
        normalized_data={},
        raw_metadata={},
        evidence_references=[],
        errors=[],
        occurred_at=datetime.now(tz=UTC),
        completed_at=None,
    )

    normalized = normalizer.normalize(result)

    assert normalized.status == "verified"
    assert normalized.completed_at is not None


@pytest.mark.asyncio
async def test_mock_connector_supports_success_failure_and_unavailable() -> None:
    connector = MockVerificationConnector()
    request = _build_request()
    request.request_type = "employment"

    success = await connector.execute(
        VerificationConnectorExecutionContext(verification_request=request, metadata={"connector_mode": "success"})
    )
    failure = await connector.execute(
        VerificationConnectorExecutionContext(verification_request=request, metadata={"connector_mode": "failed"})
    )

    assert success.status == "verified"
    assert failure.status == "failed"
    with pytest.raises(ServiceUnavailableError, match="Mock connector is unavailable"):
        await connector.execute(
            VerificationConnectorExecutionContext(verification_request=request, metadata={"connector_mode": "unavailable"})
        )


@pytest.mark.asyncio
async def test_execution_service_records_successful_run() -> None:
    connector = _build_connector()
    request = _build_request()
    registry = FakeRegistry(implementation=MockVerificationConnector())
    service = ConnectorExecutionService(session=None, registry=registry, normalizer=ConnectorResultNormalizer())  # type: ignore[arg-type]
    service._runs = FakeRunRepository()  # type: ignore[assignment]

    run, result = await service.execute(
        connector=connector,
        request=request,
        actor_user_id=uuid4(),
        metadata={"connector_mode": "success"},
    )

    assert run.status == "succeeded"
    assert result.status == "verified"
    assert run.execution_time_ms is not None
    assert run.normalized_result["status"] == "verified"


@pytest.mark.asyncio
async def test_execution_service_marks_unavailable_runs() -> None:
    connector = _build_connector()
    request = _build_request()
    registry = FakeRegistry(implementation=MockVerificationConnector())
    service = ConnectorExecutionService(session=None, registry=registry, normalizer=ConnectorResultNormalizer())  # type: ignore[arg-type]
    service._runs = FakeRunRepository()  # type: ignore[assignment]

    with pytest.raises(ServiceUnavailableError, match="Mock connector is unavailable"):
        await service.execute(
            connector=connector,
            request=request,
            actor_user_id=uuid4(),
            metadata={"connector_mode": "unavailable"},
        )

    assert service._runs.runs[0].status == "unavailable"  # type: ignore[index]


@pytest.mark.asyncio
async def test_execution_service_marks_failed_runs_when_implementation_crashes() -> None:
    connector = _build_connector()
    request = _build_request()
    registry = FakeRegistry(implementation=FailingConnector())
    service = ConnectorExecutionService(session=None, registry=registry, normalizer=ConnectorResultNormalizer())  # type: ignore[arg-type]
    service._runs = FakeRunRepository()  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="mock connector exploded"):
        await service.execute(
            connector=connector,
            request=request,
            actor_user_id=uuid4(),
            metadata={},
        )

    assert service._runs.runs[0].status == "failed"  # type: ignore[index]
