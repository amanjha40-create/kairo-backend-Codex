"""Validated JSON envelope for jobs published to SQS."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SqsJobEnvelope(BaseModel):
    """Canonical worker payload — API producers should send this shape."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(..., min_length=1, max_length=256, description="Registered handler key")
    data: dict[str, Any] = Field(default_factory=dict)
