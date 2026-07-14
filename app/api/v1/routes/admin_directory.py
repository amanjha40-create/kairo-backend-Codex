"""Read-only Admin reviewer and organization lookup routes."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies.services import get_admin_directory_service
from app.api.dependencies.verification_admin import CurrentUser, require_view_cases
from app.schemas.admin_directory import AdminOrganizationSearchPage, AdminReviewerPage
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
