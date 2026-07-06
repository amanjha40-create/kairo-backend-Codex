"""Repository for email delivery audit logs."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_delivery_log import EmailDeliveryLog


class EmailDeliveryLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, log: EmailDeliveryLog) -> EmailDeliveryLog:
        self._session.add(log)
        await self._session.flush()
        return log

    async def get_by_id(self, log_id: UUID) -> EmailDeliveryLog | None:
        stmt = select(EmailDeliveryLog).where(EmailDeliveryLog.id == log_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_public_id(self, public_id: UUID) -> EmailDeliveryLog | None:
        stmt = select(EmailDeliveryLog).where(EmailDeliveryLog.public_id == public_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()
