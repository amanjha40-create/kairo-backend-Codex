"""Internal notification center administration routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_notification_service
from app.api.dependencies.verification_admin import require_reviewer, require_view_cases
from app.schemas.notification import (
    NotificationDetailResponse,
    NotificationDeliveryResponse,
    NotificationEventResponse,
    NotificationResponse,
    NotificationStatisticsResponse,
    NotificationUnreadCountResponse,
    UserNotificationResponse,
)
from app.schemas.pagination import ListQueryParams, Page
from app.services.notification_service import NotificationService

admin_router = APIRouter(prefix="/admin/notifications", tags=["notifications"])
user_router = APIRouter(prefix="/notifications", tags=["notifications"])


@user_router.get("", response_model=Page[UserNotificationResponse])
async def list_user_notifications(
    params: Annotated[ListQueryParams, Depends()],
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[NotificationService, Depends(get_notification_service)],
) -> Page[UserNotificationResponse]:
    return await svc.list_user_notifications(current.id, params)


@user_router.get("/unread-count", response_model=NotificationUnreadCountResponse)
async def get_unread_count(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[NotificationService, Depends(get_notification_service)],
) -> NotificationUnreadCountResponse:
    return await svc.unread_count(current.id)


@user_router.post("/{notification_public_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_notification_read(
    notification_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[NotificationService, Depends(get_notification_service)],
) -> None:
    await svc.mark_user_read(current.id, notification_public_id)


@user_router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_notifications_read(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[NotificationService, Depends(get_notification_service)],
) -> None:
    await svc.mark_user_read_all(current.id)


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
