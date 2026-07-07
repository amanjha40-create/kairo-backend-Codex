"""Internal verification connector administration routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.dependencies.services import get_connector_registry_service
from app.api.dependencies.verification_admin import CurrentUser, require_reviewer, require_view_cases
from app.schemas.pagination import ListQueryParams, Page
from app.schemas.verification_connector import (
    VerificationConnectorHealthResponse,
    VerificationConnectorResponse,
    VerificationConnectorRunResponse,
    VerificationConnectorUpdateRequest,
)
from app.services.connector_registry_service import ConnectorRegistryService

admin_router = APIRouter(prefix="/admin/verification-connectors", tags=["verification-connectors"])


@admin_router.get("", response_model=Page[VerificationConnectorResponse])
async def list_verification_connectors(
    params: Annotated[ListQueryParams, Depends()],
    _: Annotated[CurrentUser, Depends(require_view_cases)],
    svc: Annotated[ConnectorRegistryService, Depends(get_connector_registry_service)],
) -> Page[VerificationConnectorResponse]:
    result = await svc.list_connectors(params)
    if isinstance(result, list):
        raise RuntimeError("Verification connector list must return a page envelope")
    return result


@admin_router.get("/{connector_public_id}", response_model=VerificationConnectorResponse)
async def get_verification_connector(
    connector_public_id: UUID,
    _: Annotated[CurrentUser, Depends(require_view_cases)],
    svc: Annotated[ConnectorRegistryService, Depends(get_connector_registry_service)],
) -> VerificationConnectorResponse:
    return await svc.get_detail(connector_public_id)


@admin_router.patch("/{connector_public_id}", response_model=VerificationConnectorResponse)
async def update_verification_connector(
    connector_public_id: UUID,
    payload: VerificationConnectorUpdateRequest,
    _: Annotated[CurrentUser, Depends(require_reviewer)],
    svc: Annotated[ConnectorRegistryService, Depends(get_connector_registry_service)],
) -> VerificationConnectorResponse:
    return await svc.update_connector(connector_public_id, payload)


@admin_router.get("/{connector_public_id}/health", response_model=VerificationConnectorHealthResponse)
async def get_verification_connector_health(
    connector_public_id: UUID,
    _: Annotated[CurrentUser, Depends(require_view_cases)],
    svc: Annotated[ConnectorRegistryService, Depends(get_connector_registry_service)],
) -> VerificationConnectorHealthResponse:
    return await svc.get_health(connector_public_id)


@admin_router.get("/{connector_public_id}/runs", response_model=Page[VerificationConnectorRunResponse])
async def list_verification_connector_runs(
    connector_public_id: UUID,
    params: Annotated[ListQueryParams, Depends()],
    _: Annotated[CurrentUser, Depends(require_view_cases)],
    svc: Annotated[ConnectorRegistryService, Depends(get_connector_registry_service)],
) -> Page[VerificationConnectorRunResponse]:
    result = await svc.list_run_history(connector_public_id, params)
    if isinstance(result, list):
        raise RuntimeError("Verification connector run history must return a page envelope")
    return result
