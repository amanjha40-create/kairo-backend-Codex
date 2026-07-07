"""Service for loading connector catalog entries and in-code implementations."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.verification_connector import VerificationConnector
from app.repositories.verification_connector import VerificationConnectorRepository
from app.verification_connectors.contracts import VerificationConnectorImplementation
from app.verification_connectors.providers import get_connector_implementations


class ConnectorRegistryService:
    """Resolves connector catalog records and implementation instances."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        implementations: tuple[VerificationConnectorImplementation, ...] | None = None,
    ) -> None:
        self._session = session
        self._repo = VerificationConnectorRepository(session)
        self._implementations = implementations if implementations is not None else get_connector_implementations()
        self._implementation_by_key = {implementation.connector_key: implementation for implementation in self._implementations}

    async def list_connectors(self) -> list[VerificationConnector]:
        return await self._repo.list_all()

    async def list_enabled_connectors(self) -> list[VerificationConnector]:
        return await self._repo.list_enabled()

    async def get_connector_by_key(self, connector_key: str) -> VerificationConnector | None:
        return await self._repo.get_by_key(connector_key)

    async def get_connector_by_public_id(self, connector_public_id):
        return await self._repo.get_by_public_id(connector_public_id)

    def get_implementation(self, connector_key: str) -> VerificationConnectorImplementation | None:
        return self._implementation_by_key.get(connector_key)
