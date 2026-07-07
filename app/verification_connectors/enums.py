"""Verification connector framework enums."""

from __future__ import annotations

from enum import StrEnum


class VerificationConnectorHealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class VerificationConnectorRunStatus(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class VerificationConnectorResultStatus(StrEnum):
    VERIFIED = "verified"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
