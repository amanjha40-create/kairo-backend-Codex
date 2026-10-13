"""Private document workflow, separate from GPS and canonical identity verification."""

import asyncio
import hashlib
import hmac
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select

from app.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationAppError,
)
from app.infrastructure.s3.presign import generate_presigned_put_url
from app.models.permanent_address import PermanentAddressDocument as Evidence
from app.models.permanent_address import PermanentAddressReview as Review
from app.models.permanent_address import PermanentAddressVersion as Version
from app.models.user import User
from app.models.user_account_event import UserAccountEvent
from app.models.user_document import UserDocument
from app.schemas.permanent_address import AddressDocumentState, AddressDocumentUploadResponse
from app.services.permanent_address_policy import calendar_day, count_days

TYPES = {
    "address_proof": "Address proof (bill, statement, lease or other accepted proof)",
    "driving_license": "Driving Licence",
    "passport": "Passport",
    "voter_id": "Voter ID",
    "government_id": "Government identity/address document",
}
OUTCOMES = {
    "APPROVE_MATCHING": "MATCH",
    "REJECT": "REJECTED",
    "REQUEST_CORRECTION": "NEEDS_CORRECTION",
    "REQUEST_DIFFERENT_DOCUMENT": "NEEDS_CORRECTION",
}


class AddressDocumentMixin:
    def document_event(self, row, document_id, action, actor=None):
        self.db.add(
            UserAccountEvent(
                user_id=row.user_id,
                actor_user_id=actor or row.user_id,
                event_type="permanent_address_document",
                title="Address document event",
                metadata_payload={
                    "address_version_id": str(row.id),
                    "document_id": str(document_id),
                    "action": action,
                },
            )
        )

    def document_types(self):
        self.require_enabled()
        return {
            "items": [
                {
                    "value": kind,
                    "label": label,
                    "max_age_days": self.settings.permanent_address_document_max_age_days.get(kind),
                }
                for kind, label in TYPES.items()
            ],
            "allowed_content_types": ["application/pdf", "image/jpeg", "image/png", "image/webp"],
            "max_bytes": 50 * 1024 * 1024,
        }

    def check_document_freshness(self, doc, evidence):
        today = calendar_day(self.clock())
        if doc.expires_at and doc.expires_at < today:
            raise ValidationAppError("Document has expired")
        issued = evidence.issued_on if evidence else None
        maximum = self.settings.permanent_address_document_max_age_days.get(doc.document_type)
        if issued and issued > today:
            raise ValidationAppError("Document issue date cannot be in the future")
        if maximum is not None and (maximum <= 0 or not issued or (today - issued).days > maximum):
            raise ValidationAppError("Document does not meet the configured freshness policy")

    async def document_record(self, doc_id):
        return await self.db.scalar(select(Evidence).where(Evidence.document_id == doc_id))

    async def document_state(self, owner, version_id):
        self.require_enabled()
        row = await self.active(owner, version_id)
        latest = await self.db.scalar(
            select(Evidence)
            .where(Evidence.address_version_id == row.id)
            .order_by(Evidence.created_at.desc(), Evidence.id)
            .limit(1)
        )
        if latest is None:
            return AddressDocumentState(document_id=row.document_id, status=row.document_status)
        doc = await self.db.get(UserDocument, latest.document_id)
        status = latest.status
        if doc is None or doc.deleted_at or doc.superseded_at:
            status = "REQUIRED"
        elif status == "UPLOADING" and latest.upload_expires_at <= self.clock():
            status = "NEEDS_CORRECTION"
        elif status not in {"UPLOADING", "SUPERSEDED"}:
            try:
                self.check_document_freshness(doc, latest)
                if await self.document_binding(doc) != latest.binding:
                    status = "NEEDS_CORRECTION"
            except (NotFoundError, ServiceUnavailableError, ValidationAppError):
                status = "NEEDS_CORRECTION"
            if doc.verification_status not in {"pending", "approved"} or not doc.checksum_sha256:
                status = "NEEDS_CORRECTION"
            if latest.document_id == row.document_id and status != "NEEDS_CORRECTION":
                status = {
                    "NEEDS_REVIEW": "UNDER_REVIEW",
                    "MISMATCH": "REJECTED",
                }.get(row.document_status, row.document_status)
        return AddressDocumentState(
            document_id=latest.document_id,
            document_type=doc.document_type if doc else None,
            status=status,
            uploaded_at=latest.uploaded_at,
            issued_on=latest.issued_on,
        )

    async def upload_address_document(self, owner, payload):
        self.require_enabled()
        row = await self.active(owner, payload.address_version_id)
        if row.completed_at or row.document_status == "MATCH":
            raise ConflictError("The current address document is already approved")
        if payload.document_type.value not in TYPES:
            raise ValidationAppError("Select an accepted address document type")
        if not self.settings.s3_documents_bucket:
            raise ServiceUnavailableError("Document storage is unavailable")
        identifier = uuid4()
        prefix = self.settings.s3_document_key_prefix.rstrip("/")
        doc = UserDocument(
            id=identifier,
            user_id=owner,
            document_type=payload.document_type.value,
            object_key=f"{prefix}/user-documents/{owner}/{identifier}/address-proof",
            original_filename=payload.original_filename,
            content_type=payload.content_type,
            byte_size=payload.byte_size,
            checksum_sha256="",
            verification_status="pending",
            expires_at=payload.expires_at,
        )
        ttl = self.settings.s3_presigned_put_ttl_seconds
        evidence = Evidence(
            id=uuid4(),
            address_version_id=row.id,
            document_id=identifier,
            status="UPLOADING",
            upload_expires_at=self.clock() + timedelta(seconds=ttl),
            issued_on=payload.issued_on,
        )
        self.check_document_freshness(doc, evidence)
        url = await generate_presigned_put_url(
            bucket=self.settings.s3_documents_bucket,
            object_key=doc.object_key,
            content_type=doc.content_type,
            ttl_seconds=ttl,
            settings=self.settings,
        )
        self.db.add(doc)
        await self.db.flush()
        self.db.add(evidence)
        self.document_event(row, doc.id, "upload_started")
        await self.db.commit()
        return AddressDocumentUploadResponse(
            document_id=doc.id,
            upload_url=url,
            expires_in_seconds=ttl,
            headers_required={"Content-Type": doc.content_type},
        )

    async def complete_address_document(self, owner, document_id, payload):
        self.require_enabled()
        row = await self.active(owner, payload.address_version_id)
        evidence = await self.document_record(document_id)
        doc = await self.db.get(UserDocument, document_id)
        if (
            evidence is None
            or evidence.address_version_id != row.id
            or doc is None
            or doc.user_id != owner
            or doc.deleted_at
            or doc.superseded_at
        ):
            raise NotFoundError()
        if evidence.status != "UPLOADING":
            if doc.checksum_sha256 == payload.checksum_sha256 and evidence.uploaded_at:
                return await self.document_state(owner, row.id)
            raise ConflictError("Document upload is no longer current")
        if evidence.upload_expires_at <= self.clock():
            raise ConflictError("Upload expired; choose the file again")
        self.check_document_freshness(doc, evidence)
        binding = await self.document_binding(doc)
        item = SimpleNamespace(
            object_key=doc.object_key,
            object_version=binding["version"],
            object_etag=binding["etag"],
            byte_size=doc.byte_size,
            filename="address-proof",
        )
        chunks, _ = await self.storage.open(item)

        def validate():
            digest, total, header = hashlib.sha256(), 0, b""
            try:
                for chunk in chunks:
                    total += len(chunk)
                    if total > doc.byte_size:
                        raise ValidationAppError("Document size does not match the upload")
                    header = (header + chunk)[:16]
                    digest.update(chunk)
            finally:
                close = getattr(chunks, "close", None)
                if close:
                    close()
            signatures = {
                "application/pdf": header.startswith(b"%PDF-"),
                "image/jpeg": header.startswith(b"\xff\xd8\xff"),
                "image/png": header.startswith(b"\x89PNG\r\n\x1a\n"),
                "image/webp": header.startswith(b"RIFF") and header[8:12] == b"WEBP",
            }
            if (
                total != doc.byte_size
                or not signatures.get(doc.content_type)
                or not hmac.compare_digest(digest.hexdigest(), payload.checksum_sha256)
            ):
                raise ValidationAppError("Document format or checksum does not match the upload")

        await asyncio.to_thread(validate)
        doc.checksum_sha256 = payload.checksum_sha256
        evidence.binding, evidence.uploaded_at, evidence.status = binding, self.clock(), "UPLOADED"
        self.document_event(row, doc.id, "uploaded")
        await self.db.commit()
        return await self.document_state(owner, row.id)

    async def bind_address_document(self, row, doc, binding):
        evidence = await self.document_record(doc.id)
        if evidence is not None and (
            evidence.address_version_id != row.id or evidence.status == "UPLOADING"
        ):
            raise ConflictError("Document must be completed for this address version")
        if evidence is None:
            # Legacy Vault attachment still receives an immutable version binding.
            old_version = await self.db.scalar(
                select(Version.id).where(Version.document_id == doc.id, Version.id != row.id)
            )
            if old_version:
                raise ConflictError("Document belongs to another address version")
            evidence = Evidence(
                address_version_id=row.id,
                document_id=doc.id,
                uploaded_at=self.clock(),
                status="UPLOADED",
                binding=binding,
            )
            self.db.add(evidence)
        self.check_document_freshness(doc, evidence)
        if evidence.binding != binding:
            raise ConflictError("Document changed; upload it again")
        previous = await self.document_record(row.document_id) if row.document_id else None
        if previous and previous.document_id != doc.id:
            previous.status = "SUPERSEDED"
            self.document_event(row, previous.document_id, "replaced")
        evidence.status, evidence.submitted_at = "UNDER_REVIEW", self.clock()
        self.document_event(row, doc.id, "submitted")

    async def submit_address_document(self, owner, payload):
        self.require_enabled()
        row = await self.active(owner, payload.address_version_id)
        if row.completed_at or (
            row.document_status == "MATCH" and row.document_id != payload.document_id
        ):
            raise ConflictError("The current address document is already approved")
        return await self.attach_evidence(owner, payload)

    async def decide_address_document(self, reviewer, version_id, payload):
        await self.manual_actor(reviewer)
        row = await self.db.get(Version, version_id)
        if row is None:
            raise NotFoundError()
        if row.user_id == reviewer:
            raise ForbiddenError("Self-review is not permitted")
        row = await self.active(row.user_id, version_id)
        await self.db.refresh(row)
        digest = hashlib.sha256(payload.model_dump_json().encode()).hexdigest()
        receipt = await self.db.scalar(
            select(Review).where(
                Review.address_version_id == row.id,
                Review.idempotency_key == payload.idempotency_key,
            )
        )
        if receipt:
            if receipt.request_digest != digest or receipt.reviewer_id != reviewer:
                raise ConflictError("Review request key was already used")
            return {"document_status": receipt.outcome, "reviewed_at": receipt.created_at}
        doc = await self.evidence_valid(row.user_id, row)
        if doc is None or doc.id != payload.document_id:
            raise ConflictError("Address evidence is no longer eligible")
        evidence = await self.document_record(doc.id)
        if evidence is None or not (
            evidence.status in {"UNDER_REVIEW", "NEEDS_CORRECTION"}
            or (evidence.status == "MATCH" and row.document_status == "NEEDS_REVIEW")
        ):
            raise ConflictError("Document is not awaiting review")
        if payload.outcome == "APPROVE_MATCHING" and not (
            payload.candidate_identity_matches
            and payload.document_acceptable
            and payload.address_matches
        ):
            raise ValidationAppError(
                "Explicit identity, document and address review confirmation required"
            )
        outcome = OUTCOMES[payload.outcome]
        evidence.status = row.document_status = outcome
        receipt = Review(
            address_version_id=row.id,
            reviewer_id=reviewer,
            document_id=doc.id,
            document_checksum=doc.checksum_sha256,
            outcome=outcome,
            idempotency_key=payload.idempotency_key,
            request_digest=digest,
            created_at=self.clock(),
        )
        self.db.add(receipt)
        row.completed_at = None
        sessions = await self.sessions(row)
        if (
            outcome == "MATCH"
            and count_days(
                [s.counted_day for s in sessions if s.counted_day],
                row.window_started_at,
                self.clock(),
            )
            >= 3
        ):
            row.completed_at = self.clock()
        self.document_event(row, doc.id, payload.outcome.lower(), reviewer)
        await self.db.commit()
        return {"document_status": outcome, "reviewed_at": receipt.created_at}

    async def document_review_projection(self, reviewer, version_id):
        detail = await self.review_detail(reviewer, version_id)
        row = await self.db.get(Version, version_id)
        doc = await self.db.get(UserDocument, row.document_id)
        user = await self.db.get(User, row.user_id)
        evidence = await self.document_record(doc.id)
        history = (
            await self.db.scalars(
                select(Review)
                .where(Review.address_version_id == row.id)
                .order_by(Review.created_at)
            )
        ).all()
        events = (
            await self.db.scalars(
                select(UserAccountEvent)
                .where(
                    UserAccountEvent.user_id == row.user_id,
                    UserAccountEvent.event_type == "permanent_address_document",
                    UserAccountEvent.metadata_payload["address_version_id"].astext == str(row.id),
                )
                .order_by(UserAccountEvent.created_at)
            )
        ).all()
        return {
            **detail,
            "candidate_id": row.user_id,
            "candidate_name": user.full_name,
            "address_version": row.version,
            "upload_state": evidence.status if evidence else "UNDER_REVIEW",
            "uploaded_at": evidence.uploaded_at if evidence else doc.created_at,
            "issued_on": evidence.issued_on if evidence else None,
            "expires_at": doc.expires_at,
            "content_path": f"/api/v1/permanent-address/reviews/{row.id}/content",
            "reviews": [
                {
                    "outcome": r.outcome,
                    "reviewed_by": r.reviewer_id,
                    "reviewed_at": r.created_at,
                    "document_id": r.document_id,
                }
                for r in history
            ],
            "audit": [{"action": e.metadata_payload["action"], "at": e.created_at} for e in events],
        }
