"""Certification service — metadata CRUD + optional S3 document upload."""

from __future__ import annotations

import uuid
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.exceptions import NotFoundError, ServiceUnavailableError
from app.infrastructure.s3.presign import generate_presigned_get_url, generate_presigned_put_url
from app.models.certification import Certification
from app.repositories.certification import CertificationRepository
from app.schemas.certification import (
    CertificationCreateRequest,
    CertificationDownloadUrlResponse,
    CertificationUpdateRequest,
    CertificationUploadIntentRequest,
    CertificationUploadIntentResponse,
)


class CertificationService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._repo = CertificationRepository(session)
        self._settings = settings or get_settings()

    async def create(self, user_id: UUID, payload: CertificationCreateRequest) -> Certification:
        item = Certification(
            user_id=user_id,
            title=payload.title,
            issuing_organization=payload.issuing_organization,
            issued_date=payload.issued_date,
            expiry_date=payload.expiry_date,
            does_not_expire=payload.does_not_expire,
            credential_id=payload.credential_id,
            credential_url=payload.credential_url,
        )
        result = await self._repo.create(item)
        await self._session.commit()
        await self._session.refresh(result)
        return result

    async def create_upload_intent(
        self, user_id: UUID, payload: CertificationUploadIntentRequest,
    ) -> CertificationUploadIntentResponse:
        bucket = self._settings.s3_documents_bucket
        if not bucket:
            raise ServiceUnavailableError("Document storage is not configured")

        cert_id = uuid.uuid4()
        prefix = self._settings.s3_document_key_prefix.rstrip("/")
        object_key = (
            f"{prefix}/certifications/{user_id}/{cert_id}/{payload.original_filename}"
        )

        item = Certification(
            id=cert_id,
            user_id=user_id,
            title=payload.title,
            issuing_organization=payload.issuing_organization,
            issued_date=payload.issued_date,
            expiry_date=payload.expiry_date,
            does_not_expire=payload.does_not_expire,
            credential_id=payload.credential_id,
            credential_url=payload.credential_url,
            object_key=object_key,
            original_filename=payload.original_filename,
            content_type=payload.content_type,
            byte_size=payload.byte_size,
            checksum_sha256="",
        )
        await self._repo.create(item)
        await self._session.commit()

        upload_url = await generate_presigned_put_url(
            bucket=bucket,
            object_key=object_key,
            content_type=payload.content_type,
            ttl_seconds=900,
        )
        return CertificationUploadIntentResponse(
            certification_id=cert_id,
            upload_url=upload_url,
            object_key=object_key,
        )

    async def complete_upload(
        self, user_id: UUID, cert_id: UUID, checksum_sha256: str,
    ) -> Certification:
        item = await self._repo.get_owned(cert_id, user_id)
        if item is None:
            raise NotFoundError("Certification not found")
        item.checksum_sha256 = checksum_sha256
        await self._session.commit()
        await self._session.refresh(item)
        return item

    async def list_for_user(
        self, user_id: UUID, *, offset: int = 0, limit: int = 50,
    ) -> tuple[list[Certification], int]:
        return await self._repo.list_for_user(user_id, offset=offset, limit=limit)

    async def get_for_user(self, user_id: UUID, cert_id: UUID) -> Certification:
        item = await self._repo.get_owned(cert_id, user_id)
        if item is None:
            raise NotFoundError("Certification not found")
        return item

    async def update(
        self, user_id: UUID, cert_id: UUID, payload: CertificationUpdateRequest,
    ) -> Certification:
        item = await self._repo.get_owned(cert_id, user_id)
        if item is None:
            raise NotFoundError("Certification not found")
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(item, field, value)
        await self._session.commit()
        await self._session.refresh(item)
        return item

    async def get_download_url(
        self, user_id: UUID, cert_id: UUID,
    ) -> CertificationDownloadUrlResponse:
        item = await self._repo.get_owned(cert_id, user_id)
        if item is None:
            raise NotFoundError("Certification not found")
        if not item.object_key:
            raise NotFoundError("No document uploaded for this certification")
        bucket = self._settings.s3_documents_bucket
        if not bucket:
            raise ServiceUnavailableError("Document storage is not configured")
        url = await generate_presigned_get_url(bucket=bucket, object_key=item.object_key)
        return CertificationDownloadUrlResponse(download_url=url)

    async def delete(self, user_id: UUID, cert_id: UUID) -> None:
        item = await self._repo.get_owned(cert_id, user_id)
        if item is None:
            raise NotFoundError("Certification not found")
        await self._repo.soft_delete(item)
        await self._session.commit()
