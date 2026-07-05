"""Portfolio item service — create, list, upload, delete."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.exceptions import NotFoundError, ServiceUnavailableError
from app.infrastructure.s3.presign import generate_presigned_get_url, generate_presigned_put_url
from app.models.portfolio import PortfolioItem
from app.repositories.portfolio import PortfolioRepository
from app.schemas.portfolio import (
    PortfolioCompleteUploadRequest,
    PortfolioDownloadUrlResponse,
    PortfolioItemCreateRequest,
    PortfolioItemUpdateRequest,
    PortfolioUploadIntentRequest,
    PortfolioUploadIntentResponse,
)


class PortfolioService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._repo = PortfolioRepository(session)
        self._settings = settings or get_settings()

    def _tags_to_str(self, tags: list[str] | None) -> str | None:
        if not tags:
            return None
        return ",".join(t.strip() for t in tags if t.strip())

    async def create(self, user_id: UUID, payload: PortfolioItemCreateRequest) -> PortfolioItem:
        item = PortfolioItem(
            user_id=user_id,
            title=payload.title,
            description=payload.description,
            url=payload.url,
            tags=self._tags_to_str(payload.tags),
            verification_status="pending",
        )
        await self._repo.create(item)
        await self._session.commit()
        await self._session.refresh(item)
        return item

    async def list_for_user(self, user_id: UUID, *, offset: int = 0, limit: int = 50):
        return await self._repo.list_for_user(user_id, offset=offset, limit=limit)

    async def get_owned(self, user_id: UUID, item_id: UUID) -> PortfolioItem:
        item = await self._repo.get_owned(item_id, user_id)
        if item is None:
            raise NotFoundError("Portfolio item not found")
        return item

    async def update(
        self, user_id: UUID, item_id: UUID, payload: PortfolioItemUpdateRequest,
    ) -> PortfolioItem:
        item = await self.get_owned(user_id, item_id)
        data = payload.model_dump(exclude_unset=True)
        for field, value in data.items():
            if field == "tags":
                item.tags = self._tags_to_str(value)
            else:
                setattr(item, field, value)
        await self._session.commit()
        await self._session.refresh(item)
        return item

    async def delete(self, user_id: UUID, item_id: UUID) -> None:
        item = await self.get_owned(user_id, item_id)
        await self._repo.soft_delete(item)
        await self._session.commit()

    # --- File upload ---

    async def create_upload_intent(
        self,
        user_id: UUID,
        item_id: UUID,
        payload: PortfolioUploadIntentRequest,
    ) -> PortfolioUploadIntentResponse:
        item = await self.get_owned(user_id, item_id)

        bucket = self._settings.s3_documents_bucket
        if not bucket:
            raise ServiceUnavailableError("File storage is not configured")

        prefix = self._settings.s3_document_key_prefix.rstrip("/")
        object_key = f"{prefix}/portfolio/{user_id}/{item_id}/{payload.original_filename}"

        item.original_filename = payload.original_filename
        item.content_type = payload.content_type
        item.byte_size = payload.byte_size
        item.object_key = object_key
        await self._session.commit()

        upload_url, headers = await generate_presigned_put_url(
            bucket=bucket,
            object_key=object_key,
            content_type=payload.content_type,
            ttl_seconds=self._settings.s3_presigned_put_ttl_seconds,
        )
        return PortfolioUploadIntentResponse(
            portfolio_item_id=item.id,
            object_key=object_key,
            bucket=bucket,
            upload_url=upload_url,
            expires_in_seconds=self._settings.s3_presigned_put_ttl_seconds,
            headers_required=headers,
        )

    async def complete_upload(
        self,
        user_id: UUID,
        item_id: UUID,
        _payload: PortfolioCompleteUploadRequest,
    ) -> PortfolioItem:
        item = await self.get_owned(user_id, item_id)
        item.upload_completed_at = datetime.now(tz=UTC)
        await self._session.commit()
        await self._session.refresh(item)
        return item

    async def get_download_url(
        self, user_id: UUID, item_id: UUID,
    ) -> PortfolioDownloadUrlResponse:
        item = await self.get_owned(user_id, item_id)
        if not item.object_key or not item.upload_completed_at:
            raise NotFoundError("No file attached to this portfolio item")

        bucket = self._settings.s3_documents_bucket
        if not bucket:
            raise ServiceUnavailableError("File storage is not configured")

        ttl = self._settings.s3_presigned_put_ttl_seconds
        download_url = await generate_presigned_get_url(
            bucket=bucket,
            object_key=item.object_key,
            ttl_seconds=ttl,
        )
        return PortfolioDownloadUrlResponse(
            portfolio_item_id=item.id,
            download_url=download_url,
            expires_in_seconds=ttl,
        )
