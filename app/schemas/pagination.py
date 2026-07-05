"""Shared DTOs for pagination and list responses."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

T = TypeVar("T")


class PageParams(BaseModel):
    """Offset pagination — replace with cursor-based for very large tables."""

    model_config = ConfigDict(str_strip_whitespace=True)

    offset: int = Field(0, ge=0, description="0-based row offset")
    limit: int = Field(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)

    @field_validator("limit")
    @classmethod
    def cap_limit(cls, v: int) -> int:
        return min(v, MAX_PAGE_SIZE)


class Page(BaseModel, Generic[T]):
    """Uniform page envelope for stable OpenAPI and clients."""

    items: list[T]
    total: int
    offset: int
    limit: int

    model_config = ConfigDict(arbitrary_types_allowed=True)


class Message(BaseModel):
    """Simple narrative responses."""

    message: str
    meta: dict[str, Any] | None = None
