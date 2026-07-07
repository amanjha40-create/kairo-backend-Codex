"""Connector selection rules for verification requests."""

from __future__ import annotations

from app.exceptions import ServiceUnavailableError
from app.models.verification_connector import VerificationConnector
from app.models.verification_request import VerificationRequest
from app.services.connector_registry_service import ConnectorRegistryService


class ConnectorSelectionService:
    """Selects the best available connector for a verification request."""

    def __init__(self, registry: ConnectorRegistryService) -> None:
        self._registry = registry

    async def select_for_request(self, request: VerificationRequest) -> VerificationConnector:
        connectors = await self._registry.list_enabled_connectors()
        capability = request.request_type.value
        registry_type = request.registry_record.organization_type if request.registry_record is not None else None

        matches = [
            connector
            for connector in connectors
            if self._supports_capability(connector, capability) and self._supports_registry_type(connector, registry_type)
        ]
        if not matches:
            raise ServiceUnavailableError("No enabled verification connector is available for this request")

        matches.sort(
            key=lambda connector: (
                connector.priority,
                0 if self._is_exact_registry_match(connector, registry_type) else 1,
                connector.connector_key,
            )
        )
        return matches[0]

    def _supports_capability(self, connector: VerificationConnector, capability: str) -> bool:
        normalized_capabilities = {value.strip().lower() for value in connector.supported_capabilities}
        return capability.strip().lower() in normalized_capabilities

    def _supports_registry_type(self, connector: VerificationConnector, registry_type: str | None) -> bool:
        supported_types = {value.strip().lower() for value in connector.supported_registry_types}
        if "*" in supported_types:
            return True
        if registry_type is None:
            return not supported_types
        return registry_type.strip().lower() in supported_types

    def _is_exact_registry_match(self, connector: VerificationConnector, registry_type: str | None) -> bool:
        if registry_type is None:
            return False
        supported_types = {value.strip().lower() for value in connector.supported_registry_types}
        return registry_type.strip().lower() in supported_types
