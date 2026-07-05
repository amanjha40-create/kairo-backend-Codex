"""Generic document upload for internships and freelance contracts.

Reuses the same S3 infrastructure as employment documents.
"""

from __future__ import annotations

import uuid
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.employment.constants import PENDING_UPLOAD_CHECKSUM_HEX
from app.exceptions import NotFoundError, EmploymentCaseNotFoundError
from app.infrastructure.s3.paths import (
    build_user_internship_document_key,
    build_user_freelance_document_key,
    sanitize_filename_for_storage,
)
from app.infrastructure.s3.presign import generate_presigned_get_url, generate_presigned_put_url
from app.infrastructure.s3.service import S3UploadService
from app.models.internship import Internship
from app.models.freelance_contract import FreelanceContract
from app.models.internship_document import InternshipDocument
from app.models.freelance_contract_document import FreelanceContractDocument

_GET_TTL = 7 * 24 * 60 * 60  # 7 days


class DocUploadIntentRequest(BaseModel):
    document_type: str
    original_filename: str
    content_type: str
    byte_size: int


class DocUploadIntentResponse(BaseModel):
    document_id: uuid.UUID
    upload_url: str
    expires_in_seconds: int


class DocCompleteRequest(BaseModel):
    checksum_sha256: str


class DocResponse(BaseModel):
    id: uuid.UUID
    document_type: str
    original_filename: str
    byte_size: int
    content_type: str
    verification_status: str
    download_url: str | None = None


OwnerKind = Literal["internship", "freelance"]


