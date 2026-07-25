"""Organization and membership management routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_organization_service
from app.schemas.organization import (
    OrganizationCreateRequest,
    OrganizationInvitationCreateRequest,
    OrganizationInvitationResponse,
    OrganizationMemberCreateRequest,
    OrganizationMemberResponse,
    OrganizationMemberSuspendRequest,
    OrganizationMemberUpdateRequest,
    OrganizationOwnershipTransferResponse,
    OrganizationResponse,
    OrganizationUpdateRequest,
)
from app.schemas.pagination import ListQueryParams, Page
from app.services.organization_service import OrganizationService

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    payload: OrganizationCreateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[OrganizationService, Depends(get_organization_service)],
) -> OrganizationResponse:
    return await svc.create_organization(current.id, payload)


@router.post(
    "/onboarding/complete", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED
)
async def complete_organization_onboarding(
    payload: OrganizationCreateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[OrganizationService, Depends(get_organization_service)],
) -> OrganizationResponse:
    return await svc.complete_onboarding(current.id, payload)


@router.get("/me", response_model=Page[OrganizationResponse] | list[OrganizationResponse])
async def list_my_organizations(
    params: Annotated[ListQueryParams, Depends()],
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[OrganizationService, Depends(get_organization_service)],
) -> Page[OrganizationResponse] | list[OrganizationResponse]:
    return await svc.list_my_organizations(current.id, params)


@router.get("/{org_public_id}", response_model=OrganizationResponse)
async def get_organization(
    org_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[OrganizationService, Depends(get_organization_service)],
) -> OrganizationResponse:
    return await svc.get_organization(current.id, org_public_id)


@router.patch("/{org_public_id}", response_model=OrganizationResponse)
async def update_organization(
    org_public_id: UUID,
    payload: OrganizationUpdateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[OrganizationService, Depends(get_organization_service)],
) -> OrganizationResponse:
    return await svc.update_organization(current.id, org_public_id, payload)


@router.post(
    "/{org_public_id}/members",
    response_model=OrganizationMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_organization_member(
    org_public_id: UUID,
    payload: OrganizationMemberCreateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[OrganizationService, Depends(get_organization_service)],
) -> OrganizationMemberResponse:
    return await svc.add_member(current.id, org_public_id, payload)


@router.post(
    "/{org_public_id}/invitations",
    response_model=OrganizationInvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_organization_invitation(
    org_public_id: UUID,
    payload: OrganizationInvitationCreateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[OrganizationService, Depends(get_organization_service)],
) -> OrganizationInvitationResponse:
    return await svc.create_invitation(current.id, org_public_id, payload)


@router.get(
    "/{org_public_id}/invitations",
    response_model=Page[OrganizationInvitationResponse] | list[OrganizationInvitationResponse],
)
async def list_organization_invitations(
    org_public_id: UUID,
    params: Annotated[ListQueryParams, Depends()],
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[OrganizationService, Depends(get_organization_service)],
) -> Page[OrganizationInvitationResponse] | list[OrganizationInvitationResponse]:
    return await svc.list_invitations(current.id, org_public_id, params)


@router.post(
    "/{org_public_id}/invitations/{invitation_public_id}/resend",
    response_model=OrganizationInvitationResponse,
)
async def resend_organization_invitation(
    org_public_id: UUID,
    invitation_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[OrganizationService, Depends(get_organization_service)],
) -> OrganizationInvitationResponse:
    return await svc.resend_invitation(current.id, org_public_id, invitation_public_id)


@router.post(
    "/{org_public_id}/invitations/{invitation_public_id}/cancel",
    response_model=OrganizationInvitationResponse,
)
async def cancel_organization_invitation(
    org_public_id: UUID,
    invitation_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[OrganizationService, Depends(get_organization_service)],
) -> OrganizationInvitationResponse:
    return await svc.cancel_invitation(current.id, org_public_id, invitation_public_id)


@router.get(
    "/{org_public_id}/members",
    response_model=Page[OrganizationMemberResponse] | list[OrganizationMemberResponse],
)
async def list_organization_members(
    org_public_id: UUID,
    params: Annotated[ListQueryParams, Depends()],
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[OrganizationService, Depends(get_organization_service)],
) -> Page[OrganizationMemberResponse] | list[OrganizationMemberResponse]:
    return await svc.list_members(current.id, org_public_id, params)


@router.patch(
    "/{org_public_id}/members/{member_public_id}", response_model=OrganizationMemberResponse
)
async def update_organization_member(
    org_public_id: UUID,
    member_public_id: UUID,
    payload: OrganizationMemberUpdateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[OrganizationService, Depends(get_organization_service)],
) -> OrganizationMemberResponse:
    return await svc.update_member_role(current.id, org_public_id, member_public_id, payload)


@router.post(
    "/{org_public_id}/members/{member_public_id}/suspend", response_model=OrganizationMemberResponse
)
async def suspend_organization_member(
    org_public_id: UUID,
    member_public_id: UUID,
    payload: OrganizationMemberSuspendRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[OrganizationService, Depends(get_organization_service)],
) -> OrganizationMemberResponse:
    return await svc.suspend_member(current.id, org_public_id, member_public_id, payload)


@router.post(
    "/{org_public_id}/members/{member_public_id}/restore", response_model=OrganizationMemberResponse
)
async def restore_organization_member(
    org_public_id: UUID,
    member_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[OrganizationService, Depends(get_organization_service)],
) -> OrganizationMemberResponse:
    return await svc.restore_member(current.id, org_public_id, member_public_id)


@router.delete(
    "/{org_public_id}/members/{member_public_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_organization_member(
    org_public_id: UUID,
    member_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[OrganizationService, Depends(get_organization_service)],
) -> Response:
    await svc.remove_member(current.id, org_public_id, member_public_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{org_public_id}/members/{member_public_id}/transfer-ownership",
    response_model=OrganizationOwnershipTransferResponse,
)
async def transfer_organization_ownership(
    org_public_id: UUID,
    member_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[OrganizationService, Depends(get_organization_service)],
) -> OrganizationOwnershipTransferResponse:
    return await svc.transfer_ownership(current.id, org_public_id, member_public_id)
