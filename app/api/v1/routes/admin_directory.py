"""Read-only Admin reviewer, organization, and candidate lookup routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies.services import get_admin_directory_service
from app.api.dependencies.verification_admin import (
    CurrentUser,
    require_user_account_manager,
    require_user_note_manager,
    require_user_reader,
    require_user_security_manager,
    require_view_cases,
)
from app.schemas.admin_directory import (
    AdminOrganizationSearchPage,
    AdminReviewerPage,
    AdminUserDetailResponse,
    AdminUserNoteCreateRequest,
    AdminUserNoteResponse,
    AdminUserPage,
    AdminUserRestoreRequest,
    AdminUserSuspendRequest,
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
    _: Annotated[CurrentUser, Depends(require_user_reader)],
    svc: Annotated[AdminDirectoryService, Depends(get_admin_directory_service)],
) -> AdminUserPage:
    return await svc.list_users(params)


@router.get("/users/{user_public_id}", response_model=AdminUserDetailResponse)
async def get_admin_user_detail(
    user_public_id: UUID,
    current: Annotated[CurrentUser, Depends(require_user_reader)],
    svc: Annotated[AdminDirectoryService, Depends(get_admin_directory_service)],
) -> AdminUserDetailResponse:
    return await svc.get_user_detail(current, user_public_id)


@router.post(
    "/users/{user_public_id}/notes",
    response_model=AdminUserNoteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_admin_user_note(
    user_public_id: UUID,
    payload: AdminUserNoteCreateRequest,
    current: Annotated[CurrentUser, Depends(require_user_note_manager)],
    svc: Annotated[AdminDirectoryService, Depends(get_admin_directory_service)],
) -> AdminUserNoteResponse:
    return await svc.add_note(current, user_public_id, payload)


@router.post("/users/{user_public_id}/suspend", response_model=AdminUserDetailResponse)
async def suspend_admin_user(
    user_public_id: UUID,
    payload: AdminUserSuspendRequest,
    current: Annotated[CurrentUser, Depends(require_user_account_manager)],
    svc: Annotated[AdminDirectoryService, Depends(get_admin_directory_service)],
) -> AdminUserDetailResponse:
    return await svc.suspend_user(current, user_public_id, payload)


@router.post("/users/{user_public_id}/restore", response_model=AdminUserDetailResponse)
async def restore_admin_user(
    user_public_id: UUID,
    payload: AdminUserRestoreRequest,
    current: Annotated[CurrentUser, Depends(require_user_account_manager)],
    svc: Annotated[AdminDirectoryService, Depends(get_admin_directory_service)],
) -> AdminUserDetailResponse:
    return await svc.restore_user(current, user_public_id, payload)


@router.post(
    "/users/{user_public_id}/sessions/{session_public_id}/revoke",
    response_model=AdminUserDetailResponse,
)
async def revoke_admin_user_session(
    user_public_id: UUID,
    session_public_id: UUID,
    current: Annotated[CurrentUser, Depends(require_user_security_manager)],
    svc: Annotated[AdminDirectoryService, Depends(get_admin_directory_service)],
) -> AdminUserDetailResponse:
    return await svc.revoke_session(current, user_public_id, session_public_id)


@router.post("/users/{user_public_id}/sessions/revoke-all", response_model=AdminUserDetailResponse)
async def revoke_all_admin_user_sessions(
    user_public_id: UUID,
    current: Annotated[CurrentUser, Depends(require_user_security_manager)],
    svc: Annotated[AdminDirectoryService, Depends(get_admin_directory_service)],
) -> AdminUserDetailResponse:
    return await svc.revoke_all_sessions(current, user_public_id)


@router.post("/users/{user_public_id}/password-reset", response_model=AdminUserDetailResponse)
async def initiate_admin_user_password_reset(
    user_public_id: UUID,
    current: Annotated[CurrentUser, Depends(require_user_security_manager)],
    svc: Annotated[AdminDirectoryService, Depends(get_admin_directory_service)],
) -> AdminUserDetailResponse:
    return await svc.initiate_password_reset(current, user_public_id)
