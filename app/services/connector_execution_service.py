"""Execution orchestrator for verification connectors."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ServiceUnavailableError
from app.models.verification_connector import VerificationConnector
from app.models.verification_connector_run import VerificationConnectorRun
from app.models.verification_request import VerificationRequest
from app.repositories.verification_connector import VerificationConnectorRunRepository
from app.schemas.verification_connector import VerificationConnectorResult
from app.services.connector_registry_service import ConnectorRegistryService
from app.services.connector_result_normalizer import ConnectorResultNormalizer
from app.verification_connectors.contracts import VerificationConnectorExecutionContext
from app.verification_connectors.enums import VerificationConnectorRunStatus


class ConnectorExecutionService:
    """Executes connector implementations and persists run history."""

    def __init__(
        self,
        session: AsyncSession,
        registry: ConnectorRegistryService,
        normalizer: ConnectorResultNormalizer,
    ) -> None:
        self._session = session
        self._registry = registry
        self._normalizer = normalizer
        self._runs = VerificationConnectorRunRepository(session)

    async def execute(
        self,
        *,
        connector: VerificationConnector,
        request: VerificationRequest,
        actor_user_id: UUID | None,
        metadata: dict | None = None,
    ) -> tuple[VerificationConnectorRun, VerificationConnectorResult]:
        implementation = self._registry.get_implementation(connector.connector_key)
        if implementation is None:
            raise ServiceUnavailableError(
                f"No connector implementation is registered for {connector.connector_key}"
            )

        started_at = datetime.now(tz=UTC)
        run = VerificationConnectorRun(
            connector_key=connector.connector_key,
            verification_request_id=request.id,
            registry_record_id=request.registry_record_id,
            status=VerificationConnectorRunStatus.STARTED.value,
            started_at=started_at,
            raw_metadata={"actor_user_id": str(actor_user_id) if actor_user_id is not None else None},
        )
        await self._runs.create(run)

        try:
            result = await implementation.execute(
                VerificationConnectorExecutionContext(
                    verification_request=request,
                    registry_record=request.registry_record,
                    actor_user_id=actor_user_id,
                    metadata=metadata or {},
                )
            )
            normalized_result = self._normalizer.normalize(result)
            completed_at = normalized_result.completed_at or datetime.now(tz=UTC)
            run.status = self._map_run_status(normalized_result.status)
            run.completed_at = completed_at
            run.execution_time_ms = max(int((completed_at - started_at).total_seconds() * 1000), 0)
            run.normalized_result = {
                "status": normalized_result.status,
                "confidence": normalized_result.confidence,
                "normalized_data": normalized_result.normalized_data,
                "occurred_at": normalized_result.occurred_at.isoformat(),
                "completed_at": normalized_result.completed_at.isoformat()
                if normalized_result.completed_at is not None
                else None,
            }
            run.raw_metadata = normalized_result.raw_metadata
            run.evidence_references = normalized_result.evidence_references
            run.error = {"errors": normalized_result.errors} if normalized_result.errors else {}
            return run, normalized_result
        except ServiceUnavailableError as exc:
            await self._mark_run_unavailable(run, started_at, str(exc))
            raise
        except Exception as exc:
            completed_at = datetime.now(tz=UTC)
            run.status = VerificationConnectorRunStatus.FAILED.value
            run.completed_at = completed_at
            run.execution_time_ms = max(int((completed_at - started_at).total_seconds() * 1000), 0)
            run.error = {
                "errors": [
                    {
                        "code": "connector_execution_failed",
                        "message": str(exc),
                        "type": type(exc).__name__,
                    }
                ]
            }
            raise

    async def _mark_run_unavailable(
        self,
        run: VerificationConnectorRun,
        started_at: datetime,
        message: str,
    ) -> None:
        completed_at = datetime.now(tz=UTC)
        run.status = VerificationConnectorRunStatus.UNAVAILABLE.value
        run.completed_at = completed_at
        run.execution_time_ms = max(int((completed_at - started_at).total_seconds() * 1000), 0)
        run.error = {"errors": [{"code": "connector_unavailable", "message": message}]}

    def _map_run_status(self, result_status: str) -> str:
        if result_status == "verified":
            return VerificationConnectorRunStatus.SUCCEEDED.value
        if result_status == "unavailable":
            return VerificationConnectorRunStatus.UNAVAILABLE.value
        return VerificationConnectorRunStatus.FAILED.value
