"""Shared DTOs and helpers for pagination, filtering, and list responses."""

from __future__ import annotations

import math
from datetime import date, datetime, time
from typing import Any, Generic, Sequence, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

T = TypeVar("T")


class PageParams(BaseModel):
    """Backward-compatible pagination parameters with page/page_size support."""

    model_config = ConfigDict(str_strip_whitespace=True)

    page: int | None = Field(
        default=None,
        ge=1,
        description="1-based page number. Preferred over offset.",
        examples=[1],
    )
    page_size: int | None = Field(
        default=None,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="Preferred page size query parameter.",
        examples=[20],
    )
    offset: int | None = Field(
        default=None,
        ge=0,
        description="Deprecated 0-based row offset. Still supported for backward compatibility.",
        examples=[0],
    )
    limit: int | None = Field(
        default=None,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="Deprecated page size parameter. Still supported for backward compatibility.",
        examples=[20],
    )

    @field_validator("page_size", "limit")
    @classmethod
    def cap_limit(cls, v: int | None) -> int | None:
        if v is None:
            return None
        return min(v, MAX_PAGE_SIZE)

    @model_validator(mode="after")
    def normalize_pagination(self) -> "PageParams":
        size = self.page_size or self.limit or DEFAULT_PAGE_SIZE
        size = min(size, MAX_PAGE_SIZE)

        if self.page is not None:
            page = self.page
            offset = (page - 1) * size
        elif self.offset is not None:
            offset = self.offset
            page = (offset // size) + 1
        else:
            page = 1
            offset = 0

        self.page = page
        self.page_size = size
        self.offset = offset
        self.limit = size
        return self

    @property
    def slice_start(self) -> int:
        return self.offset or 0

    @property
    def slice_end(self) -> int:
        return self.slice_start + (self.limit or DEFAULT_PAGE_SIZE)


class ListQueryParams(PageParams):
    """Generic frontend-friendly query parameters for list endpoints."""

    pagination_requested: bool = Field(default=False, exclude=True)
    paginate: bool = Field(
        default=False,
        description="When true, return a page envelope instead of a raw list for backward-compatible routes.",
    )
    search: str | None = Field(default=None, description="Case-insensitive free-text search.")
    status: str | None = Field(
        default=None,
        description="Optional status filter. Comma-separated values are supported.",
        examples=["pending,accepted"],
    )
    created_after: datetime | date | None = Field(
        default=None,
        description="Include records created on or after this timestamp/date.",
    )
    created_before: datetime | date | None = Field(
        default=None,
        description="Include records created on or before this timestamp/date.",
    )
    sort_by: str | None = Field(default=None, description="Field name to sort by when supported.")
    sort_order: str = Field(default="desc", description="Sort direction: asc or desc.")

    @field_validator("sort_order")
    @classmethod
    def validate_sort_order(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"asc", "desc"}:
            raise ValueError("sort_order must be 'asc' or 'desc'")
        return normalized

    @model_validator(mode="before")
    @classmethod
    def mark_requested_pagination(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data["pagination_requested"] = data.get("paginate", False) or any(
                data.get(field_name) is not None
                for field_name in ("page", "page_size", "offset", "limit")
            )
        return data

    @model_validator(mode="after")
    def normalize_paginate(self) -> "ListQueryParams":
        self.paginate = self.paginate or self.pagination_requested
        return self


class Page(BaseModel, Generic[T]):
    """Uniform page envelope for stable OpenAPI and clients."""

    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int
    offset: int
    limit: int

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @model_validator(mode="before")
    @classmethod
    def backfill_legacy_pagination_fields(cls, data: Any) -> Any:
        """Accept older `{items,total,offset,limit}` constructors and derive the rest."""

        if not isinstance(data, dict):
            return data

        total = int(data.get("total", 0) or 0)
        offset = int(data.get("offset", 0) or 0)
        limit = int(data.get("limit") or data.get("page_size") or DEFAULT_PAGE_SIZE)
        limit = min(max(limit, 1), MAX_PAGE_SIZE)
        page = int(data.get("page") or ((offset // limit) + 1))
        page_size = int(data.get("page_size") or limit)
        total_pages = int(data.get("total_pages") or (math.ceil(total / page_size) if total > 0 else 0))

        normalized = dict(data)
        normalized["offset"] = offset
        normalized["limit"] = limit
        normalized["page"] = page
        normalized["page_size"] = page_size
        normalized["total_pages"] = total_pages
        return normalized

    @classmethod
    def create(
        cls,
        *,
        items: list[T],
        total: int,
        params: PageParams,
    ) -> "Page[T]":
        page_size = params.page_size or DEFAULT_PAGE_SIZE
        total_pages = math.ceil(total / page_size) if total > 0 else 0
        return cls(
            items=items,
            total=total,
            page=params.page or 1,
            page_size=page_size,
            total_pages=total_pages,
            offset=params.offset or 0,
            limit=params.limit or page_size,
        )


class Message(BaseModel):
    """Simple narrative responses."""

    message: str
    meta: dict[str, Any] | None = None


def filter_sort_paginate(
    items: Sequence[T],
    *,
    params: ListQueryParams,
    search_fields: Sequence[str] = (),
    status_field: str | None = "status",
    created_field: str | None = "created_at",
    allowed_sort_fields: Sequence[str] = (),
    default_sort_by: str | None = "created_at",
    force_page_envelope: bool = False,
) -> list[T] | Page[T]:
    """Apply lightweight in-memory filtering/sorting/pagination to response DTOs."""

    filtered = list(items)

    if params.search and search_fields:
        needle = params.search.strip().lower()
        filtered = [
            item for item in filtered
            if any(needle in _stringify(getattr(item, field, None)).lower() for field in search_fields)
        ]

    if params.status and status_field:
        accepted_statuses = {part.strip().lower() for part in params.status.split(",") if part.strip()}
        filtered = [
            item for item in filtered
            if _stringify(getattr(item, status_field, None)).lower() in accepted_statuses
        ]

    if params.created_after and created_field:
        created_after = _coerce_datetime(params.created_after, end_of_day=False)
        filtered = [
            item for item in filtered
            if (item_created := _coerce_datetime(getattr(item, created_field, None), end_of_day=False)) is not None
            and item_created >= created_after
        ]

    if params.created_before and created_field:
        created_before = _coerce_datetime(params.created_before, end_of_day=True)
        filtered = [
            item for item in filtered
            if (item_created := _coerce_datetime(getattr(item, created_field, None), end_of_day=False)) is not None
            and item_created <= created_before
        ]

    sort_by = params.sort_by or default_sort_by
    if sort_by and (not allowed_sort_fields or sort_by in allowed_sort_fields):
        filtered.sort(
            key=lambda item: _sort_key(getattr(item, sort_by, None)),
            reverse=params.sort_order == "desc",
        )

    total = len(filtered)
    if force_page_envelope or params.paginate:
        effective_params = params
        page_items = filtered[params.slice_start:params.slice_end]
        if force_page_envelope and not params.paginate:
            effective_params = PageParams(
                page=1,
                page_size=max(total, 1),
            )
            page_items = filtered
        return Page[T].create(items=page_items, total=total, params=effective_params)

    return filtered


def _stringify(value: object) -> str:
    if value is None:
        return ""
    if hasattr(value, "value"):
        return str(getattr(value, "value"))
    return str(value)


def _coerce_datetime(value: object, *, end_of_day: bool) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        if end_of_day:
            return datetime.combine(value, time.max)
        return datetime.combine(value, time.min)
    return None


def _sort_key(value: object) -> tuple[int, object]:
    if value is None:
        return (1, "")
    if hasattr(value, "value"):
        return (0, str(getattr(value, "value")))
    return (0, value)
