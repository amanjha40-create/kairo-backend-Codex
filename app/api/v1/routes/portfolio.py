"""Portfolio items — freelancer project showcase."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_portfolio_service
from app.schemas.pagination import Page, PageParams
from app.schemas.portfolio import (
    PortfolioCompleteUploadRequest,
    PortfolioDownloadUrlResponse,
    PortfolioItemCreateRequest,
    PortfolioItemResponse,
    PortfolioItemUpdateRequest,
    PortfolioUploadIntentRequest,
    PortfolioUploadIntentResponse,
)
from app.services.portfolio_service import PortfolioService

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("", response_model=Page[PortfolioItemResponse])
async def list_portfolio(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    page: Annotated[PageParams, Depends()],
    svc: Annotated[PortfolioService, Depends(get_portfolio_service)],
) -> Page[PortfolioItemResponse]:
    items, total = await svc.list_for_user(current.id, offset=page.offset, limit=page.limit)
    return Page[PortfolioItemResponse].create(
        items=[PortfolioItemResponse.model_validate(i) for i in items],
        total=total,
        params=page,
    )


@router.post("", response_model=PortfolioItemResponse, status_code=status.HTTP_201_CREATED)
async def create_portfolio_item(
    payload: PortfolioItemCreateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[PortfolioService, Depends(get_portfolio_service)],
) -> PortfolioItemResponse:
    item = await svc.create(current.id, payload)
    return PortfolioItemResponse.model_validate(item)


@router.get("/{item_id}", response_model=PortfolioItemResponse)
async def get_portfolio_item(
    item_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[PortfolioService, Depends(get_portfolio_service)],
) -> PortfolioItemResponse:
    item = await svc.get_owned(current.id, item_id)
    return PortfolioItemResponse.model_validate(item)


@router.patch("/{item_id}", response_model=PortfolioItemResponse)
async def update_portfolio_item(
    item_id: UUID,
    payload: PortfolioItemUpdateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[PortfolioService, Depends(get_portfolio_service)],
) -> PortfolioItemResponse:
    item = await svc.update(current.id, item_id, payload)
    return PortfolioItemResponse.model_validate(item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_portfolio_item(
    item_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[PortfolioService, Depends(get_portfolio_service)],
) -> None:
    await svc.delete(current.id, item_id)


@router.post(
    "/{item_id}/upload-intent",
    response_model=PortfolioUploadIntentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_upload_intent(
    item_id: UUID,
    payload: PortfolioUploadIntentRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[PortfolioService, Depends(get_portfolio_service)],
) -> PortfolioUploadIntentResponse:
    return await svc.create_upload_intent(current.id, item_id, payload)


@router.post(
    "/{item_id}/complete-upload",
    response_model=PortfolioItemResponse,
)
async def complete_upload(
    item_id: UUID,
    payload: PortfolioCompleteUploadRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[PortfolioService, Depends(get_portfolio_service)],
) -> PortfolioItemResponse:
    item = await svc.complete_upload(current.id, item_id, payload)
    return PortfolioItemResponse.model_validate(item)


@router.get(
    "/{item_id}/download-url",
    response_model=PortfolioDownloadUrlResponse,
)
async def get_download_url(
    item_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[PortfolioService, Depends(get_portfolio_service)],
) -> PortfolioDownloadUrlResponse:
    return await svc.get_download_url(current.id, item_id)
