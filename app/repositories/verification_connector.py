"""Repositories for connector catalog entries and execution runs."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.verification_connector import VerificationConnector
from app.models.verification_connector_run import VerificationConnectorRun


class VerificationConnectorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, connector: VerificationConnector) -> VerificationConnector:
        self._session.add(connector)
        await self._session.flush()
        return connector

    async def get_by_key(self, connector_key: str) -> VerificationConnector | None:
        stmt = select(VerificationConnector).where(VerificationConnector.connector_key == connector_key)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_public_id(self, connector_public_id: UUID) -> VerificationConnector | None:
        stmt = select(VerificationConnector).where(VerificationConnector.public_id == connector_public_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_all(self) -> list[VerificationConnector]:
        stmt = select(VerificationConnector).order_by(
            VerificationConnector.priority.asc(),
            VerificationConnector.connector_key.asc(),
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())

    async def list_enabled(self) -> list[VerificationConnector]:
        stmt = (
            select(VerificationConnector)
            .where(VerificationConnector.enabled.is_(True))
            .order_by(
                VerificationConnector.priority.asc(),
                VerificationConnector.connector_key.asc(),
            )
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())


class VerificationConnectorRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, run: VerificationConnectorRun) -> VerificationConnectorRun:
        self._session.add(run)
        await self._session.flush()
        return run

    async def get_by_public_id(self, run_public_id: UUID) -> VerificationConnectorRun | None:
        stmt = (
            select(VerificationConnectorRun)
            .options(
                joinedload(VerificationConnectorRun.connector),
                joinedload(VerificationConnectorRun.verification_request),
                joinedload(VerificationConnectorRun.registry_record),
            )
            .where(VerificationConnectorRun.public_id == run_public_id)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_connector_key(self, connector_key: str) -> list[VerificationConnectorRun]:
        stmt = (
            select(VerificationConnectorRun)
            .options(
                joinedload(VerificationConnectorRun.verification_request),
                joinedload(VerificationConnectorRun.registry_record),
            )
            .where(VerificationConnectorRun.connector_key == connector_key)
            .order_by(VerificationConnectorRun.started_at.desc(), VerificationConnectorRun.id.desc())
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())

    async def list_for_request(self, verification_request_id: UUID) -> list[VerificationConnectorRun]:
        stmt = (
            select(VerificationConnectorRun)
            .options(
                joinedload(VerificationConnectorRun.connector),
                joinedload(VerificationConnectorRun.registry_record),
            )
            .where(VerificationConnectorRun.verification_request_id == verification_request_id)
            .order_by(VerificationConnectorRun.started_at.desc(), VerificationConnectorRun.id.desc())
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())

    async def list_for_request_ids(self, verification_request_ids: Sequence[UUID]) -> list[VerificationConnectorRun]:
        if not verification_request_ids:
            return []
        stmt = (
            select(VerificationConnectorRun)
            .options(
                joinedload(VerificationConnectorRun.connector),
                joinedload(VerificationConnectorRun.registry_record),
            )
            .where(VerificationConnectorRun.verification_request_id.in_(verification_request_ids))
            .order_by(VerificationConnectorRun.started_at.desc(), VerificationConnectorRun.id.desc())
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())
