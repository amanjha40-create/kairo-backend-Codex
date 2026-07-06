"""Organization and membership management routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_organization_service
from app.schemas.organization import (
    OrganizationCreateRequest,
    OrganizationMemberCreateRequest,
    OrganizationMemberResponse,
    OrganizationMemberUpdateRequest,
    OrganizationResponse,
)
from app.services.organization_service import OrganizationService

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    payload: OrganizationCreateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[OrganizationService, Depends(get_organization_service)],
) -> OrganizationResponse:
    return await svc.create_organization(current.id, payload)


@router.get("/me", response_model=list[OrganizationResponse])
async def list_my_organizations(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[OrganizationService, Depends(get_organization_service)],
) -> list[OrganizationResponse]:
    return await svc.list_my_organizations(current.id)


@router.get("/{org_public_id}", response_model=OrganizationResponse)
async def get_organization(
    org_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[OrganizationService, Depends(get_organization_service)],
) -> OrganizationResponse:
    return await svc.get_organization(current.id, org_public_id)


@router.post("/{org_public_id}/members", response_model=OrganizationMemberResponse, status_code=status.HTTP_201_CREATED)
async def add_organization_member(
    org_public_id: UUID,
    payload: OrganizationMemberCreateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[OrganizationService, Depends(get_organization_service)],
) -> OrganizationMemberResponse:
    return await svc.add_member(current.id, org_public_id, payload)


@router.get("/{org_public_id}/members", response_model=list[OrganizationMemberResponse])
async def list_organization_members(
    org_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[OrganizationService, Depends(get_organization_service)],
) -> list[OrganizationMemberResponse]:
    return await svc.list_members(current.id, org_public_id)


@router.patch("/{org_public_id}/members/{member_public_id}", response_model=OrganizationMemberResponse)
async def update_organization_member(
    org_public_id: UUID,
    member_public_id: UUID,
    payload: OrganizationMemberUpdateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[OrganizationService, Depends(get_organization_service)],
) -> OrganizationMemberResponse:
    return await svc.update_member_role(current.id, org_public_id, member_public_id, payload)
