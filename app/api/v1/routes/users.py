"""User-facing profile endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from uuid import UUID
from pydantic import BaseModel

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_profile_view_service, get_user_service
from app.schemas.user import AvatarUploadIntentResponse, UserPublic, UserUpdate
from app.schemas.profile import (
    ProfileLanguageCreate,
    ProfileLanguageResponse,
    ProfileLanguageUpdate,
    ProfileLinkCreate,
    ProfileLinkResponse,
    ProfileLinkUpdate,
)
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


@router.delete("/me/avatar", status_code=status.HTTP_204_NO_CONTENT, summary="Remove current profile photo")
async def remove_avatar(
    current: CurrentUser = Depends(get_current_user),
    users: UserService = Depends(get_user_service),
) -> None:
    await users.remove_avatar(current.id)


@router.post("/me/avatar/complete", response_model=UserPublic, summary="Confirm uploaded profile photo")
async def complete_avatar_upload(
    current: CurrentUser = Depends(get_current_user),
    users: UserService = Depends(get_user_service),
) -> UserPublic:
    return await users.complete_avatar_upload(current.id)


@router.get("/me/languages", response_model=list[ProfileLanguageResponse], summary="List profile languages")
async def list_languages(
    current: CurrentUser = Depends(get_current_user),
    users: UserService = Depends(get_user_service),
) -> list[ProfileLanguageResponse]:
    return await users.list_languages(current.id)


@router.post("/me/languages", response_model=ProfileLanguageResponse, status_code=status.HTTP_201_CREATED, summary="Add profile language")
async def create_language(
    payload: ProfileLanguageCreate,
    current: CurrentUser = Depends(get_current_user),
    users: UserService = Depends(get_user_service),
) -> ProfileLanguageResponse:
    return await users.create_language(current.id, payload)


@router.patch("/me/languages/{language_id}", response_model=ProfileLanguageResponse, summary="Update profile language")
async def update_language(
    language_id: UUID,
    payload: ProfileLanguageUpdate,
    current: CurrentUser = Depends(get_current_user),
    users: UserService = Depends(get_user_service),
) -> ProfileLanguageResponse:
    return await users.update_language(current.id, language_id, payload)


@router.delete("/me/languages/{language_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete profile language")
async def delete_language(
    language_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    users: UserService = Depends(get_user_service),
) -> None:
    await users.delete_language(current.id, language_id)


@router.get("/me/links", response_model=list[ProfileLinkResponse], summary="List professional links")
async def list_links(
    current: CurrentUser = Depends(get_current_user),
    users: UserService = Depends(get_user_service),
) -> list[ProfileLinkResponse]:
    return await users.list_links(current.id)


@router.post("/me/links", response_model=ProfileLinkResponse, status_code=status.HTTP_201_CREATED, summary="Add professional link")
async def create_link(
    payload: ProfileLinkCreate,
    current: CurrentUser = Depends(get_current_user),
    users: UserService = Depends(get_user_service),
) -> ProfileLinkResponse:
    return await users.create_link(current.id, payload)


@router.patch("/me/links/{link_id}", response_model=ProfileLinkResponse, summary="Update professional link")
async def update_link(
    link_id: UUID,
    payload: ProfileLinkUpdate,
    current: CurrentUser = Depends(get_current_user),
    users: UserService = Depends(get_user_service),
) -> ProfileLinkResponse:
    return await users.update_link(current.id, link_id, payload)


@router.delete("/me/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete professional link")
async def delete_link(
    link_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    users: UserService = Depends(get_user_service),
) -> None:
    await users.delete_link(current.id, link_id)


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
