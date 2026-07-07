"""Service for loading connector catalog entries and in-code implementations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.models.verification_connector import VerificationConnector
from app.models.verification_connector_run import VerificationConnectorRun
from app.repositories.verification_connector import VerificationConnectorRepository
from app.repositories.verification_connector import VerificationConnectorRunRepository
from app.schemas.pagination import ListQueryParams, Page, filter_sort_paginate
from app.schemas.verification_connector import (
    VerificationConnectorHealthResponse,
    VerificationConnectorResponse,
    VerificationConnectorRunResponse,
    VerificationConnectorUpdateRequest,
)
from app.verification_connectors.contracts import VerificationConnectorImplementation
from app.verification_connectors.providers import get_connector_implementations


class ConnectorRegistryService:
    """Resolves connector catalog records and implementation instances."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        implementations: tuple[VerificationConnectorImplementation, ...] | None = None,
    ) -> None:
        self._session = session
        self._repo = VerificationConnectorRepository(session)
        self._runs = VerificationConnectorRunRepository(session)
        self._implementations = implementations if implementations is not None else get_connector_implementations()
        self._implementation_by_key = {
            implementation.connector_key: implementation for implementation in self._implementations
        }

    async def list_connectors(
        self,
        params: ListQueryParams | None = None,
    ) -> list[VerificationConnectorResponse] | Page[VerificationConnectorResponse]:
        connectors = [self._to_response(item) for item in await self._repo.list_all()]
        if params is None:
            return connectors
        return filter_sort_paginate(
            connectors,
            params=params,
            search_fields=("connector_key", "display_name", "connector_type", "health_status"),
            allowed_sort_fields=(
                "created_at",
                "updated_at",
                "connector_key",
                "display_name",
                "connector_type",
                "health_status",
                "priority",
            ),
            default_sort_by="priority",
            force_page_envelope=True,
        )

    async def list_enabled_connectors(self) -> list[VerificationConnector]:
        return await self._repo.list_enabled()

    async def get_connector_by_key(self, connector_key: str) -> VerificationConnector | None:
        return await self._repo.get_by_key(connector_key)

    async def get_connector_by_public_id(self, connector_public_id: UUID) -> VerificationConnector | None:
        return await self._repo.get_by_public_id(connector_public_id)

    async def get_detail(self, connector_public_id: UUID) -> VerificationConnectorResponse:
        connector = await self._require_connector(connector_public_id)
        return self._to_response(connector)

    async def update_connector(
        self,
        connector_public_id: UUID,
        payload: VerificationConnectorUpdateRequest,
    ) -> VerificationConnectorResponse:
        connector = await self._require_connector(connector_public_id)
        if payload.enabled is not None:
            connector.enabled = payload.enabled
        if payload.priority is not None:
            connector.priority = payload.priority
        if payload.health_status is not None:
            connector.health_status = payload.health_status
        await self._session.commit()
        await self._session.refresh(connector)
        refreshed = await self._require_connector(connector_public_id)
        return self._to_response(refreshed)

    async def get_health(self, connector_public_id: UUID) -> VerificationConnectorHealthResponse:
        connector = await self._require_connector(connector_public_id)
        return VerificationConnectorHealthResponse(
            connector_public_id=connector.public_id,
            connector_key=connector.connector_key,
            display_name=connector.display_name,
            health_status=connector.health_status,
            enabled=connector.enabled,
            checked_at=connector.last_health_checked_at,
        )

    async def list_run_history(
        self,
        connector_public_id: UUID,
        params: ListQueryParams | None = None,
    ) -> list[VerificationConnectorRunResponse] | Page[VerificationConnectorRunResponse]:
        connector = await self._require_connector(connector_public_id)
        runs = [self._to_run_response(item) for item in await self._runs.list_for_connector_key(connector.connector_key)]
        if params is None:
            return runs
        return filter_sort_paginate(
            runs,
            params=params,
            search_fields=("connector_key", "status"),
            allowed_sort_fields=("started_at", "completed_at", "status", "execution_time_ms", "retry_count"),
            default_sort_by="started_at",
            force_page_envelope=True,
        )

    def get_implementation(self, connector_key: str) -> VerificationConnectorImplementation | None:
        return self._implementation_by_key.get(connector_key)

    async def _require_connector(self, connector_public_id: UUID) -> VerificationConnector:
        connector = await self._repo.get_by_public_id(connector_public_id)
        if connector is None:
            raise NotFoundError("Verification connector not found")
        return connector

    def _to_response(self, connector: VerificationConnector) -> VerificationConnectorResponse:
        return VerificationConnectorResponse(
            public_id=connector.public_id,
            connector_key=connector.connector_key,
            display_name=connector.display_name,
            connector_type=connector.connector_type,
            supported_capabilities=connector.supported_capabilities,
            supported_registry_types=connector.supported_registry_types,
            version=connector.version,
            health_status=connector.health_status,
            enabled=connector.enabled,
            priority=connector.priority,
            last_health_checked_at=connector.last_health_checked_at,
            created_at=connector.created_at,
            updated_at=connector.updated_at,
        )

    def _to_run_response(self, run: VerificationConnectorRun) -> VerificationConnectorRunResponse:
        return VerificationConnectorRunResponse(
            public_id=run.public_id,
            connector_public_id=run.connector.public_id if run.connector is not None else None,
            connector_key=run.connector_key,
            verification_request_public_id=run.verification_request.public_id,
            registry_record_public_id=run.registry_record.public_id if run.registry_record is not None else None,
            status=run.status,
            started_at=run.started_at,
            completed_at=run.completed_at,
            execution_time_ms=run.execution_time_ms,
            normalized_result=run.normalized_result,
            raw_metadata=run.raw_metadata,
            evidence_references=run.evidence_references,
            error=run.error,
            retry_count=run.retry_count,
            created_at=run.created_at,
            updated_at=run.updated_at,
        )
