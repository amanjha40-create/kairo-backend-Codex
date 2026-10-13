"""Synthetic local evidence only: no live storage, provider or GPS calls."""

import hashlib
from datetime import timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
from app.models.permanent_address import (
    PermanentAddressReview,
    PermanentAddressVersion,
)
from app.models.trust_score_snapshot import TrustScoreSnapshot
from app.models.user_account_event import UserAccountEvent
from app.models.user_document import UserDocument
from app.schemas.passport_share import PassportSharePermissions
from app.schemas.permanent_address import (
    AddressDocumentCompleteInput,
    AddressDocumentReviewInput,
    AddressDocumentSubmitInput,
    AddressDocumentUploadInput,
)
from app.services.address_document_privacy import private_address_document
from app.services.document_pack_sources import DocumentPackSources
from app.services.document_pack_storage import ObjectBinding
from app.services.public_passport_service import PublicPassportService
from app.services.trust_score_service import TrustScoreService
from tests.test_permanent_address_manual_review import payload as location_decision
from tests.test_permanent_address_manual_review import pending
from tests.test_permanent_address_verification import ADDRESS, prepare
from tests.test_permanent_address_verification import case as address_case

case = address_case

PDF = b"%PDF-1.4\nSynthetic address evidence only\n%%EOF"


class Storage:
    body = PDF
    etag = "synthetic"

    async def inspect(self, key):
        return ObjectBinding(key, None, self.etag, len(self.body), "application/pdf")

    async def open(self, item):
        return iter([self.body]), {"Cache-Control": "no-store"}


@pytest.fixture(autouse=True)
def no_storage_network(monkeypatch):
    async def presign(**kwargs):
        assert kwargs["ttl_seconds"] > 0
        assert kwargs["content_type"] == "application/pdf"
        return "https://synthetic.invalid/temporary-upload"

    monkeypatch.setattr(
        "app.services.permanent_address_documents.generate_presigned_put_url", presign
    )


async def upload(case, *, complete=True, submit=True):
    db, users, svc, clock, geo = case
    row = await svc.current(users[0].id)
    version = row.id if row else await prepare(case)
    svc.storage = Storage()
    svc.settings.s3_documents_bucket = "synthetic-address-documents"
    intent = await svc.upload_address_document(
        users[0].id,
        AddressDocumentUploadInput(
            address_version_id=version,
            document_type="address_proof",
            original_filename="synthetic.pdf",
            content_type="application/pdf",
            byte_size=len(PDF),
        ),
    )
    payload = AddressDocumentCompleteInput(
        address_version_id=version, checksum_sha256=hashlib.sha256(PDF).hexdigest()
    )
    if complete:
        await svc.complete_address_document(users[0].id, intent.document_id, payload)
    if submit:
        await svc.submit_address_document(
            users[0].id,
            AddressDocumentSubmitInput(
                address_version_id=version,
                document_id=intent.document_id,
                confirms_current_address=True,
            ),
        )
    return version, intent, payload


def decision(document, outcome="APPROVE_MATCHING", **changes):
    return AddressDocumentReviewInput(
        document_id=document,
        idempotency_key=uuid4(),
        outcome=outcome,
        inspected_document=True,
        candidate_identity_matches=True,
        document_acceptable=True,
        address_matches=True,
    ).model_copy(update=changes)


