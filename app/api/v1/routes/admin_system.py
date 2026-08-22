"""Admin System Operations routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies.services import get_admin_system_service
from app.api.dependencies.verification_admin import (
    CurrentUser,
    require_system_operations_incident_create,
    require_system_operations_incident_update,
    require_system_operations_read,
    require_system_operations_retry,
)
from app.schemas.admin_system import (
    AdminSystemActivityItemResponse,
    AdminSystemActivityParams,
    AdminSystemCreateIncidentRequest,
    AdminSystemFailuresResponse,
    AdminSystemIncidentDetailResponse,
    AdminSystemIncidentListItemResponse,
    AdminSystemIncidentListParams,
    AdminSystemResolveIncidentRequest,
    AdminSystemRetryResponse,
    AdminSystemRuntimeResponse,
    AdminSystemStatusResponse,
    AdminSystemUpdateIncidentRequest,
    AdminSystemWorkloadsResponse,
)
from app.schemas.pagination import Page
from app.services.admin_system_service import AdminSystemService

router = APIRouter(prefix="/admin/system", tags=["admin-system"])


@router.get("/status", response_model=AdminSystemStatusResponse)
async def get_admin_system_status(
    _: Annotated[object, Depends(require_system_operations_read)],
    svc: Annotated[AdminSystemService, Depends(get_admin_system_service)],
) -> AdminSystemStatusResponse:
    return await svc.get_status()


@router.get("/runtime", response_model=AdminSystemRuntimeResponse)
async def get_admin_system_runtime(
    _: Annotated[object, Depends(require_system_operations_read)],
    svc: Annotated[AdminSystemService, Depends(get_admin_system_service)],
) -> AdminSystemRuntimeResponse:
    return await svc.get_runtime()


@router.get("/workloads", response_model=AdminSystemWorkloadsResponse)
async def get_admin_system_workloads(
    _: Annotated[object, Depends(require_system_operations_read)],
    svc: Annotated[AdminSystemService, Depends(get_admin_system_service)],
) -> AdminSystemWorkloadsResponse:
    return await svc.get_workloads()


@router.get("/failures", response_model=AdminSystemFailuresResponse)
async def get_admin_system_failures(
    _: Annotated[object, Depends(require_system_operations_read)],
    svc: Annotated[AdminSystemService, Depends(get_admin_system_service)],
) -> AdminSystemFailuresResponse:
    return await svc.get_failures()


@router.get("/activity", response_model=Page[AdminSystemActivityItemResponse])
async def list_admin_system_activity(
    params: Annotated[AdminSystemActivityParams, Depends()],
    _: Annotated[object, Depends(require_system_operations_read)],
    svc: Annotated[AdminSystemService, Depends(get_admin_system_service)],
) -> Page[AdminSystemActivityItemResponse]:
    return await svc.list_activity(params)


@router.get("/incidents", response_model=Page[AdminSystemIncidentListItemResponse])
async def list_admin_system_incidents(
    params: Annotated[AdminSystemIncidentListParams, Depends()],
    _: Annotated[object, Depends(require_system_operations_read)],
    svc: Annotated[AdminSystemService, Depends(get_admin_system_service)],
) -> Page[AdminSystemIncidentListItemResponse]:
    return await svc.list_incidents(params)


@router.get("/incidents/{incident_public_id}", response_model=AdminSystemIncidentDetailResponse)
async def get_admin_system_incident(
    incident_public_id: UUID,
    _: Annotated[object, Depends(require_system_operations_read)],
    svc: Annotated[AdminSystemService, Depends(get_admin_system_service)],
) -> AdminSystemIncidentDetailResponse:
    return await svc.get_incident(incident_public_id)


@router.post(
    "/incidents",
    response_model=AdminSystemIncidentDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_admin_system_incident(
    payload: AdminSystemCreateIncidentRequest,
    current: Annotated[CurrentUser, Depends(require_system_operations_incident_create)],
    svc: Annotated[AdminSystemService, Depends(get_admin_system_service)],
) -> AdminSystemIncidentDetailResponse:
    return await svc.create_incident(current, payload)


@router.patch("/incidents/{incident_public_id}", response_model=AdminSystemIncidentDetailResponse)
async def update_admin_system_incident(
    incident_public_id: UUID,
    payload: AdminSystemUpdateIncidentRequest,
    current: Annotated[CurrentUser, Depends(require_system_operations_incident_update)],
    svc: Annotated[AdminSystemService, Depends(get_admin_system_service)],
) -> AdminSystemIncidentDetailResponse:
    return await svc.update_incident(current, incident_public_id, payload)


@router.post(
    "/incidents/{incident_public_id}/resolve",
    response_model=AdminSystemIncidentDetailResponse,
)
async def resolve_admin_system_incident(
    incident_public_id: UUID,
    payload: AdminSystemResolveIncidentRequest,
    current: Annotated[CurrentUser, Depends(require_system_operations_incident_update)],
    svc: Annotated[AdminSystemService, Depends(get_admin_system_service)],
) -> AdminSystemIncidentDetailResponse:
    return await svc.resolve_incident(current, incident_public_id, payload)


@router.post(
    "/retries/communications/{communication_public_id}",
    response_model=AdminSystemRetryResponse,
)
async def retry_admin_system_communication(
    communication_public_id: UUID,
    current: Annotated[CurrentUser, Depends(require_system_operations_retry)],
    svc: Annotated[AdminSystemService, Depends(get_admin_system_service)],
) -> AdminSystemRetryResponse:
    return await svc.retry_failed_communication(communication_public_id, actor_user_id=current.id)
