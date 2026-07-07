"""In-code verification connector implementation registry."""

from __future__ import annotations

from app.verification_connectors.contracts import VerificationConnectorImplementation


def get_connector_implementations() -> tuple[VerificationConnectorImplementation, ...]:
    """Return all available connector implementations for this deployment."""

    return ()
