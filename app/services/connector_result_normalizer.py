"""Normalization helpers for connector execution results."""

from __future__ import annotations

from datetime import UTC, datetime

from app.schemas.verification_connector import VerificationConnectorResult


class ConnectorResultNormalizer:
    """Ensures connector outputs conform to the platform result contract."""

    def normalize(self, result: VerificationConnectorResult) -> VerificationConnectorResult:
        if result.completed_at is None:
            result.completed_at = datetime.now(tz=UTC)
        if result.occurred_at.tzinfo is None:
            result.occurred_at = result.occurred_at.replace(tzinfo=UTC)
        if result.completed_at.tzinfo is None:
            result.completed_at = result.completed_at.replace(tzinfo=UTC)
        if result.status:
            result.status = result.status.strip().lower()
        return result
