"""In-code verification connector implementation registry."""

from __future__ import annotations

from app.verification_connectors.contracts import VerificationConnectorImplementation
from app.verification_connectors.mock_connector import MockVerificationConnector
from app.config import get_settings


def get_connector_implementations() -> tuple[VerificationConnectorImplementation, ...]:
    """Return all available connector implementations for this deployment."""

    if get_settings().is_production:
        return ()
    return (MockVerificationConnector(),)
