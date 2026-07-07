"""Repositories for notification center models."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.models.notification import Notification
from app.models.notification_delivery import NotificationDelivery
from app.models.notification_event import NotificationEvent
from app.models.notification_preference import NotificationPreference


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, notification: Notification) -> Notification:
        self._session.add(notification)
        await self._session.flush()
        return notification

    async def get_by_public_id(self, notification_public_id: UUID) -> Notification | None:
        stmt = (
            select(Notification)
            .options(
                selectinload(Notification.deliveries),
                selectinload(Notification.events),
            )
            .where(Notification.public_id == notification_public_id)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_all(self) -> list[Notification]:
        stmt = (
            select(Notification)
            .options(
                selectinload(Notification.deliveries),
                selectinload(Notification.events),
            )
            .order_by(Notification.created_at.desc(), Notification.id.desc())
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())

    async def count_by_status(self) -> list[tuple[str, int]]:
        stmt = (
            select(Notification.status, func.count(Notification.id))
            .group_by(Notification.status)
            .order_by(Notification.status.asc())
        )
        rows = await self._session.execute(stmt)
        return [(status, int(total)) for status, total in rows.all()]

    async def count_by_channel(self) -> list[tuple[str, int]]:
        stmt = (
            select(Notification.channel, func.count(Notification.id))
            .group_by(Notification.channel)
            .order_by(Notification.channel.asc())
        )
        rows = await self._session.execute(stmt)
        return [(channel, int(total)) for channel, total in rows.all()]


class NotificationPreferenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, preference: NotificationPreference) -> NotificationPreference:
        self._session.add(preference)
        await self._session.flush()
        return preference

    async def get_for_user_event(self, user_id: UUID, event_type: str) -> NotificationPreference | None:
        stmt = select(NotificationPreference).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.event_type == event_type,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()


class NotificationDeliveryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, delivery: NotificationDelivery) -> NotificationDelivery:
        self._session.add(delivery)
        await self._session.flush()
        return delivery

    async def list_for_notification(self, notification_id: UUID) -> list[NotificationDelivery]:
        stmt = (
            select(NotificationDelivery)
            .options(joinedload(NotificationDelivery.email_delivery_log))
            .where(NotificationDelivery.notification_id == notification_id)
            .order_by(NotificationDelivery.created_at.asc(), NotificationDelivery.id.asc())
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())


class NotificationEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, event: NotificationEvent) -> NotificationEvent:
        self._session.add(event)
        await self._session.flush()
        return event

    async def list_for_notification(self, notification_id: UUID) -> list[NotificationEvent]:
        stmt = (
            select(NotificationEvent)
            .where(NotificationEvent.notification_id == notification_id)
            .order_by(NotificationEvent.created_at.asc(), NotificationEvent.id.asc())
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())
