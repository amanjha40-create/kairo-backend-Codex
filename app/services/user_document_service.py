"""User identity document service — S3 upload intents and lifecycle."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.exceptions import NotFoundError, ServiceUnavailableError
from app.infrastructure.s3.presign import (
    generate_presigned_get_url,
    generate_presigned_put_url,
)
from app.models import UserDocument
from app.repositories.user_document import UserDocumentRepository
from app.schemas.user_document import (
    UserDocumentUpdateRequest,
    UserDocumentUploadIntentRequest,
    UserDocumentUploadIntentResponse,
    UserDocumentDownloadUrlResponse,
)

logger = logging.getLogger(__name__)


class UserDocumentService:
    """Owns the lifecycle of user identity documents (Aadhaar, PAN, license, etc.)."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._docs = UserDocumentRepository(session)
        self._settings = settings or get_settings()

    async def list_for_user(self, user_id: UUID, *, offset: int = 0, limit: int = 50):
        return await self._docs.list_for_user(user_id, offset=offset, limit=limit)

    async def get_for_user(self, user_id: UUID, document_id: UUID) -> UserDocument:
        doc = await self._docs.get_owned(document_id, user_id)
        if doc is None:
            raise NotFoundError("User document not found")
        return doc

    async def create_upload_intent(
        self,
        user_id: UUID,
        payload: UserDocumentUploadIntentRequest,
    ) -> UserDocumentUploadIntentResponse:
        """Create DB row and presigned S3 PUT URL — client uploads directly to S3."""

        bucket = self._settings.s3_documents_bucket
        if not bucket:
            raise ServiceUnavailableError("Document storage is not configured")

        replaced = None
        if payload.replaces_document_id is not None:
            replaced = await self._docs.get_owned(payload.replaces_document_id, user_id)
            if replaced is None:
                raise NotFoundError("Document to replace not found")
            if replaced.superseded_at is not None:
                raise NotFoundError("Document to replace is no longer current")

        document_id = uuid.uuid4()
        prefix = self._settings.s3_document_key_prefix.rstrip("/")
        object_key = f"{prefix}/user-documents/{user_id}/{document_id}/{payload.original_filename}"

        # Persist a "pending upload" row first (so we don't have orphan S3 objects)
        doc = UserDocument(
            id=document_id,
            user_id=user_id,
            document_type=payload.document_type.value,
            document_number=payload.document_number,
            object_key=object_key,
            original_filename=payload.original_filename,
            content_type=payload.content_type,
            byte_size=payload.byte_size,
            checksum_sha256="",  # filled at complete-upload step
            verification_status="pending",
            expires_at=payload.expires_at,
            superseded_by_id=None,
            replaces_document_id=replaced.id if replaced is not None else None,
        )
        await self._docs.create(doc)

        upload_url = await generate_presigned_put_url(
            bucket=bucket,
            object_key=object_key,
            content_type=payload.content_type,
            ttl_seconds=self._settings.s3_presigned_put_ttl_seconds,
            settings=self._settings,
        )

        await self._session.commit()

        return UserDocumentUploadIntentResponse(
            document_id=document_id,
            object_key=object_key,
            bucket=bucket,
            upload_url=upload_url,
            expires_in_seconds=self._settings.s3_presigned_put_ttl_seconds,
            headers_required={"Content-Type": payload.content_type},
        )

    async def complete_upload(
        self,
        user_id: UUID,
        document_id: UUID,
        checksum_sha256: str,
    ) -> UserDocument:
        """Mark the document as uploaded after client confirms S3 PUT."""

        doc = await self._docs.get_owned(document_id, user_id)
        if doc is None:
            raise NotFoundError("User document not found")
        doc.checksum_sha256 = checksum_sha256
        if doc.replaces_document_id is not None:
            previous = await self._docs.get_owned(doc.replaces_document_id, user_id)
            if previous is not None and previous.superseded_at is None:
                previous.superseded_at = datetime.now(UTC)
                previous.superseded_by_id = doc.id
        await self._session.commit()
        await self._session.refresh(doc)
        return doc

    async def update(
        self,
        user_id: UUID,
        document_id: UUID,
        payload: UserDocumentUpdateRequest,
    ) -> UserDocument:
        doc = await self._docs.get_owned(document_id, user_id)
        if doc is None:
            raise NotFoundError("User document not found")
        if payload.document_number is not None:
            doc.document_number = payload.document_number
        if payload.expires_at is not None:
            doc.expires_at = payload.expires_at
        await self._session.commit()
        await self._session.refresh(doc)
        return doc

    async def delete(self, user_id: UUID, document_id: UUID) -> None:
        doc = await self._docs.get_owned(document_id, user_id)
        if doc is None:
            raise NotFoundError("User document not found")
        await self._docs.soft_delete(doc)
        await self._session.commit()

    async def get_download_url(
        self, user_id: UUID, document_id: UUID,
    ) -> UserDocumentDownloadUrlResponse:
        doc = await self._docs.get_owned(document_id, user_id)
        if doc is None:
            raise NotFoundError("User document not found")
        bucket = self._settings.s3_documents_bucket
        if not bucket:
            raise ServiceUnavailableError("Document storage is not configured")
        ttl = 300
        url = await generate_presigned_get_url(
            bucket=bucket,
            object_key=doc.object_key,
            ttl_seconds=ttl,
            settings=self._settings,
        )
        return UserDocumentDownloadUrlResponse(
            document_id=doc.id, download_url=url, expires_in_seconds=ttl,
        )
