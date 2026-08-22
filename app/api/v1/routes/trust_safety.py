"""Admin Trust & Safety routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

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
from app.schemas.pagination import Page
from app.schemas.trust_safety import (
    RiskSignalResponse,
    TrustSafetyAddNoteRequest,
    TrustSafetyAssignInvestigationRequest,
    TrustSafetyCreateInvestigationRequest,
    TrustSafetyDismissRequest,
    TrustSafetyInvestigationAssigneeResponse,
    TrustSafetyInvestigationDetailResponse,
    TrustSafetyInvestigationListItemResponse,
    TrustSafetyInvestigationNoteResponse,
    TrustSafetyListParams,
    TrustSafetyOverviewSummaryResponse,
    TrustSafetyResolveRequest,
    TrustSafetyUpdateSeverityRequest,
    TrustSafetyUpdateStatusRequest,
)
from app.services.trust_safety_service import TrustSafetyService

router = APIRouter(prefix="/admin/trust-safety", tags=["trust-safety"])


@router.get("/signals", response_model=Page[RiskSignalResponse])
async def list_trust_safety_signals(
    params: Annotated[TrustSafetyListParams, Depends()],
    _: Annotated[CurrentUser, Depends(require_trust_safety_read)],
    svc: Annotated[TrustSafetyService, Depends(get_trust_safety_service)],
) -> Page[RiskSignalResponse]:
    return await svc.list_signals(params)


@router.get("/assignees", response_model=Page[TrustSafetyInvestigationAssigneeResponse])
async def list_trust_safety_assignees(
    params: Annotated[TrustSafetyListParams, Depends()],
    _: Annotated[CurrentUser, Depends(require_trust_safety_read)],
    svc: Annotated[TrustSafetyService, Depends(get_trust_safety_service)],
) -> Page[TrustSafetyInvestigationAssigneeResponse]:
    return await svc.list_assignees(params)


@router.get("/investigations", response_model=Page[TrustSafetyInvestigationListItemResponse])
async def list_trust_safety_investigations(
    params: Annotated[TrustSafetyListParams, Depends()],
    _: Annotated[CurrentUser, Depends(require_trust_safety_read)],
    svc: Annotated[TrustSafetyService, Depends(get_trust_safety_service)],
) -> Page[TrustSafetyInvestigationListItemResponse]:
    return await svc.list_investigations(params)


@router.get("/summary", response_model=TrustSafetyOverviewSummaryResponse)
async def get_trust_safety_summary(
    _: Annotated[CurrentUser, Depends(require_trust_safety_read)],
    svc: Annotated[TrustSafetyService, Depends(get_trust_safety_service)],
) -> TrustSafetyOverviewSummaryResponse:
    return await svc.summary()


@router.post(
    "/investigations",
    response_model=TrustSafetyInvestigationDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_trust_safety_investigation(
    payload: TrustSafetyCreateInvestigationRequest,
    current: Annotated[CurrentUser, Depends(require_trust_safety_create)],
    svc: Annotated[TrustSafetyService, Depends(get_trust_safety_service)],
) -> TrustSafetyInvestigationDetailResponse:
    return await svc.create_investigation(current, payload)


@router.get(
    "/investigations/{investigation_public_id}",
    response_model=TrustSafetyInvestigationDetailResponse,
)
async def get_trust_safety_investigation(
    investigation_public_id: UUID,
    current: Annotated[CurrentUser, Depends(require_trust_safety_read)],
    svc: Annotated[TrustSafetyService, Depends(get_trust_safety_service)],
) -> TrustSafetyInvestigationDetailResponse:
    return await svc.get_detail(current, investigation_public_id)


@router.post(
    "/investigations/{investigation_public_id}/assign",
    response_model=TrustSafetyInvestigationDetailResponse,
)
async def assign_trust_safety_investigation(
    investigation_public_id: UUID,
    payload: TrustSafetyAssignInvestigationRequest,
    current: Annotated[CurrentUser, Depends(require_trust_safety_assign)],
    svc: Annotated[TrustSafetyService, Depends(get_trust_safety_service)],
) -> TrustSafetyInvestigationDetailResponse:
    return await svc.assign(current, investigation_public_id, payload)


@router.post(
    "/investigations/{investigation_public_id}/severity",
    response_model=TrustSafetyInvestigationDetailResponse,
)
async def update_trust_safety_investigation_severity(
    investigation_public_id: UUID,
    payload: TrustSafetyUpdateSeverityRequest,
    current: Annotated[CurrentUser, Depends(require_trust_safety_update_severity)],
    svc: Annotated[TrustSafetyService, Depends(get_trust_safety_service)],
) -> TrustSafetyInvestigationDetailResponse:
    return await svc.update_severity(current, investigation_public_id, payload)


@router.post(
    "/investigations/{investigation_public_id}/notes",
    response_model=TrustSafetyInvestigationNoteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_trust_safety_investigation_note(
    investigation_public_id: UUID,
    payload: TrustSafetyAddNoteRequest,
    current: Annotated[CurrentUser, Depends(require_trust_safety_note)],
    svc: Annotated[TrustSafetyService, Depends(get_trust_safety_service)],
) -> TrustSafetyInvestigationNoteResponse:
    return await svc.add_note(current, investigation_public_id, payload)


@router.post(
    "/investigations/{investigation_public_id}/status",
    response_model=TrustSafetyInvestigationDetailResponse,
)
async def update_trust_safety_investigation_status(
    investigation_public_id: UUID,
    payload: TrustSafetyUpdateStatusRequest,
    current: Annotated[CurrentUser, Depends(require_trust_safety_resolve)],
    svc: Annotated[TrustSafetyService, Depends(get_trust_safety_service)],
) -> TrustSafetyInvestigationDetailResponse:
    return await svc.update_status(current, investigation_public_id, payload)


@router.post(
    "/investigations/{investigation_public_id}/resolve",
    response_model=TrustSafetyInvestigationDetailResponse,
)
async def resolve_trust_safety_investigation(
    investigation_public_id: UUID,
    payload: TrustSafetyResolveRequest,
    current: Annotated[CurrentUser, Depends(require_trust_safety_resolve)],
    svc: Annotated[TrustSafetyService, Depends(get_trust_safety_service)],
) -> TrustSafetyInvestigationDetailResponse:
    return await svc.resolve(current, investigation_public_id, payload)


@router.post(
    "/investigations/{investigation_public_id}/dismiss",
    response_model=TrustSafetyInvestigationDetailResponse,
)
async def dismiss_trust_safety_investigation(
    investigation_public_id: UUID,
    payload: TrustSafetyDismissRequest,
    current: Annotated[CurrentUser, Depends(require_trust_safety_resolve)],
    svc: Annotated[TrustSafetyService, Depends(get_trust_safety_service)],
) -> TrustSafetyInvestigationDetailResponse:
    return await svc.dismiss(current, investigation_public_id, payload)
