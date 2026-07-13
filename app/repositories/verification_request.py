"""Repository for verification requests and immutable timeline events."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.verification_request import VerificationRequest
from app.models.verification_request_event import VerificationRequestEvent


class VerificationRequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, request: VerificationRequest) -> VerificationRequest:
        self._session.add(request)
        await self._session.flush()
        return request

    async def get_by_public_id(self, request_public_id: UUID) -> VerificationRequest | None:
        stmt = (
            select(VerificationRequest)
            .options(
                joinedload(VerificationRequest.organization),
                joinedload(VerificationRequest.registry_record),
                joinedload(VerificationRequest.trust_invitation),
            )
            .where(VerificationRequest.public_id == request_public_id)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_id(self, request_id: UUID) -> VerificationRequest | None:
        return (await self._session.execute(select(VerificationRequest).where(VerificationRequest.id == request_id))).scalar_one_or_none()

    async def list_for_organization(self, organization_id: UUID) -> list[VerificationRequest]:
        stmt = (
            select(VerificationRequest)
            .options(
                joinedload(VerificationRequest.organization),
                joinedload(VerificationRequest.registry_record),
                joinedload(VerificationRequest.trust_invitation),
            )
            .where(VerificationRequest.organization_id == organization_id)
            .order_by(VerificationRequest.created_at.desc())
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())

    async def list_for_subject(self, subject_user_id: UUID) -> list[VerificationRequest]:
        stmt = (
            select(VerificationRequest)
            .options(
                joinedload(VerificationRequest.organization),
                joinedload(VerificationRequest.registry_record),
                joinedload(VerificationRequest.trust_invitation),
            )
            .where(VerificationRequest.subject_user_id == subject_user_id)
            .order_by(VerificationRequest.created_at.desc())
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())

    async def get_active_for_employment(self, employment_id: UUID) -> VerificationRequest | None:
        terminal_statuses = ("verified", "rejected", "cancelled", "expired")
        stmt = (
            select(VerificationRequest)
            .where(
                VerificationRequest.employment_id == employment_id,
                VerificationRequest.status.not_in(terminal_statuses),
            )
            .order_by(VerificationRequest.created_at.desc())
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def list_by_status(self, statuses: list[str]) -> list[VerificationRequest]:
        stmt = (
            select(VerificationRequest)
            .options(
                joinedload(VerificationRequest.organization),
                joinedload(VerificationRequest.registry_record),
                joinedload(VerificationRequest.trust_invitation),
            )
            .where(VerificationRequest.status.in_(statuses))
            .order_by(VerificationRequest.created_at.asc())
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())

    async def append_event(self, event: VerificationRequestEvent) -> VerificationRequestEvent:
        self._session.add(event)
        await self._session.flush()
        return event

    async def list_timeline(self, verification_request_id: UUID) -> list[VerificationRequestEvent]:
        stmt = (
            select(VerificationRequestEvent)
            .where(VerificationRequestEvent.verification_request_id == verification_request_id)
            .order_by(VerificationRequestEvent.created_at.asc(), VerificationRequestEvent.id.asc())
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())
