"""User-facing profile endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_profile_view_service, get_user_service
from app.schemas.user import AvatarUploadIntentResponse, UserPublic, UserUpdate
from app.services import UserService
from app.services.profile_view_service import ProfileViewService, ShareAnalyticsResponse

router = APIRouter(prefix="/users", tags=["users"])


class AvatarUploadRequest(BaseModel):
    content_type: str


@router.get("/me", response_model=UserPublic, summary="Current authenticated user profile")
async def read_me(
    current: CurrentUser = Depends(get_current_user),
    users: UserService = Depends(get_user_service),
) -> UserPublic:
    return await users.get_public_profile(current.id)


@router.patch("/me", response_model=UserPublic, summary="Update current user profile")
async def update_me(
    payload: UserUpdate,
    current: CurrentUser = Depends(get_current_user),
    users: UserService = Depends(get_user_service),
) -> UserPublic:
    return await users.update_profile(current.id, payload)


@router.post("/me/avatar-upload-url", response_model=AvatarUploadIntentResponse, summary="Get presigned URL to upload avatar")
async def get_avatar_upload_url(
    payload: AvatarUploadRequest,
    current: CurrentUser = Depends(get_current_user),
    users: UserService = Depends(get_user_service),
) -> AvatarUploadIntentResponse:
    return await users.create_avatar_upload_intent(current.id, payload.content_type)


@router.post("/me/complete-onboarding", status_code=status.HTTP_204_NO_CONTENT, summary="Mark onboarding complete")
async def complete_onboarding(
    current: CurrentUser = Depends(get_current_user),
    users: UserService = Depends(get_user_service),
) -> None:
    await users.complete_onboarding(current.id)


@router.get("/me/share-analytics", response_model=ShareAnalyticsResponse, summary="Profile share analytics")
async def get_share_analytics(
    current: CurrentUser = Depends(get_current_user),
    view_svc: ProfileViewService = Depends(get_profile_view_service),
) -> ShareAnalyticsResponse:
    return await view_svc.get_analytics(current.id)
