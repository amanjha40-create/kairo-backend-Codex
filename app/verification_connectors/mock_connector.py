"""Mock verification connector for local and test execution."""

from __future__ import annotations

from datetime import UTC, datetime

from app.exceptions import ServiceUnavailableError
from app.schemas.verification_connector import VerificationConnectorResult
from app.verification_connectors.contracts import VerificationConnectorExecutionContext


class MockVerificationConnector:
    """Safe in-process connector used to exercise the framework."""

    connector_key = "mock_connector"
    display_name = "Mock Verification Connector"
    supported_capabilities = (
        "employment",
        "education",
        "identity",
        "document",
        "license",
        "medical",
        "reference",
        "platform",
        "certification",
        "custom",
    )
    supported_registry_types = ("*",)
    version = "v1"

    async def execute(
        self,
        context: VerificationConnectorExecutionContext,
    ) -> VerificationConnectorResult:
        occurred_at = datetime.now(tz=UTC)
        mode = self._resolve_mode(context)
        if mode == "unavailable":
            raise ServiceUnavailableError("Mock connector is unavailable")
        request_type = self._request_type(context)
        if mode == "failed":
            return VerificationConnectorResult(
                status="failed",
                confidence=25,
                normalized_data={
                    "request_type": request_type,
                    "match": False,
                    "outcome": "not_verified",
                },
                raw_metadata={
                    "connector": self.connector_key,
                    "mode": mode,
                },
                evidence_references=[],
                errors=[
                    {
                        "code": "verification_failed",
                        "message": "Mock connector returned a negative verification result",
                    }
                ],
                occurred_at=occurred_at,
                completed_at=occurred_at,
            )
        return VerificationConnectorResult(
            status="verified",
            confidence=95,
            normalized_data={
                "request_type": request_type,
                "match": True,
                "outcome": "verified",
            },
            raw_metadata={
                "connector": self.connector_key,
                "mode": mode,
            },
            evidence_references=[],
            errors=[],
            occurred_at=occurred_at,
            completed_at=occurred_at,
        )

    def _resolve_mode(self, context: VerificationConnectorExecutionContext) -> str:
        metadata_mode = context.metadata.get("connector_mode") or context.metadata.get("mock_connector_mode")
        trust_context_mode = context.verification_request.trust_context.get("connector_mode") or context.verification_request.trust_context.get(
            "mock_connector_mode"
        )
        mode = metadata_mode or trust_context_mode or "success"
        normalized = str(mode).strip().lower()
        if normalized in {"success", "verified"}:
            return "success"
        if normalized in {"failed", "failure", "negative"}:
            return "failed"
        if normalized in {"unavailable", "down", "offline"}:
            return "unavailable"
        return "success"

    def _request_type(self, context: VerificationConnectorExecutionContext) -> str:
        raw = getattr(context.verification_request.request_type, "value", context.verification_request.request_type)
        return str(raw).strip().lower()
