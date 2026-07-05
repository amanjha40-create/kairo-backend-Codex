"""Generic API envelopes — optional wrappers around domain DTOs."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ApiSuccessEnvelope(BaseModel, Generic[T]):
    """Standard success body when routes prefer `{ data, meta }` instead of bare models."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    data: T
    meta: dict[str, Any] | None = None


class ApiErrorBody(BaseModel):
    """Structured client-facing error — align with exception handlers."""

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(..., min_length=1, max_length=128)
    message: str = Field(..., min_length=1, max_length=2000)
    details: list[dict[str, Any]] | None = None
