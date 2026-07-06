"""Verification request engine routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_verification_request_service
from app.schemas.verification_request import (
    VerificationRequestActionPayload,
    VerificationRequestCreateRequest,
    VerificationRequestResponse,
    VerificationRequestTimelineResponse,
)
from app.services.verification_request_service import VerificationRequestService

router = APIRouter(tags=["verification-requests"])
org_router = APIRouter(prefix="/organizations/{organization_public_id}/verification-requests", tags=["verification-requests"])


@org_router.post("", response_model=VerificationRequestResponse, status_code=status.HTTP_201_CREATED)
async def create_verification_request(
    organization_public_id: UUID,
    payload: VerificationRequestCreateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[VerificationRequestService, Depends(get_verification_request_service)],
) -> VerificationRequestResponse:
    return await svc.create(current.id, organization_public_id, payload)


@org_router.get("", response_model=list[VerificationRequestResponse])
async def list_verification_requests(
    organization_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[VerificationRequestService, Depends(get_verification_request_service)],
) -> list[VerificationRequestResponse]:
    return await svc.list_for_organization(current.id, organization_public_id)


@router.get("/verification-requests/{verification_request_public_id}", response_model=VerificationRequestResponse)
async def get_verification_request(
    verification_request_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[VerificationRequestService, Depends(get_verification_request_service)],
) -> VerificationRequestResponse:
    return await svc.get_detail(current.id, current.email, verification_request_public_id)


@router.post("/verification-requests/{verification_request_public_id}/accept", response_model=VerificationRequestResponse)
async def accept_verification_request(
    verification_request_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[VerificationRequestService, Depends(get_verification_request_service)],
) -> VerificationRequestResponse:
    return await svc.accept(current.id, current.email, verification_request_public_id)


@router.post("/verification-requests/{verification_request_public_id}/request-information", response_model=VerificationRequestResponse)
async def request_verification_information(
    verification_request_public_id: UUID,
    payload: VerificationRequestActionPayload,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[VerificationRequestService, Depends(get_verification_request_service)],
) -> VerificationRequestResponse:
    return await svc.request_information(current.id, verification_request_public_id, payload)


@router.post("/verification-requests/{verification_request_public_id}/verify", response_model=VerificationRequestResponse)
async def verify_verification_request(
    verification_request_public_id: UUID,
    payload: VerificationRequestActionPayload,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[VerificationRequestService, Depends(get_verification_request_service)],
) -> VerificationRequestResponse:
    return await svc.verify(current.id, verification_request_public_id, payload)


@router.post("/verification-requests/{verification_request_public_id}/reject", response_model=VerificationRequestResponse)
async def reject_verification_request(
    verification_request_public_id: UUID,
    payload: VerificationRequestActionPayload,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[VerificationRequestService, Depends(get_verification_request_service)],
) -> VerificationRequestResponse:
    return await svc.reject(current.id, verification_request_public_id, payload)


@router.post("/verification-requests/{verification_request_public_id}/cancel", response_model=VerificationRequestResponse)
async def cancel_verification_request(
    verification_request_public_id: UUID,
    payload: VerificationRequestActionPayload,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[VerificationRequestService, Depends(get_verification_request_service)],
) -> VerificationRequestResponse:
    return await svc.cancel(current.id, verification_request_public_id, payload)


@router.get("/verification-requests/{verification_request_public_id}/timeline", response_model=VerificationRequestTimelineResponse)
async def get_verification_request_timeline(
    verification_request_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[VerificationRequestService, Depends(get_verification_request_service)],
) -> VerificationRequestTimelineResponse:
    return await svc.get_timeline(current.id, current.email, verification_request_public_id)
