"""Read-only Admin reviewer, organization, and candidate lookup routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.dependencies.services import get_admin_directory_service
from app.api.dependencies.verification_admin import (
    CurrentUser,
    require_user_manager,
    require_view_cases,
)
from app.schemas.admin_directory import (
    AdminOrganizationSearchPage,
    AdminReviewerPage,
    AdminUserDetailResponse,
    AdminUserPage,
)
from app.schemas.pagination import ListQueryParams
from app.services.admin_directory_service import AdminDirectoryService

router = APIRouter(prefix="/admin", tags=["admin-review-workflow"])


@router.get("/verification-reviewers", response_model=AdminReviewerPage)
async def list_verification_reviewers(
    params: Annotated[ListQueryParams, Depends()],
    _: Annotated[CurrentUser, Depends(require_view_cases)],
    svc: Annotated[AdminDirectoryService, Depends(get_admin_directory_service)],
) -> AdminReviewerPage:
    return await svc.list_reviewers(params)


@router.get("/organizations/search", response_model=AdminOrganizationSearchPage)
async def search_admin_organizations(
    params: Annotated[ListQueryParams, Depends()],
    _: Annotated[CurrentUser, Depends(require_view_cases)],
    svc: Annotated[AdminDirectoryService, Depends(get_admin_directory_service)],
) -> AdminOrganizationSearchPage:
    return await svc.search_organizations(params)


@router.get("/users", response_model=AdminUserPage)
async def list_admin_users(
    params: Annotated[ListQueryParams, Depends()],
    _: Annotated[CurrentUser, Depends(require_user_manager)],
    svc: Annotated[AdminDirectoryService, Depends(get_admin_directory_service)],
) -> AdminUserPage:
    return await svc.list_users(params)


@router.get("/users/{user_public_id}", response_model=AdminUserDetailResponse)
async def get_admin_user_detail(
    user_public_id: UUID,
    _: Annotated[CurrentUser, Depends(require_user_manager)],
    svc: Annotated[AdminDirectoryService, Depends(get_admin_directory_service)],
) -> AdminUserDetailResponse:
    return await svc.get_user_detail(user_public_id)
