"""Portfolio item Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, Field, field_validator


class PortfolioItemCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=5000)
    url: AnyHttpUrl | None = None
    tags: list[str] | None = None  # will be stored comma-separated


class PortfolioItemUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=5000)
    url: AnyHttpUrl | None = None
    tags: list[str] | None = None


class PortfolioItemResponse(BaseModel):
    id: UUID
    user_id: UUID
    title: str
    description: str | None
    url: str | None
    tags: list[str]
    original_filename: str | None
    content_type: str | None
    byte_size: int | None
    upload_completed_at: datetime | None
    verification_status: str
    created_at: datetime
    updated_at: datetime

    @field_validator("tags", mode="before")
    @classmethod
    def parse_tags(cls, v: object) -> list[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            return [t.strip() for t in v.split(",") if t.strip()]
        return []

    model_config = {"from_attributes": True}


class PortfolioUploadIntentRequest(BaseModel):
    original_filename: str
    content_type: str
    byte_size: int


class PortfolioUploadIntentResponse(BaseModel):
    portfolio_item_id: UUID
    object_key: str
    bucket: str
    upload_url: str
    expires_in_seconds: int
    headers_required: dict[str, str]


class PortfolioCompleteUploadRequest(BaseModel):
    checksum_sha256: str | None = None


class PortfolioDownloadUrlResponse(BaseModel):
    portfolio_item_id: UUID
    download_url: str
    expires_in_seconds: int
