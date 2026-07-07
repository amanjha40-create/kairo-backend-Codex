"""Verification connector framework DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _normalize_key(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("value cannot be empty")
    return normalized


class VerificationConnectorResponse(BaseModel):
    public_id: UUID
    connector_key: str
    display_name: str
    connector_type: str
    supported_capabilities: list[str]
    supported_registry_types: list[str]
    version: str
    health_status: str
    enabled: bool
    priority: int
    last_health_checked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class VerificationConnectorUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=10_000)
    health_status: str | None = Field(default=None, min_length=1, max_length=32)

    @field_validator("health_status")
    @classmethod
    def validate_health_status(cls, value: str | None) -> str | None:
        return _normalize_key(value) if value is not None else None


class VerificationConnectorHealthResponse(BaseModel):
    connector_public_id: UUID
    connector_key: str
    display_name: str
    health_status: str
    enabled: bool
    checked_at: datetime | None


class VerificationConnectorRunResponse(BaseModel):
    public_id: UUID
    connector_public_id: UUID | None = None
    connector_key: str
    verification_request_public_id: UUID
    registry_record_public_id: UUID | None
    status: str
    started_at: datetime
    completed_at: datetime | None
    execution_time_ms: int | None
    normalized_result: dict[str, Any]
    raw_metadata: dict[str, Any]
    evidence_references: list[dict[str, Any]]
    error: dict[str, Any]
    retry_count: int
    created_at: datetime
    updated_at: datetime


class VerificationConnectorResult(BaseModel):
    status: str
    confidence: float | None = Field(default=None, ge=0, le=100)
    normalized_data: dict[str, Any] = Field(default_factory=dict)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)
    evidence_references: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    occurred_at: datetime
    completed_at: datetime | None = None


class VerificationConnectorRunListResponse(BaseModel):
    connector_public_id: UUID
    connector_key: str
    items: list[VerificationConnectorRunResponse]
