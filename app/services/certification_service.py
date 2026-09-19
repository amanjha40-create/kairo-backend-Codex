"""Certification service — metadata CRUD + optional S3 document upload."""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
from botocore.exceptions import ClientError
from jwt.exceptions import InvalidTokenError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationAppError,
)
from app.infrastructure.s3.presign import (
    generate_presigned_get_url,
    generate_presigned_put_url,
    head_object_meta,
)
from app.models.certification import Certification
from app.repositories.certification import CertificationRepository
from app.schemas.certification import (
    CertificationCreateRequest,
    CertificationDocumentCompleteUploadRequest,
    CertificationDocumentUploadIntentRequest,
    CertificationDocumentUploadIntentResponse,
    CertificationDownloadUrlResponse,
    CertificationUpdateRequest,
    CertificationUploadIntentRequest,
    CertificationUploadIntentResponse,
)

_DOCUMENT_UPLOAD_TOKEN_TYPE = "certification_document_upload"
_DOCUMENT_UPLOAD_TTL_SECONDS = 900


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
            credential_url=str(payload.credential_url) if payload.credential_url else None,
            verification_status=Certification.SELF_DECLARED_STATUS,
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
            credential_url=str(payload.credential_url) if payload.credential_url else None,
            object_key=object_key,
            original_filename=payload.original_filename,
            content_type=payload.content_type,
            byte_size=payload.byte_size,
            checksum_sha256="",
            verification_status=Certification.SELF_DECLARED_STATUS,
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

    async def create_document_upload_intent(
        self,
        user_id: UUID,
        cert_id: UUID,
        payload: CertificationDocumentUploadIntentRequest,
    ) -> CertificationDocumentUploadIntentResponse:
        item = await self._repo.get_owned(cert_id, user_id)
        if item is None:
            raise NotFoundError("Certification not found")

        bucket = self._settings.s3_documents_bucket
        if not bucket:
            raise ServiceUnavailableError("Document storage is not configured")

        upload_id = uuid.uuid4()
        object_key = self._document_object_key(
            user_id=user_id,
            cert_id=cert_id,
            upload_id=upload_id,
            original_filename=payload.original_filename,
        )
        upload_token = self._build_document_upload_token(
            user_id=user_id,
            cert_id=cert_id,
            upload_id=upload_id,
            payload=payload,
            base_revision=self._attachment_revision(item),
        )
        upload_url = await generate_presigned_put_url(
            bucket=bucket,
            object_key=object_key,
            content_type=payload.content_type,
            ttl_seconds=_DOCUMENT_UPLOAD_TTL_SECONDS,
            settings=self._settings,
        )
        return CertificationDocumentUploadIntentResponse(
            upload_url=upload_url,
            upload_token=upload_token,
            expires_in_seconds=_DOCUMENT_UPLOAD_TTL_SECONDS,
            headers_required={"Content-Type": payload.content_type},
        )

    async def complete_document_upload(
        self,
        user_id: UUID,
        cert_id: UUID,
        payload: CertificationDocumentCompleteUploadRequest,
    ) -> Certification:
        claims = self._decode_document_upload_token(payload.upload_token)
        if claims["user_id"] != user_id:
            raise ForbiddenError("Certification document upload is not authorized")
        if claims["certification_id"] != cert_id:
            raise ValidationAppError("Upload token does not match this certification")
        if not hmac.compare_digest(claims["checksum_sha256"], payload.checksum_sha256):
            raise ValidationAppError("Document checksum does not match the upload intent")

        item = await self._repo.get_owned_for_update(cert_id, user_id)
        if item is None:
            raise NotFoundError("Certification not found")

        object_key = self._document_object_key(
            user_id=user_id,
            cert_id=cert_id,
            upload_id=claims["upload_id"],
            original_filename=claims["original_filename"],
        )
        if self._matches_completed_upload(item, object_key, claims):
            return item
        if not hmac.compare_digest(claims["base_revision"], self._attachment_revision(item)):
            raise ConflictError(
                "Certification document changed; request a new upload before replacing it"
            )

        bucket = self._settings.s3_documents_bucket
        if not bucket:
            raise ServiceUnavailableError("Document storage is not configured")
        try:
            metadata = await head_object_meta(
                bucket=bucket,
                object_key=object_key,
                settings=self._settings,
            )
        except ClientError as exc:
            raise ValidationAppError("Uploaded certificate document could not be verified") from exc

        if int(metadata.get("ContentLength", -1)) != claims["byte_size"]:
            raise ValidationAppError("Uploaded certificate document size does not match")
        stored_content_type = str(metadata.get("ContentType") or "").strip().lower()
        if stored_content_type != claims["content_type"]:
            raise ValidationAppError("Uploaded certificate document type does not match")

        item.object_key = object_key
        item.original_filename = claims["original_filename"]
        item.content_type = claims["content_type"]
        item.byte_size = claims["byte_size"]
        item.checksum_sha256 = claims["checksum_sha256"]
        try:
            await self._session.commit()
            await self._session.refresh(item)
        except Exception:
            await self._session.rollback()
            raise
        return item

    async def detach_document(self, user_id: UUID, cert_id: UUID) -> Certification:
        item = await self._repo.get_owned_for_update(cert_id, user_id)
        if item is None:
            raise NotFoundError("Certification not found")
        if not any(
            (
                item.object_key,
                item.original_filename,
                item.content_type,
                item.byte_size,
                item.checksum_sha256,
            )
        ):
            return item

        item.object_key = None
        item.original_filename = None
        item.content_type = None
        item.byte_size = None
        item.checksum_sha256 = None
        try:
            await self._session.commit()
            await self._session.refresh(item)
        except Exception:
            await self._session.rollback()
            raise
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
        data = payload.model_dump(exclude_unset=True)
        if data.get("credential_url") is not None:
            data["credential_url"] = str(data["credential_url"])
        for field, value in data.items():
            setattr(item, field, value)
        await self._session.commit()
        await self._session.refresh(item)
        return item

    async def content(self, user_id: UUID, cert_id: UUID):
        from app.services.private_document_content import private_document_content

        item = await self._repo.get_owned(cert_id, user_id)
        if item is None:
            raise NotFoundError("Certification not found")
        return await private_document_content(
            self._settings, item,
            completed=bool(item.checksum_sha256 and item.checksum_sha256 != "0" * 64),
        )

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

    def _document_object_key(
        self,
        *,
        user_id: UUID,
        cert_id: UUID,
        upload_id: UUID,
        original_filename: str,
    ) -> str:
        prefix = self._settings.s3_document_key_prefix.rstrip("/")
        return (
            f"{prefix}/certifications/{user_id}/{cert_id}/"
            f"{upload_id.hex}/{original_filename}"
        )

    def _build_document_upload_token(
        self,
        *,
        user_id: UUID,
        cert_id: UUID,
        upload_id: UUID,
        payload: CertificationDocumentUploadIntentRequest,
        base_revision: str,
    ) -> str:
        now = datetime.now(tz=UTC)
        claims: dict[str, Any] = {
            "sub": str(user_id),
            "type": _DOCUMENT_UPLOAD_TOKEN_TYPE,
            "certification_id": str(cert_id),
            "upload_id": str(upload_id),
            "original_filename": payload.original_filename,
            "content_type": payload.content_type,
            "byte_size": payload.byte_size,
            "checksum_sha256": payload.checksum_sha256,
            "base_revision": base_revision,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=_DOCUMENT_UPLOAD_TTL_SECONDS)).timestamp()),
        }
        return jwt.encode(
            claims,
            self._settings.jwt_secret_key,
            algorithm=self._settings.jwt_algorithm,
        )

    def _decode_document_upload_token(self, upload_token: str) -> dict[str, Any]:
        try:
            claims = jwt.decode(
                upload_token,
                self._settings.jwt_secret_key,
                algorithms=[self._settings.jwt_algorithm],
                options={"require": ["exp", "sub"]},
            )
            if claims.get("type") != _DOCUMENT_UPLOAD_TOKEN_TYPE:
                raise ValueError("wrong token type")
            parsed = {
                "user_id": UUID(str(claims["sub"])),
                "certification_id": UUID(str(claims["certification_id"])),
                "upload_id": UUID(str(claims["upload_id"])),
                "original_filename": str(claims["original_filename"]),
                "content_type": str(claims["content_type"]),
                "byte_size": int(claims["byte_size"]),
                "checksum_sha256": str(claims["checksum_sha256"]),
                "base_revision": str(claims["base_revision"]),
            }
        except (InvalidTokenError, KeyError, TypeError, ValueError) as exc:
            raise ValidationAppError("Invalid or expired certification upload token") from exc
        return parsed

    @staticmethod
    def _attachment_revision(item: Certification) -> str:
        value = "\x1f".join(
            (
                item.object_key or "",
                item.original_filename or "",
                item.content_type or "",
                str(item.byte_size) if item.byte_size is not None else "",
                item.checksum_sha256 or "",
            )
        )
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _matches_completed_upload(
        item: Certification,
        object_key: str,
        claims: dict[str, Any],
    ) -> bool:
        return (
            item.object_key == object_key
            and item.original_filename == claims["original_filename"]
            and item.content_type == claims["content_type"]
            and item.byte_size == claims["byte_size"]
            and item.checksum_sha256 == claims["checksum_sha256"]
        )
