"""Selected-document shares with hash-only credentials and revocation-aware access."""

import hashlib
import hmac
import logging
import re
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.exceptions import NotFoundError, ValidationAppError
from app.models import DocumentSharePack, DocumentSharePackItem, User
from app.schemas.document_share_pack import (
    DocumentPackCreated,
    DocumentPackResponse,
    PublicDocumentPack,
    PublicPackItem,
)
from app.services.document_pack_sources import DocumentPackSources
from app.services.document_pack_storage import DocumentPackStorage

logger = logging.getLogger(__name__)


class DocumentSharePackService:
    def __init__(self, session, settings):
        self.session, self.settings = session, settings
        self.storage = DocumentPackStorage(settings)
        self.sources = DocumentPackSources(session, settings, self.storage)

    @staticmethod
    def state(pack):
        if pack.revoked_at:
            return "revoked"
        return "expired" if pack.expires_at <= datetime.now(UTC) else "active"

    @staticmethod
    def public(pack):
        return PublicDocumentPack(
            purpose=pack.purpose,
            expires_at=pack.expires_at,
            document_count=len(pack.items),
            items=[PublicPackItem.model_validate(item) for item in pack.items],
        )

    def response(self, pack):
        return DocumentPackResponse(
            **self.public(pack).model_dump(),
            public_id=pack.public_id,
            created_at=pack.created_at,
            revoked_at=pack.revoked_at,
            status=self.state(pack),
            view_count=pack.view_count,
            last_viewed_at=pack.last_viewed_at,
        )

    async def create(self, owner, payload):
        now = datetime.now(UTC)
        token = secrets.token_urlsafe(32)
        pack = DocumentSharePack(
            id=uuid4(),
            public_id=uuid4(),
            owner_user_id=owner,
            purpose=payload.purpose,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            created_at=now,
            expires_at=now + timedelta(days=payload.expiry_days),
            view_count=0,
            revoked_at=None,
            last_viewed_at=None,
            items=[],
        )
        copied = []
        try:
            # Lock in stable order to avoid deadlocks with simultaneous selections.
            resolved = []
            for selection in sorted(payload.items, key=lambda s: (s.source_type, str(s.source_id))):
                resolved.append(await self.sources.resolve(owner, selection))
            if sum(binding.size for _, _, binding in resolved) > 200 * 1024 * 1024:
                raise ValidationAppError("A document pack may contain up to 200 MB")
            seen_objects = set()
            for source, dto, binding in resolved:
                identity = (binding.key, binding.version, binding.etag)
                if identity in seen_objects:
                    raise ValidationAppError("The same file cannot be shared twice in a pack")
                seen_objects.add(identity)
                item_id = uuid4()
                key = f"{self.settings.s3_document_key_prefix.rstrip('/')}/document-share-packs/{pack.id}/{item_id}"
                binding = await self.storage.snapshot(binding, key)
                if binding.owns_snapshot:
                    copied.append(binding)
                pack.items.append(
                    DocumentSharePackItem(
                        id=uuid4(),
                        public_id=item_id,
                        source_type=source.kind,
                        source_id=source.row.id,
                        category=dto.category,
                        title=dto.title,
                        context=dto.context,
                        filename=dto.filename,
                        content_type=dto.content_type,
                        byte_size=dto.byte_size,
                        checksum_sha256=getattr(source.row, "checksum_sha256", None),
                        object_key=binding.key,
                        object_version=binding.version,
                        object_etag=binding.etag,
                        owns_snapshot=binding.owns_snapshot,
                        created_at=now,
                    )
                )
            self.session.add(pack)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            for binding in copied:
                try:
                    await self.storage.delete_snapshot(binding)
                except Exception:
                    # Never log object keys, filenames, or bearer material.
                    logger.error("document_pack.snapshot_cleanup_failed")
            raise
        # A fragment keeps the credential out of frontend hosting access logs and referrers.
        origin = (
            self.settings.employer_portal_base_url or self.settings.app_public_base_url
        ).rstrip("/")
        return DocumentPackCreated(
            **self.response(pack).model_dump(), share_url=f"{origin}/document-pack#token={token}"
        )

    def query(self):
        return select(DocumentSharePack).options(selectinload(DocumentSharePack.items))

    async def owned(self, owner, public_id, *, lock=False):
        query = self.query().where(
            DocumentSharePack.owner_user_id == owner, DocumentSharePack.public_id == public_id
        )
        if lock:
            query = query.with_for_update()
        pack = (await self.session.execute(query)).scalar_one_or_none()
        if pack is None:
            raise NotFoundError("Document pack not found")
        return pack

    async def history(self, owner, *, offset=0, limit=20):
        total = await self.session.scalar(
            select(func.count())
            .select_from(DocumentSharePack)
            .where(DocumentSharePack.owner_user_id == owner)
        )
        packs = (
            (
                await self.session.execute(
                    self.query()
                    .where(DocumentSharePack.owner_user_id == owner)
                    .order_by(DocumentSharePack.created_at.desc(), DocumentSharePack.id)
                    .offset(offset)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return [self.response(pack) for pack in packs], total

    async def revoke(self, owner, public_id):
        pack = await self.owned(owner, public_id, lock=True)
        if pack.revoked_at is None:
            pack.revoked_at = datetime.now(UTC)
            await self.session.commit()
        return self.response(pack)

    async def resolve(self, token, *, lock=False):
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise NotFoundError("Document pack unavailable")
        query = (
            self.query()
            .join(User, User.id == DocumentSharePack.owner_user_id)
            .where(
                DocumentSharePack.token_hash == hashlib.sha256(token.encode()).hexdigest(),
                User.deleted_at.is_(None),
                User.is_active.is_(True),
            )
        )
        if lock:
            query = query.with_for_update(of=DocumentSharePack)
        pack = (await self.session.execute(query)).scalar_one_or_none()
        if pack is None or self.state(pack) != "active":
            raise NotFoundError("Document pack unavailable")
        return pack

    async def recipient(self, token):
        pack = await self.resolve(token, lock=True)
        pack.view_count += 1
        pack.last_viewed_at = datetime.now(UTC)
        result = self.public(pack)
        await self.session.commit()
        return result

    async def public_item(self, token, public_id):
        pack = await self.resolve(token)
        item = next((item for item in pack.items if item.public_id == public_id), None)
        if item is None or item.cleaned_at is not None:
            raise NotFoundError("Shared document unavailable")
        return pack, item

    def signature(self, token, item_id, expires):
        message = f"document-download\0{token}\0{item_id}\0{expires}"
        return hmac.new(
            self.settings.jwt_secret_key.encode(), message.encode(), hashlib.sha256
        ).hexdigest()

    async def download_url(self, token, item_id):
        pack, _ = await self.public_item(token, item_id)
        expires = min(int(datetime.now(UTC).timestamp()) + 60, int(pack.expires_at.timestamp()))
        signature = self.signature(token, item_id, expires)
        return {
            "download_url": f"/api/v1/public/document-share-packs/{token}/items/{item_id}/content?expires={expires}&signature={signature}",
            "expires_in_seconds": max(0, expires - int(datetime.now(UTC).timestamp())),
        }

    async def content(self, token, item_id, expires, signature):
        now = int(datetime.now(UTC).timestamp())
        if not now < expires <= now + 60 or not hmac.compare_digest(
            signature, self.signature(token, item_id, expires)
        ):
            raise NotFoundError("Shared document unavailable")
        _, item = await self.public_item(token, item_id)
        chunks, headers = await self.storage.open(item)
        return chunks, headers, item.content_type