@pytest.mark.asyncio
async def test_required_and_upload_complete_submit(case):
    db, users, svc, *_ = case
    version = await prepare(case)
    assert (await svc.document_state(users[0].id, version)).status == "REQUIRED"
    version, intent, payload = await upload(case, complete=False, submit=False)
    assert (await svc.document_state(users[0].id, version)).status == "UPLOADING"
    assert "object_key" not in intent.model_dump() and "bucket" not in intent.model_dump()
    await svc.complete_address_document(users[0].id, intent.document_id, payload)
    assert (await svc.document_state(users[0].id, version)).status == "UPLOADED"
    await svc.submit_address_document(
        users[0].id,
        AddressDocumentSubmitInput(
            address_version_id=version,
            document_id=intent.document_id,
            confirms_current_address=True,
        ),
    )
    assert (await svc.document_state(users[0].id, version)).status == "UNDER_REVIEW"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome,expected",
    [
        ("APPROVE_MATCHING", "MATCH"),
        ("REJECT", "REJECTED"),
        ("REQUEST_CORRECTION", "NEEDS_CORRECTION"),
        ("REQUEST_DIFFERENT_DOCUMENT", "NEEDS_CORRECTION"),
    ],
)
async def test_review_outcomes_idempotent_and_no_gps_target_or_score(case, outcome, expected):
    db, users, svc, *_ = case
    version, intent, _ = await upload(case)
    row = await db.get(PermanentAddressVersion, version)
    target = row.target_encrypted
    payload = decision(intent.document_id, outcome)
    first = await svc.decide_address_document(users[2].id, version, payload)
    again = await svc.decide_address_document(users[2].id, version, payload)
    assert first == again and first["document_status"] == expected
    assert (
        await db.scalar(
            select(func.count())
            .select_from(PermanentAddressReview)
            .where(PermanentAddressReview.address_version_id == version)
        )
        == 1
    )
    assert row.target_encrypted == target and row.target_source == "provider_geocode"
    assert row.target_confirmed_at is None and row.completed_at is None
    assert (await svc.state(users[0].id)).successful_gps_checks == 0
    assert (await svc.state(users[0].id)).status != "PERMANENT_ADDRESS_VERIFIED"
    assert (await svc.document_state(users[0].id, version)).status == expected
    with pytest.raises(ConflictError):
        await svc.decide_address_document(
            users[2].id, version, payload.model_copy(update={"address_matches": False})
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("actor", [0, 1])
async def test_candidate_cannot_review_or_view(case, actor):
    db, users, svc, *_ = case
    version, intent, _ = await upload(case)
    with pytest.raises(ForbiddenError):
        await svc.decide_address_document(users[actor].id, version, decision(intent.document_id))
    with pytest.raises(ForbiddenError):
        await svc.review_detail(users[actor].id, version)


@pytest.mark.asyncio
async def test_owner_only_completion_and_submission(case):
    db, users, svc, *_ = case
    version, intent, payload = await upload(case, complete=False, submit=False)
    with pytest.raises(NotFoundError):
        await svc.complete_address_document(users[1].id, intent.document_id, payload)
    with pytest.raises(NotFoundError):
        await svc.submit_address_document(
            users[1].id,
            AddressDocumentSubmitInput(
                address_version_id=version,
                document_id=intent.document_id,
                confirms_current_address=True,
            ),
        )
    with pytest.raises(ValidationAppError):
        await svc.submit_address_document(
            users[0].id,
            AddressDocumentSubmitInput(
                address_version_id=version,
                document_id=intent.document_id,
                confirms_current_address=True,
            ),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["expired", "checksum", "format", "size", "deleted"])
async def test_upload_fails_closed(case, failure):
    db, users, svc, clock, _ = case
    version, intent, payload = await upload(case, complete=False, submit=False)
    if failure == "expired":
        clock[0] += timedelta(hours=24)
    elif failure == "checksum":
        payload.checksum_sha256 = "0" * 64
    elif failure == "format":
        svc.storage.body = b"x" * len(PDF)
    elif failure == "size":
        svc.storage.body = PDF + b"more"
    else:
        (await db.get(UserDocument, intent.document_id)).deleted_at = clock[0]
    with pytest.raises((ConflictError, ValidationAppError, NotFoundError)):
        await svc.complete_address_document(users[0].id, intent.document_id, payload)


@pytest.mark.asyncio
async def test_replacement_and_address_edit_preserve_audit(case):
    db, users, svc, *_ = case
    version, first, _ = await upload(case)
    await svc.decide_address_document(users[2].id, version, decision(first.document_id, "REJECT"))
    _, second, _ = await upload(case)
    assert (await svc.document_record(first.document_id)).status == "SUPERSEDED"
    assert (await svc.document_record(second.document_id)).status == "UNDER_REVIEW"
    await svc.decide_address_document(users[2].id, version, decision(second.document_id))
    newer = await svc.save_address(
        users[0].id, ADDRESS.model_copy(update={"address_line_1": "125 Synthetic Road"})
    )
    assert newer.document_status == "REQUIRED"
    assert (await db.get(PermanentAddressVersion, version)).document_status == "MATCH"
    assert (
        await db.scalar(
            select(func.count())
            .select_from(PermanentAddressReview)
            .where(PermanentAddressReview.address_version_id == version)
        )
        == 2
    )
    with pytest.raises(NotFoundError):
        await svc.decide_address_document(users[2].id, version, decision(second.document_id))
    with pytest.raises(ConflictError):
        await svc.submit_address_document(
            users[0].id,
            AddressDocumentSubmitInput(
                address_version_id=newer.address_version_id,
                document_id=second.document_id,
                confirms_current_address=True,
            ),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["deleted", "detached", "replaced_bytes", "superseded", "expired"]
)
async def test_review_invalid_document_rejected(case, failure):
    db, users, svc, clock, _ = case
    version, intent, _ = await upload(case)
    doc = await db.get(UserDocument, intent.document_id)
    if failure == "deleted":
        doc.deleted_at = clock[0]
    elif failure == "detached":
        (await db.get(PermanentAddressVersion, version)).document_id = None
    elif failure == "superseded":
        doc.superseded_at = clock[0]
    elif failure == "expired":
        doc.expires_at = clock[0].date() - timedelta(days=1)
    else:
        svc.storage.etag = "changed"
    with pytest.raises(ConflictError):
        await svc.decide_address_document(users[2].id, version, decision(intent.document_id))


@pytest.mark.asyncio
async def test_privacy_and_admin_projection(case):
    db, users, svc, *_ = case
    version, intent, _ = await upload(case)
    assert await db.scalar(select(private_address_document(intent.document_id))) is True
    sources = DocumentPackSources(db, svc.settings, svc.storage)
    assert not list((await db.scalars(sources.queries(users[0].id)["vault"])).all())
    safe = (await svc.document_state(users[0].id, version)).model_dump_json()
    for value in ("object_key", "checksum", "reviewer", "claimed_address", "target", "upload_url"):
        assert value not in safe
    projection = await svc.document_review_projection(users[2].id, version)
    assert projection["claimed_address"] == ADDRESS.model_dump()
    assert projection["content_path"].endswith("/content")
    assert (
        not {"target_encrypted", "evidence_binding", "object_key", "coordinates"}
        & projection.keys()
    )
    chunks, headers, mime = await svc.review_detail(users[2].id, version, content=True)
    assert b"".join(chunks) == PDF and mime == "application/pdf"
    assert headers["Cache-Control"] == "no-store"


@pytest.mark.asyncio
async def test_approval_requires_all_explicit_confirmations(case):
    db, users, svc, *_ = case
    version, intent, _ = await upload(case)
    for field in ("candidate_identity_matches", "document_acceptable", "address_matches"):
        with pytest.raises(ValidationAppError):
            await svc.decide_address_document(
                users[2].id, version, decision(intent.document_id, **{field: False})
            )


@pytest.mark.parametrize(
    "changes",
    [
        {"content_type": "text/html"},
        {"byte_size": 52428801},
        {"document_number": "private"},
        {"original_filename": "../file.pdf"},
    ],
)
def test_upload_validation(changes):
    data = dict(
        address_version_id=uuid4(),
        document_type="address_proof",
        original_filename="test.pdf",
        content_type="application/pdf",
        byte_size=10,
    )
    with pytest.raises(ValidationError):
        AddressDocumentUploadInput(**(data | changes))


@pytest.mark.asyncio
async def test_configurable_freshness_no_universal_expiry(case):
    db, users, svc, *_ = case
    version, intent, _ = await upload(case)
    assert (await svc.document_state(users[0].id, version)).status == "UNDER_REVIEW"
    svc.settings.permanent_address_document_max_age_days = {"address_proof": 30}
    assert (
        await svc.evidence_valid(users[0].id, await db.get(PermanentAddressVersion, version))
        is None
    )
    assert (await svc.document_state(users[0].id, version)).status == "NEEDS_CORRECTION"
    events = (
        await db.scalars(select(UserAccountEvent).where(UserAccountEvent.user_id == users[0].id))
    ).all()
    assert all("address_line_1" not in str(e.metadata_payload) for e in events)


@pytest.mark.asyncio
async def test_new_document_approval_unlocks_only_existing_synthetic_pending_target(case):
    db, users, svc, *_ = case
    row, attempt = await pending(case)
    version, intent, _ = await upload(case)
    with pytest.raises(ValidationAppError):
        await svc.resolve_manual_location(
            users[2].id, version, attempt.id, location_decision(users)
        )
    await svc.decide_address_document(users[2].id, version, decision(intent.document_id))
    assert (await svc.state(users[0].id)).successful_gps_checks == 0
    assert row.target_source == "provider_geocode" and row.target_confirmed_at is None
    receipt = await svc.resolve_manual_location(
        users[2].id, version, attempt.id, location_decision(users)
    )
    assert receipt["outcome"] == "APPROVE_ONSITE_LOCATION"
    assert (await svc.state(users[0].id)).successful_gps_checks == 1


@pytest.mark.asyncio
async def test_additional_evidence_request_is_not_shown_as_approved(case):
    db, users, svc, *_ = case
    row, attempt = await pending(case)
    version, intent, _ = await upload(case)
    await svc.decide_address_document(users[2].id, version, decision(intent.document_id))
    await svc.resolve_manual_location(
        users[2].id, row.id, attempt.id, location_decision(users, "REQUEST_ADDITIONAL_EVIDENCE")
    )
    assert (await svc.document_state(users[0].id, version)).status == "UNDER_REVIEW"
    await svc.decide_address_document(users[2].id, version, decision(intent.document_id))
    assert (await svc.document_state(users[0].id, version)).status == "MATCH"


@pytest.mark.asyncio
async def test_public_passport_excludes_proof_even_when_documents_shared(case):
    db, users, svc, *_ = case
    _, intent, _ = await upload(case)
    public = PublicPassportService(db, svc.settings)
    vault = await public.build_vault_for_user(
        users[0].id,
        PassportSharePermissions(include_user_documents=True, show_documents=True),
        public_only=True,
    )
    assert not vault.user_documents
    assert str(intent.document_id) not in vault.model_dump_json()


@pytest.mark.asyncio
async def test_upload_approval_does_not_write_score_snapshots_or_change_score(case):
    db, users, svc, *_ = case
    svc.settings.trust_score_require_consent = False
    score = TrustScoreService(db, svc.settings)
    before = await score.calculate_trust_score(users[0].id)
    count = await db.scalar(
        select(func.count())
        .select_from(TrustScoreSnapshot)
        .where(TrustScoreSnapshot.user_id == users[0].id)
    )
    version, intent, _ = await upload(case)
    await svc.decide_address_document(users[2].id, version, decision(intent.document_id))
    assert (
        await db.scalar(
            select(func.count())
            .select_from(TrustScoreSnapshot)
            .where(TrustScoreSnapshot.user_id == users[0].id)
        )
        == count
    )
    after = await score.calculate_trust_score(users[0].id)
    assert before.overall == after.overall
    assert (await db.get(UserDocument, intent.document_id)).verification_status == "pending"


@pytest.mark.asyncio
async def test_finalized_address_rejects_new_upload(case):
    db, users, svc, clock, _ = case
    version, _, _ = await upload(case)
    row = await db.get(PermanentAddressVersion, version)
    row.completed_at = clock[0]
    with pytest.raises(ConflictError):
        await upload(case)
