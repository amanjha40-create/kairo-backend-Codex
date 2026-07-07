"""Internal notification center administration routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.dependencies.services import get_notification_service
from app.api.dependencies.verification_admin import CurrentUser, require_reviewer, require_view_cases
from app.schemas.notification import (
    NotificationDetailResponse,
    NotificationDeliveryResponse,
    NotificationEventResponse,
    NotificationResponse,
    NotificationStatisticsResponse,
)
from app.schemas.pagination import ListQueryParams, Page
from app.services.notification_service import NotificationService

admin_router = APIRouter(prefix="/admin/notifications", tags=["notifications"])


@admin_router.get("/statistics/summary", response_model=NotificationStatisticsResponse)
async def get_notification_statistics(
    _: Annotated[CurrentUser, Depends(require_view_cases)],
    svc: Annotated[NotificationService, Depends(get_notification_service)],
) -> NotificationStatisticsResponse:
    return await svc.get_statistics()


@admin_router.get("", response_model=Page[NotificationResponse])
async def list_notifications(
    params: Annotated[ListQueryParams, Depends()],
    _: Annotated[CurrentUser, Depends(require_view_cases)],
    svc: Annotated[NotificationService, Depends(get_notification_service)],
) -> Page[NotificationResponse]:
    return await svc.list_notifications(params)


@admin_router.get("/{notification_public_id}", response_model=NotificationDetailResponse)
async def get_notification(
    notification_public_id: UUID,
    _: Annotated[CurrentUser, Depends(require_view_cases)],
    svc: Annotated[NotificationService, Depends(get_notification_service)],
) -> NotificationDetailResponse:
    return await svc.get_detail(notification_public_id)


@admin_router.post("/{notification_public_id}/resend", response_model=NotificationDetailResponse)
async def resend_notification(
    notification_public_id: UUID,
    reviewer: Annotated[CurrentUser, Depends(require_reviewer)],
    svc: Annotated[NotificationService, Depends(get_notification_service)],
) -> NotificationDetailResponse:
    return await svc.resend(notification_public_id, actor_user_id=reviewer.id)


@admin_router.get("/{notification_public_id}/history", response_model=Page[NotificationEventResponse])
async def get_notification_history(
    notification_public_id: UUID,
    params: Annotated[ListQueryParams, Depends()],
    _: Annotated[CurrentUser, Depends(require_view_cases)],
    svc: Annotated[NotificationService, Depends(get_notification_service)],
) -> Page[NotificationEventResponse]:
    return await svc.list_history(notification_public_id, params)


@admin_router.get("/{notification_public_id}/deliveries", response_model=Page[NotificationDeliveryResponse])
async def get_notification_deliveries(
    notification_public_id: UUID,
    params: Annotated[ListQueryParams, Depends()],
    _: Annotated[CurrentUser, Depends(require_view_cases)],
    svc: Annotated[NotificationService, Depends(get_notification_service)],
) -> Page[NotificationDeliveryResponse]:
    return await svc.list_deliveries(notification_public_id, params)
