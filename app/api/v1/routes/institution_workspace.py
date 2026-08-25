"""Institution workspace dashboards and academic verification routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_institution_workspace_service
from app.schemas.institution_workspace import (
    InstitutionDashboardResponse,
    InstitutionPassportSummaryResponse,
    InstitutionVerificationDetailResponse,
    InstitutionVerificationInboxQuery,
    InstitutionVerificationInboxResponse,
)
from app.schemas.pagination import ListQueryParams, Page
from app.schemas.verification_request import (
    VerificationRequestActionPayload,
    VerificationRequestEvidenceResponse,
    VerificationRequestPriorityRequest,
    VerificationRequestTimelineResponse,
)
from app.services.institution_workspace_service import InstitutionWorkspaceService

router = APIRouter(
    prefix="/organizations/{org_public_id}/institution", tags=["institution-workspace"]
)


@router.get("/dashboard", response_model=InstitutionDashboardResponse)
async def get_institution_dashboard(
    org_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[InstitutionWorkspaceService, Depends(get_institution_workspace_service)],
) -> InstitutionDashboardResponse:
    return await service.dashboard(current.id, org_public_id)


@router.get("/verification-requests", response_model=InstitutionVerificationInboxResponse)
async def list_institution_verifications(
    org_public_id: UUID,
    params: Annotated[InstitutionVerificationInboxQuery, Depends()],
    current: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[InstitutionWorkspaceService, Depends(get_institution_workspace_service)],
) -> InstitutionVerificationInboxResponse:
    return await service.list_verifications(current.id, org_public_id, params)


@router.get(
    "/verification-requests/{request_public_id}",
    response_model=InstitutionVerificationDetailResponse,
)
async def get_institution_verification(
    org_public_id: UUID,
    request_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[InstitutionWorkspaceService, Depends(get_institution_workspace_service)],
) -> InstitutionVerificationDetailResponse:
    return await service.verification_detail(current.id, org_public_id, request_public_id)


@router.get(
    "/verification-requests/{request_public_id}/evidence",
    response_model=Page[VerificationRequestEvidenceResponse]
    | list[VerificationRequestEvidenceResponse],
)
async def list_institution_verification_evidence(
    org_public_id: UUID,
    request_public_id: UUID,
    params: Annotated[ListQueryParams, Depends()],
    current: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[InstitutionWorkspaceService, Depends(get_institution_workspace_service)],
) -> Page[VerificationRequestEvidenceResponse] | list[VerificationRequestEvidenceResponse]:
    return await service.list_verification_evidence(
        current.id,
        org_public_id,
        request_public_id,
        params,
    )


@router.get(
    "/verification-requests/{request_public_id}/timeline",
    response_model=VerificationRequestTimelineResponse,
)
async def get_institution_verification_timeline(
    org_public_id: UUID,
    request_public_id: UUID,
    params: Annotated[ListQueryParams, Depends()],
    current: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[InstitutionWorkspaceService, Depends(get_institution_workspace_service)],
) -> VerificationRequestTimelineResponse:
    return await service.get_verification_timeline(
        current.id,
        org_public_id,
        request_public_id,
        params,
    )


@router.post(
    "/verification-requests/{request_public_id}/cancel",
    response_model=InstitutionVerificationDetailResponse,
)
async def cancel_institution_verification(
    org_public_id: UUID,
    request_public_id: UUID,
    payload: VerificationRequestActionPayload,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[InstitutionWorkspaceService, Depends(get_institution_workspace_service)],
) -> InstitutionVerificationDetailResponse:
    return await service.cancel_verification(current.id, org_public_id, request_public_id, payload)


@router.post(
    "/verification-requests/{request_public_id}/priority",
    response_model=InstitutionVerificationDetailResponse,
)
async def change_institution_verification_priority(
    org_public_id: UUID,
    request_public_id: UUID,
    payload: VerificationRequestPriorityRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[InstitutionWorkspaceService, Depends(get_institution_workspace_service)],
) -> InstitutionVerificationDetailResponse:
    return await service.change_priority(
        current.id, org_public_id, request_public_id, payload.priority
    )


@router.get(
    "/people/{person_public_id}/passport-summary", response_model=InstitutionPassportSummaryResponse
)
async def get_institution_passport_summary(
    org_public_id: UUID,
    person_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[InstitutionWorkspaceService, Depends(get_institution_workspace_service)],
) -> InstitutionPassportSummaryResponse:
    return await service.passport_summary(current.id, org_public_id, person_public_id)
