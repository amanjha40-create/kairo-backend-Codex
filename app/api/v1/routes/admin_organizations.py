"""Admin-only organization search and Company 360 routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.dependencies.services import get_admin_organization_service
from app.api.dependencies.verification_admin import CurrentUser, require_user_reader
from app.schemas.admin_organization import (
    AdminOrganizationActivityPage,
    AdminOrganizationDetailResponse,
    AdminOrganizationListParams,
    AdminOrganizationOverviewResponse,
    AdminOrganizationPage,
    AdminOrganizationPeoplePage,
    AdminOrganizationTeamPage,
    AdminOrganizationVerificationListParams,
    AdminOrganizationVerificationPage,
)
from app.schemas.pagination import ListQueryParams
from app.services.admin_organization_service import AdminOrganizationService

router = APIRouter(prefix="/admin/organizations", tags=["admin-organizations"])


@router.get("", response_model=AdminOrganizationPage)
async def list_admin_organizations(
    params: Annotated[AdminOrganizationListParams, Depends()],
    _: Annotated[CurrentUser, Depends(require_user_reader)],
    svc: Annotated[AdminOrganizationService, Depends(get_admin_organization_service)],
) -> AdminOrganizationPage:
    return await svc.list_organizations(params)


@router.get("/{organization_public_id}", response_model=AdminOrganizationDetailResponse)
async def get_admin_organization(
    organization_public_id: UUID,
    _: Annotated[CurrentUser, Depends(require_user_reader)],
    svc: Annotated[AdminOrganizationService, Depends(get_admin_organization_service)],
) -> AdminOrganizationDetailResponse:
    return await svc.get_organization(organization_public_id)


@router.get(
    "/{organization_public_id}/overview",
    response_model=AdminOrganizationOverviewResponse,
)
async def get_admin_organization_overview(
    organization_public_id: UUID,
    _: Annotated[CurrentUser, Depends(require_user_reader)],
    svc: Annotated[AdminOrganizationService, Depends(get_admin_organization_service)],
) -> AdminOrganizationOverviewResponse:
    return await svc.get_overview(organization_public_id)


@router.get("/{organization_public_id}/people", response_model=AdminOrganizationPeoplePage)
async def list_admin_organization_people(
    organization_public_id: UUID,
    params: Annotated[ListQueryParams, Depends()],
    _: Annotated[CurrentUser, Depends(require_user_reader)],
    svc: Annotated[AdminOrganizationService, Depends(get_admin_organization_service)],
) -> AdminOrganizationPeoplePage:
    return await svc.list_people(organization_public_id, params)


@router.get(
    "/{organization_public_id}/verifications",
    response_model=AdminOrganizationVerificationPage,
)
async def list_admin_organization_verifications(
    organization_public_id: UUID,
    params: Annotated[AdminOrganizationVerificationListParams, Depends()],
    _: Annotated[CurrentUser, Depends(require_user_reader)],
    svc: Annotated[AdminOrganizationService, Depends(get_admin_organization_service)],
) -> AdminOrganizationVerificationPage:
    return await svc.list_verifications(organization_public_id, params)


@router.get("/{organization_public_id}/team", response_model=AdminOrganizationTeamPage)
async def list_admin_organization_team(
    organization_public_id: UUID,
    params: Annotated[ListQueryParams, Depends()],
    _: Annotated[CurrentUser, Depends(require_user_reader)],
    svc: Annotated[AdminOrganizationService, Depends(get_admin_organization_service)],
) -> AdminOrganizationTeamPage:
    return await svc.list_team(organization_public_id, params)


@router.get("/{organization_public_id}/activity", response_model=AdminOrganizationActivityPage)
async def list_admin_organization_activity(
    organization_public_id: UUID,
    params: Annotated[ListQueryParams, Depends()],
    _: Annotated[CurrentUser, Depends(require_user_reader)],
    svc: Annotated[AdminOrganizationService, Depends(get_admin_organization_service)],
) -> AdminOrganizationActivityPage:
    return await svc.list_activity(organization_public_id, params)
