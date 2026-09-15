"""Remove only expired/revoked pack-owned snapshots, never original source objects."""

import asyncio
from datetime import UTC, datetime

from sqlalchemy import or_, select

from app.models import DocumentSharePack, DocumentSharePackItem, User
from app.services.document_pack_storage import DocumentPackStorage, ObjectBinding


async def cleanup_document_pack_snapshots(session, settings, *, limit=100):
    storage = DocumentPackStorage(settings)
    now = datetime.now(UTC)
    rows = (
        (
            await session.execute(
                select(DocumentSharePackItem)
                .join(DocumentSharePack)
                .join(User, User.id == DocumentSharePack.owner_user_id)
                .where(
                    DocumentSharePackItem.owns_snapshot.is_(True),
                    DocumentSharePackItem.cleaned_at.is_(None),
                    or_(
                        DocumentSharePack.expires_at <= now,
                        DocumentSharePack.revoked_at.is_not(None),
                        User.deleted_at.is_not(None),
                    ),
                )
                .limit(limit)
                .with_for_update(of=DocumentSharePackItem, skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    count = 0
    prefix = settings.s3_document_key_prefix.rstrip("/") + "/document-share-packs/"
    for item in rows:
        if not item.object_key.startswith(prefix):
            raise ValueError("Refusing cleanup outside pack-owned snapshot prefix")
        await storage.delete_snapshot(
            ObjectBinding(
                item.object_key,
                item.object_version,
                item.object_etag,
                item.byte_size,
                item.content_type,
                True,
            )
        )
        item.cleaned_at = now
        count += 1
    await session.commit()
    return count


async def main():
    from app.config import get_settings
    from app.db.session import async_session_factory, dispose_engine

    settings = get_settings()
    if settings.app_env.value not in {"test", "development", "staging"}:
        raise SystemExit("Document Pack cleanup is not approved for production")
    total = 0
    try:
        async with async_session_factory() as session:
            while True:
                count = await cleanup_document_pack_snapshots(session, settings)
                total += count
                if not count:
                    break
        print(f"pack_snapshots_cleaned={total}")
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
