"""Request-scoped compatibility rules for Employment API contracts."""

from __future__ import annotations

import logging
import re
from contextvars import ContextVar, Token
from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

NULLABLE_EMPLOYMENT_TYPE_CAPABILITY = "nullable-employment-type-v1"
LEGACY_EMPLOYMENT_TYPE_FALLBACK = "other"
_MAX_HEADER_LENGTH = 2048
_MAX_CAPABILITIES = 64
_CAPABILITY_TOKEN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")

logger = logging.getLogger(__name__)


class EmploymentClientClass(StrEnum):
    NULLABLE_EMPLOYMENT_CAPABLE = "nullable_employment_capable"
    LEGACY_OR_UNKNOWN = "legacy_or_unknown"


@dataclass(frozen=True, slots=True)
class ClientMetadata:
    """Non-authoritative client compatibility metadata."""

    platform: str | None = None
    package: str | None = None
    version_code: str | None = None
    version_name: str | None = None
    capabilities: frozenset[str] = frozenset()

    @property
    def client_class(self) -> EmploymentClientClass:
        if NULLABLE_EMPLOYMENT_TYPE_CAPABILITY in self.capabilities:
            return EmploymentClientClass.NULLABLE_EMPLOYMENT_CAPABLE
        return EmploymentClientClass.LEGACY_OR_UNKNOWN


_DEFAULT_METADATA = ClientMetadata()
_client_metadata: ContextVar[ClientMetadata] = ContextVar(
    "client_metadata",
    default=_DEFAULT_METADATA,
)


def _safe_header(value: str | None) -> str | None:
    if value is None or len(value) > _MAX_HEADER_LENGTH:
        return None
    normalized = value.strip()
    return normalized or None


def parse_client_metadata(headers: Mapping[str, str]) -> ClientMetadata:
    """Parse optional headers defensively; malformed values degrade to legacy."""

    raw_capabilities = _safe_header(headers.get("x-kairoid-capabilities"))
    capabilities: set[str] = set()
    if raw_capabilities is not None:
        for raw in raw_capabilities.split(",")[:_MAX_CAPABILITIES]:
            capability = raw.strip().lower()
            if _CAPABILITY_TOKEN.fullmatch(capability):
                capabilities.add(capability)

    return ClientMetadata(
        platform=_safe_header(headers.get("x-kairoid-platform")),
        package=_safe_header(headers.get("x-kairoid-package")),
        version_code=_safe_header(headers.get("x-kairoid-version-code")),
        version_name=_safe_header(headers.get("x-kairoid-version-name")),
        capabilities=frozenset(capabilities),
    )


def bind_client_metadata(metadata: ClientMetadata) -> Token[ClientMetadata]:
    return _client_metadata.set(metadata)


def reset_client_metadata(token: Token[ClientMetadata]) -> None:
    _client_metadata.reset(token)


def current_client_metadata() -> ClientMetadata:
    return _client_metadata.get()


def nullable_employment_type_capable() -> bool:
    return (
        current_client_metadata().client_class
        is EmploymentClientClass.NULLABLE_EMPLOYMENT_CAPABLE
    )


def employment_type_for_response(value: str | None) -> str | None:
    """Apply the response-only legacy shim without changing canonical state."""

    if value is not None or nullable_employment_type_capable():
        return value
    observe_legacy_response_shim()
    return LEGACY_EMPLOYMENT_TYPE_FALLBACK


def observe_client_request(*, nullable_writes_enabled: bool) -> None:
    logger.info(
        "employment_client_class_observed",
        extra={
            "event": "employment_client_class_observed",
            "count": 1,
            "client_class": current_client_metadata().client_class.value,
            "nullable_writes_enabled": nullable_writes_enabled,
        },
    )


def observe_legacy_response_shim() -> None:
    logger.info(
        "employment_legacy_response_shim_applied",
        extra={
            "event": "employment_legacy_response_shim_applied",
            "count": 1,
            "client_class": EmploymentClientClass.LEGACY_OR_UNKNOWN.value,
        },
    )


def observe_legacy_mutation_blocked() -> None:
    logger.warning(
        "employment_legacy_mutation_blocked",
        extra={
            "event": "employment_legacy_mutation_blocked",
            "count": 1,
            "client_class": EmploymentClientClass.LEGACY_OR_UNKNOWN.value,
        },
    )
