"""Production promotion privacy regression using disposable synthetic rows only."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.db.session import async_session_factory
from app.models.permanent_address import (
    PermanentAddressDocument,
    PermanentAddressReview,
    PermanentAddressSession,
    PermanentAddressVersion,
)
from app.models.user_document import UserDocument
from tests.test_account_deletion_workflow import case as case  # noqa: F401
from tests.test_account_deletion_workflow import erase


async def test_candidate_erasure_removes_address_targets_and_evidence(case):
    now = datetime.now(UTC)
    async with async_session_factory() as db:
        document = await db.scalar(select(UserDocument).where(UserDocument.user_id == case.uid))
        address = PermanentAddressVersion(
            user_id=case.uid,
            version=1,
            claimed_address={"synthetic": True},
            address_hash="c" * 64,
            target_encrypted=b"synthetic-encrypted-target-not-real",
            target_key_id="test-address-key",
            target_source="provider_geocode",
            target_status="needs_review",
            document_id=document.id,
            document_checksum=document.checksum_sha256,
        )
        db.add(address)
        await db.flush()
        address_id, document_id = address.id, document.id
        db.add_all(
            [
                PermanentAddressSession(
                    address_version_id=address_id,
                    cycle=1,
                    challenge_hash="d" * 64,
                    started_at=now,
                    expires_at=now + timedelta(seconds=60),
                    completed_at=now,
                    result="NEEDS_REVIEW",
                    pending_target_encrypted=b"synthetic-pending-target-not-real",
                    pending_target_key_id="test-address-key",
                    manual_review_status="pending",
                ),
                PermanentAddressReview(
                    address_version_id=address_id,
                    document_id=document_id,
                    document_checksum="a" * 64,
                    outcome="NEEDS_REVIEW",
                ),
                PermanentAddressDocument(
                    address_version_id=address_id,
                    document_id=document_id,
                    status="UNDER_REVIEW",
                ),
            ]
        )
        await db.commit()

    await erase(case)

    async with async_session_factory() as db:
        assert await db.get(PermanentAddressVersion, address_id) is None
        assert await db.get(UserDocument, document_id) is None
        for model in (PermanentAddressSession, PermanentAddressReview, PermanentAddressDocument):
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.address_version_id == address_id)
                )
                == 0
            )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(UserDocument)
                .where(UserDocument.user_id == case.other)
            )
            == 1
        )
    # Logical erasure inventories private storage; only the durable purge worker deletes it.
    assert case.storage.deleted == []
