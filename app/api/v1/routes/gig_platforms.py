"""Gig platform routes — CRUD for platform partnership records."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_gig_platform_service
from app.schemas.gig_platform import (
    GigPlatformCreateRequest,
    GigPlatformResponse,
    GigPlatformUpdateRequest,
)
from app.schemas.pagination import Page, PageParams
from app.services.gig_platform_service import GigPlatformService

router = APIRouter(prefix="/gig-platforms", tags=["gig-platforms"])


@router.get("", response_model=Page[GigPlatformResponse])
async def list_gig_platforms(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    page: Annotated[PageParams, Depends()],
    svc: Annotated[GigPlatformService, Depends(get_gig_platform_service)],
) -> Page[GigPlatformResponse]:
    items, total = await svc.list_for_user(current.id, offset=page.offset, limit=page.limit)
    return Page[GigPlatformResponse].create(
        items=[GigPlatformResponse.model_validate(i) for i in items],
        total=total,
        params=page,
    )


@router.post("", response_model=GigPlatformResponse, status_code=status.HTTP_201_CREATED)
async def create_gig_platform(
    payload: GigPlatformCreateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[GigPlatformService, Depends(get_gig_platform_service)],
) -> GigPlatformResponse:
    item = await svc.create(current.id, payload)
    return GigPlatformResponse.model_validate(item)


@router.get("/{item_id}", response_model=GigPlatformResponse)
async def get_gig_platform(
    item_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[GigPlatformService, Depends(get_gig_platform_service)],
) -> GigPlatformResponse:
    item = await svc.get_owned(current.id, item_id)
    return GigPlatformResponse.model_validate(item)


@router.patch("/{item_id}", response_model=GigPlatformResponse)
async def update_gig_platform(
    item_id: UUID,
    payload: GigPlatformUpdateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[GigPlatformService, Depends(get_gig_platform_service)],
) -> GigPlatformResponse:
    item = await svc.update(current.id, item_id, payload)
    return GigPlatformResponse.model_validate(item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_gig_platform(
    item_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[GigPlatformService, Depends(get_gig_platform_service)],
) -> None:
    await svc.delete(current.id, item_id)
