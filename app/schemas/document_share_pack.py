"""Platform-neutral selected-file contracts; public DTOs contain no source/storage IDs."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SourceType = Literal["vault", "employment", "education", "certification", "portfolio"]


class DocumentSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_type: SourceType
    source_id: UUID
    selection_version: str = Field(pattern=r"^[0-9a-f]{64}$")


class SelectableDocument(DocumentSelection):
    category: str
    title: str
    context: str | None = None
    filename: str
    content_type: str
    byte_size: int


class DocumentPackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    purpose: str = Field(min_length=1, max_length=120)
    expiry_days: Literal[1, 3, 7, 14, 30]
    items: list[DocumentSelection] = Field(min_length=1, max_length=20)

    @field_validator("purpose", mode="before")
    @classmethod
    def trim_purpose(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def unique_items(self):
        if len({(item.source_type, item.source_id) for item in self.items}) != len(self.items):
            raise ValueError("Select each document only once")
        return self


class PublicPackItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    public_id: UUID
    category: str
    title: str
    context: str | None
    filename: str
    content_type: str
    byte_size: int


class PublicDocumentPack(BaseModel):
    purpose: str
    expires_at: datetime
    document_count: int
    items: list[PublicPackItem]


class DocumentPackResponse(PublicDocumentPack):
    public_id: UUID
    created_at: datetime
    revoked_at: datetime | None
    status: Literal["active", "expired", "revoked"]
    view_count: int
    last_viewed_at: datetime | None


class DocumentPackCreated(DocumentPackResponse):
    share_url: str


class DocumentPackDownload(BaseModel):
    download_url: str
    expires_in_seconds: int
