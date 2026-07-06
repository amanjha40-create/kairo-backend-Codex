"""Shared API error response schemas for OpenAPI and tests."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ApiValidationErrorDetail(BaseModel):
    location: list[str | int] = Field(description="Error location path.")
    message: str = Field(description="Human-readable validation message.")
    error_type: str = Field(description="Pydantic/FastAPI validation error type.")


class ApiErrorPayload(BaseModel):
    code: str = Field(examples=["not_found"])
    message: str = Field(examples=["Resource not found"])
    details: list[ApiValidationErrorDetail] | None = None


class ApiErrorResponse(BaseModel):
    error: ApiErrorPayload
