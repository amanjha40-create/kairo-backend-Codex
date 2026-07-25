"""Trust invitation routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_trust_invitation_service
from app.schemas.pagination import ListQueryParams, Page
from app.schemas.trust_invitation import (
    TrustInvitationAcceptResponse,
    TrustInvitationCreateRequest,
    TrustInvitationCreateResponse,
    TrustInvitationDetailResponse,
    TrustInvitationPublicLookupResponse,
    TrustInvitationResponse,
    TrustInvitationSummaryResponse,
)
from app.services.trust_invitation_service import TrustInvitationService

router = APIRouter(tags=["trust-invitations"])

org_router = APIRouter(prefix="/organizations/{org_public_id}/trust-invitations", tags=["trust-invitations"])


@org_router.post("", response_model=TrustInvitationCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_trust_invitation(
    org_public_id: UUID,
    payload: TrustInvitationCreateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[TrustInvitationService, Depends(get_trust_invitation_service)],
) -> TrustInvitationCreateResponse:
    return await svc.create(current.id, org_public_id, payload)


@org_router.get("/summary", response_model=TrustInvitationSummaryResponse)
async def get_trust_invitation_summary(
    org_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[TrustInvitationService, Depends(get_trust_invitation_service)],
) -> TrustInvitationSummaryResponse:
    return await svc.get_summary(current.id, org_public_id)


@org_router.get("", response_model=Page[TrustInvitationResponse] | list[TrustInvitationResponse])
async def list_trust_invitations(
    org_public_id: UUID,
    params: Annotated[ListQueryParams, Depends()],
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[TrustInvitationService, Depends(get_trust_invitation_service)],
) -> Page[TrustInvitationResponse] | list[TrustInvitationResponse]:
    return await svc.list_for_organization(current.id, org_public_id, params)


@router.get("/trust-invitations/by-id/{trust_invitation_public_id}", response_model=TrustInvitationDetailResponse)
async def get_trust_invitation_detail(
    trust_invitation_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[TrustInvitationService, Depends(get_trust_invitation_service)],
) -> TrustInvitationDetailResponse:
    return await svc.get_detail(current.id, trust_invitation_public_id)


@router.post("/trust-invitations/{trust_invitation_public_id}/send", response_model=TrustInvitationDetailResponse)
async def send_trust_invitation(
    trust_invitation_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[TrustInvitationService, Depends(get_trust_invitation_service)],
) -> TrustInvitationDetailResponse:
    return await svc.send(current.id, trust_invitation_public_id)


@router.post("/trust-invitations/{trust_invitation_public_id}/resend", response_model=TrustInvitationDetailResponse)
async def resend_trust_invitation(
    trust_invitation_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[TrustInvitationService, Depends(get_trust_invitation_service)],
) -> TrustInvitationDetailResponse:
    return await svc.resend(current.id, trust_invitation_public_id)


@router.delete("/trust-invitations/{trust_invitation_public_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trust_invitation(
    trust_invitation_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[TrustInvitationService, Depends(get_trust_invitation_service)],
) -> Response:
    await svc.delete(current.id, trust_invitation_public_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/trust-invitations/{token}", response_model=TrustInvitationPublicLookupResponse)
async def get_trust_invitation(
    token: str,
    svc: Annotated[TrustInvitationService, Depends(get_trust_invitation_service)],
) -> TrustInvitationPublicLookupResponse:
    return await svc.get_public_by_token(token)


@router.post("/trust-invitations/{token}/accept", response_model=TrustInvitationAcceptResponse)
async def accept_trust_invitation(
    token: str,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[TrustInvitationService, Depends(get_trust_invitation_service)],
) -> TrustInvitationAcceptResponse:
    return await svc.accept(token, current.id, current.email)


@router.post("/trust-invitations/{trust_invitation_public_id}/cancel", response_model=TrustInvitationResponse)
async def cancel_trust_invitation(
    trust_invitation_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[TrustInvitationService, Depends(get_trust_invitation_service)],
) -> TrustInvitationResponse:
    return await svc.cancel(current.id, trust_invitation_public_id)
