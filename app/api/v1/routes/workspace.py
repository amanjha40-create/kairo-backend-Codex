"""Workspace bootstrap and invitation routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_workspace_service
from app.schemas.workspace import WorkspaceBootstrapResponse, WorkspaceOrganizationInvitationResponse
from app.services.workspace_service import WorkspaceService

router = APIRouter(prefix="/workspace", tags=["workspace"])


@router.get("/bootstrap", response_model=WorkspaceBootstrapResponse)
async def get_workspace_bootstrap(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceBootstrapResponse:
    return await svc.bootstrap(current.id)


@router.get("/invitations", response_model=list[WorkspaceOrganizationInvitationResponse])
async def list_workspace_invitations(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> list[WorkspaceOrganizationInvitationResponse]:
    return await svc.list_invitations(current.id)


@router.post("/invitations/{invitation_public_id}/accept", response_model=WorkspaceOrganizationInvitationResponse)
async def accept_workspace_invitation(
    invitation_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceOrganizationInvitationResponse:
    return await svc.accept_invitation(current.id, invitation_public_id)


@router.post("/invitations/{invitation_public_id}/decline", response_model=WorkspaceOrganizationInvitationResponse)
async def decline_workspace_invitation(
    invitation_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceOrganizationInvitationResponse:
    return await svc.decline_invitation(current.id, invitation_public_id)
