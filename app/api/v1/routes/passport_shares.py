"""Authenticated Trust Passport share-link management."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_passport_share_service
from app.schemas.pagination import Page, PageParams
from app.schemas.passport_share import (
    PassportShareCreateRequest,
    PassportShareCreateResponse,
    PassportShareResponse,
    PassportShareUpdateRequest,
)
from app.services.passport_share_service import PassportShareService

router = APIRouter(prefix="/passport-shares", tags=["passport-shares"])


@router.post("", response_model=PassportShareCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_passport_share(
    payload: PassportShareCreateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[PassportShareService, Depends(get_passport_share_service)],
) -> PassportShareCreateResponse:
    return await svc.create(current.id, payload)


@router.get("", response_model=Page[PassportShareResponse])
async def list_passport_shares(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    page: Annotated[PageParams, Depends()],
    svc: Annotated[PassportShareService, Depends(get_passport_share_service)],
) -> Page[PassportShareResponse]:
    items, total = await svc.list_for_user(current.id, offset=page.offset, limit=page.limit)
    return Page[PassportShareResponse](
        items=items,
        total=total,
        offset=page.offset,
        limit=page.limit,
    )


@router.get("/{share_id}", response_model=PassportShareResponse)
async def get_passport_share(
    share_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[PassportShareService, Depends(get_passport_share_service)],
) -> PassportShareResponse:
    return await svc.get_owned(current.id, share_id)


@router.patch("/{share_id}", response_model=PassportShareResponse)
async def update_passport_share(
    share_id: UUID,
    payload: PassportShareUpdateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[PassportShareService, Depends(get_passport_share_service)],
) -> PassportShareResponse:
    return await svc.update(current.id, share_id, payload)


@router.post("/{share_id}/revoke", response_model=PassportShareResponse)
async def revoke_passport_share(
    share_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[PassportShareService, Depends(get_passport_share_service)],
) -> PassportShareResponse:
    return await svc.revoke(current.id, share_id)
