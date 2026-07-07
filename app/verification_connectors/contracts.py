"""Contracts and execution context for connector implementations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from app.models.trust_registry_record import TrustRegistryRecord
from app.models.verification_request import VerificationRequest
from app.schemas.verification_connector import VerificationConnectorResult


@dataclass(slots=True)
class VerificationConnectorExecutionContext:
    """Generic execution context passed to connector implementations."""

    verification_request: VerificationRequest
    registry_record: TrustRegistryRecord | None = None
    actor_user_id: UUID | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class VerificationConnectorImplementation(Protocol):
    """Pluggable connector implementation contract."""

    connector_key: str
    display_name: str
    supported_capabilities: tuple[str, ...]
    supported_registry_types: tuple[str, ...]
    version: str

    async def execute(
        self,
        context: VerificationConnectorExecutionContext,
    ) -> VerificationConnectorResult:
        """Execute a verification step and return a normalized result payload."""