class SecondaryDocService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._storage = S3UploadService(settings)

    async def _internship_owned(self, internship_id: UUID, user_id: UUID) -> Internship:
        row = (await self._session.execute(
            select(Internship).where(
                Internship.id == internship_id,
                Internship.user_id == user_id,
                Internship.deleted_at.is_(None),
            )
        )).scalar_one_or_none()
        if not row:
            raise EmploymentCaseNotFoundError()
        return row

    async def _freelance_owned(self, freelance_id: UUID, user_id: UUID) -> FreelanceContract:
        row = (await self._session.execute(
            select(FreelanceContract).where(
                FreelanceContract.id == freelance_id,
                FreelanceContract.user_id == user_id,
                FreelanceContract.deleted_at.is_(None),
            )
        )).scalar_one_or_none()
        if not row:
            raise EmploymentCaseNotFoundError()
        return row

    async def _signed_get(self, object_key: str) -> str | None:
        bucket = self._settings.s3_documents_bucket
        if not bucket:
            return None
        try:
            return await generate_presigned_get_url(
                bucket=bucket, object_key=object_key, ttl_seconds=_GET_TTL, settings=self._settings
            )
        except Exception:
            return None

    # ---- Internship documents ----

    async def create_internship_upload_intent(
        self, user_id: UUID, internship_id: UUID, payload: DocUploadIntentRequest,
    ) -> DocUploadIntentResponse:
        self._storage.validate_declaration(byte_size=payload.byte_size, content_type=payload.content_type)
        await self._internship_owned(internship_id, user_id)

        safe_name = sanitize_filename_for_storage(payload.original_filename)
        doc_id = uuid.uuid4()
        object_key = build_user_internship_document_key(
            owner_user_id=user_id,
            internship_id=internship_id,
            document_id=doc_id,
            safe_filename=safe_name,
            prefix=self._settings.s3_document_key_prefix,
        )

        doc = InternshipDocument(
            id=doc_id,
            internship_id=internship_id,
            uploaded_by_user_id=user_id,
            document_type=payload.document_type,
            object_key=object_key,
            original_filename=safe_name,
            content_type=payload.content_type,
            byte_size=payload.byte_size,
            checksum_sha256=PENDING_UPLOAD_CHECKSUM_HEX,
            verification_status="pending_upload",
        )
        self._session.add(doc)

        bucket = self._settings.s3_documents_bucket
        assert bucket
        upload_url = await generate_presigned_put_url(
            bucket=bucket, object_key=object_key, content_type=payload.content_type,
            ttl_seconds=self._settings.s3_presigned_put_ttl_seconds, settings=self._settings,
        )
        await self._session.commit()

        return DocUploadIntentResponse(document_id=doc_id, upload_url=upload_url, expires_in_seconds=self._settings.s3_presigned_put_ttl_seconds)

    async def complete_internship_upload(
        self, user_id: UUID, internship_id: UUID, doc_id: UUID, payload: DocCompleteRequest,
    ) -> None:
        await self._internship_owned(internship_id, user_id)
        doc = (await self._session.execute(
            select(InternshipDocument).where(
                InternshipDocument.id == doc_id,
                InternshipDocument.internship_id == internship_id,
                InternshipDocument.deleted_at.is_(None),
            )
        )).scalar_one_or_none()
        if not doc:
            raise NotFoundError("Document not found")
        doc.checksum_sha256 = payload.checksum_sha256
        doc.verification_status = "pending_review"
        await self._session.commit()

    async def list_internship_documents(self, user_id: UUID, internship_id: UUID) -> list[DocResponse]:
        await self._internship_owned(internship_id, user_id)
        rows = (await self._session.execute(
            select(InternshipDocument).where(
                InternshipDocument.internship_id == internship_id,
                InternshipDocument.deleted_at.is_(None),
                InternshipDocument.checksum_sha256 != PENDING_UPLOAD_CHECKSUM_HEX,
            )
        )).scalars().all()
        result = []
        for r in rows:
            url = await self._signed_get(r.object_key)
            result.append(DocResponse(
                id=r.id, document_type=r.document_type, original_filename=r.original_filename,
                byte_size=r.byte_size, content_type=r.content_type,
                verification_status=r.verification_status, download_url=url,
            ))
        return result

    async def delete_internship_document(self, user_id: UUID, internship_id: UUID, doc_id: UUID) -> None:
        await self._internship_owned(internship_id, user_id)
        doc = (await self._session.execute(
            select(InternshipDocument).where(
                InternshipDocument.id == doc_id,
                InternshipDocument.internship_id == internship_id,
                InternshipDocument.deleted_at.is_(None),
            )
        )).scalar_one_or_none()
        if not doc:
            raise NotFoundError("Document not found")
        from datetime import datetime, timezone
        doc.deleted_at = datetime.now(timezone.utc)
        await self._session.commit()

    # ---- Freelance contract documents ----

    async def create_freelance_upload_intent(
        self, user_id: UUID, freelance_id: UUID, payload: DocUploadIntentRequest,
    ) -> DocUploadIntentResponse:
        self._storage.validate_declaration(byte_size=payload.byte_size, content_type=payload.content_type)
        await self._freelance_owned(freelance_id, user_id)

        safe_name = sanitize_filename_for_storage(payload.original_filename)
        doc_id = uuid.uuid4()
        object_key = build_user_freelance_document_key(
            owner_user_id=user_id,
            freelance_contract_id=freelance_id,
            document_id=doc_id,
            safe_filename=safe_name,
            prefix=self._settings.s3_document_key_prefix,
        )

        doc = FreelanceContractDocument(
            id=doc_id,
            freelance_contract_id=freelance_id,
            uploaded_by_user_id=user_id,
            document_type=payload.document_type,
            object_key=object_key,
            original_filename=safe_name,
            content_type=payload.content_type,
            byte_size=payload.byte_size,
            checksum_sha256=PENDING_UPLOAD_CHECKSUM_HEX,
            verification_status="pending_upload",
        )
        self._session.add(doc)

        bucket = self._settings.s3_documents_bucket
        assert bucket
        upload_url = await generate_presigned_put_url(
            bucket=bucket, object_key=object_key, content_type=payload.content_type,
            ttl_seconds=self._settings.s3_presigned_put_ttl_seconds, settings=self._settings,
        )
        await self._session.commit()

        return DocUploadIntentResponse(document_id=doc_id, upload_url=upload_url, expires_in_seconds=self._settings.s3_presigned_put_ttl_seconds)

    async def complete_freelance_upload(
        self, user_id: UUID, freelance_id: UUID, doc_id: UUID, payload: DocCompleteRequest,
    ) -> None:
        await self._freelance_owned(freelance_id, user_id)
        doc = (await self._session.execute(
            select(FreelanceContractDocument).where(
                FreelanceContractDocument.id == doc_id,
                FreelanceContractDocument.freelance_contract_id == freelance_id,
                FreelanceContractDocument.deleted_at.is_(None),
            )
        )).scalar_one_or_none()
        if not doc:
            raise NotFoundError("Document not found")
        doc.checksum_sha256 = payload.checksum_sha256
        doc.verification_status = "pending_review"
        await self._session.commit()

    async def list_freelance_documents(self, user_id: UUID, freelance_id: UUID) -> list[DocResponse]:
        await self._freelance_owned(freelance_id, user_id)
        rows = (await self._session.execute(
            select(FreelanceContractDocument).where(
                FreelanceContractDocument.freelance_contract_id == freelance_id,
                FreelanceContractDocument.deleted_at.is_(None),
                FreelanceContractDocument.checksum_sha256 != PENDING_UPLOAD_CHECKSUM_HEX,
            )
        )).scalars().all()
        result = []
        for r in rows:
            url = await self._signed_get(r.object_key)
            result.append(DocResponse(
                id=r.id, document_type=r.document_type, original_filename=r.original_filename,
                byte_size=r.byte_size, content_type=r.content_type,
                verification_status=r.verification_status, download_url=url,
            ))
        return result

    async def delete_freelance_document(self, user_id: UUID, freelance_id: UUID, doc_id: UUID) -> None:
        await self._freelance_owned(freelance_id, user_id)
        doc = (await self._session.execute(
            select(FreelanceContractDocument).where(
                FreelanceContractDocument.id == doc_id,
                FreelanceContractDocument.freelance_contract_id == freelance_id,
                FreelanceContractDocument.deleted_at.is_(None),
            )
        )).scalar_one_or_none()
        if not doc:
            raise NotFoundError("Document not found")
        from datetime import datetime, timezone
        doc.deleted_at = datetime.now(timezone.utc)
        await self._session.commit()
