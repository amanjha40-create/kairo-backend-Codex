"""Real-source regression matrix for the same isolated Document Pack fixture."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.exceptions import NotFoundError, ServiceUnavailableError
from app.models import (
    Certification,
    DocumentSharePack,
    Education,
    EducationDocument,
    Employment,
    EmploymentDocument,
    PortfolioItem,
    VerificationRequest,
    VerificationRequestEvidence,
)
from app.schemas.document_share_pack import DocumentPackCreate
from app.schemas.user_document import UserDocumentResponse
from app.services.document_share_pack_service import DocumentSharePackService
from test_document_share_packs import setup as document_pack_setup, payload_for, token_from

setup = document_pack_setup


async def seed_sources(c):
    owner = c.owner.id
    employment = Employment(
        id=uuid4(),
        created_by_user_id=owner,
        subject_full_name="Synthetic QA",
        employer_legal_name="Synthetic employer",
        job_title="QA",
    )
    education = Education(id=uuid4(), user_id=owner, institution_name="Synthetic institution")
    c.session.add_all([employment, education])
    await c.session.flush()
    records = []
    for kind in ["employment", "education", "certification", "portfolio"]:
        key = f"staging/{kind}/{uuid4()}.pdf"
        meta = c.storage.put(key)
        fields = dict(
            id=uuid4(),
            original_filename="synthetic.pdf",
            content_type="application/pdf",
            object_key=key,
            byte_size=meta["ContentLength"],
        )
        if kind == "employment":
            record = EmploymentDocument(
                **fields,
                employment_id=employment.id,
                uploaded_by_user_id=owner,
                document_type="experience_letter",
                checksum_sha256="b" * 64,
                verification_status="pending_review",
            )
        elif kind == "education":
            record = EducationDocument(
                **fields,
                education_id=education.id,
                uploaded_by_user_id=owner,
                document_type="degree_certificate",
                checksum_sha256="c" * 64,
            )
        elif kind == "certification":
            record = Certification(
                **fields, user_id=owner, title="Synthetic certification", checksum_sha256="d" * 64
            )
        else:
            record = PortfolioItem(
                **fields,
                user_id=owner,
                title="Synthetic portfolio",
                upload_completed_at=datetime.now(UTC),
            )
        c.session.add(record)
        records.append(record)
    await c.session.commit()
    return records


async def test_every_allowed_source_packs_and_replacement_detach_are_stable(setup):
    c = setup
    records = await seed_sources(c)
    files, _ = await c.svc.sources.list(c.owner.id)
    assert {file.source_type for file in files} == {
        "vault",
        "employment",
        "education",
        "certification",
        "portfolio",
    }
    payload = DocumentPackCreate(
        purpose="Synthetic multitype pack",
        expiry_days=30,
        items=[
            file.model_dump(include={"source_type", "source_id", "selection_version"})
            for file in files
        ],
    )
    created = await c.svc.create(c.owner.id, payload)
    pack = await c.svc.owned(c.owner.id, created.public_id)
    original = {item.public_id: item.object_key for item in pack.items}
    for record in records:
        c.storage.put(record.object_key, b"replaced file bytes")
        record.deleted_at = datetime.now(UTC)
        if isinstance(record, (Certification, PortfolioItem)):
            record.object_key = None
    await c.session.commit()
    reloaded = await c.svc.resolve(token_from(created))
    assert {item.public_id: item.object_key for item in reloaded.items} == original
    for item in reloaded.items:
        chunks, _ = await c.svc.storage.open(item)
        assert b"".join(chunks) == b"%PDF-synthetic harmless QA"


async def test_historical_evidence_excluded_at_catalog_and_creation(setup):
    c = setup
    records = await seed_sources(c)
    before, _ = await c.svc.sources.list(c.owner.id)
    request = VerificationRequest(
        id=uuid4(),
        subject_name="Synthetic",
        subject_email="qa@example.test",
        requested_by_user_id=c.owner.id,
        subject_user_id=c.owner.id,
        request_type="employment",
        status="draft",
    )
    c.session.add(request)
    await c.session.flush()
    for field, doc in [
        ("document_id", c.docs[0]),
        ("employment_document_id", records[0]),
        ("education_document_id", records[1]),
    ]:
        c.session.add(
            VerificationRequestEvidence(
                verification_request_id=request.id,
                submitted_by_user_id=c.owner.id,
                evidence_type="document",
                field_key="qa",
                status="superseded",
                **{field: doc.id},
            )
        )
    await c.session.commit()
    files, _ = await c.svc.sources.list(c.owner.id)
    hidden = {c.docs[0].id, records[0].id, records[1].id}
    assert not hidden.intersection(file.source_id for file in files)
    selected = next(file for file in before if file.source_id == records[0].id)
    with pytest.raises(NotFoundError):
        await c.svc.create(
            c.owner.id,
            DocumentPackCreate(
                purpose="QA",
                expiry_days=7,
                items=[
                    selected.model_dump(include={"source_type", "source_id", "selection_version"})
                ],
            ),
        )


async def test_copy_failure_rolls_back_all_items_and_removes_partial_snapshot(setup, monkeypatch):
    c = setup
    original = c.svc.storage.snapshot
    calls = 0

    async def fail_second(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ServiceUnavailableError("Synthetic copy failure")
        return await original(*args)

    monkeypatch.setattr(c.svc.storage, "snapshot", fail_second)
    payload = await payload_for(c, count=2)
    with pytest.raises(ServiceUnavailableError):
        await c.svc.create(c.owner.id, payload)
    assert await c.session.scalar(select(func.count()).select_from(DocumentSharePack)) == 0
    assert len(c.storage.deleted) == 1
    assert len(c.storage.objects) == 3


async def test_concurrent_revoke_and_view_count_no_lost_updates(setup):
    c = setup
    owner = c.owner.id
    created = await c.svc.create(owner, await payload_for(c))
    token = token_from(created)

    async def view():
        async with c.factory() as session:
            await DocumentSharePackService(session, c.settings).recipient(token)

    await asyncio.gather(view(), view())
    await c.session.refresh(await c.svc.owned(owner, created.public_id))
    assert (await c.svc.owned(owner, created.public_id)).view_count == 2
    await c.session.rollback()

    async def revoke():
        async with c.factory() as session:
            return await DocumentSharePackService(session, c.settings).revoke(
                owner, created.public_id
            )

    first, second = await asyncio.gather(revoke(), revoke())
    assert first.revoked_at == second.revoked_at


@pytest.mark.parametrize(
    "kind",
    [
        "aadhaar",
        "pan",
        "passport",
        "driving_license",
        "voter_id",
        "birth_certificate",
        "address_proof",
        "government_id",
    ],
)
async def test_identity_precise_database_roundtrip_no_verification_inference(setup, kind):
    doc = setup.docs[0]
    doc.document_type = kind
    await setup.session.commit()
    await setup.session.refresh(doc)
    assert UserDocumentResponse.model_validate(doc).document_type == kind
    assert doc.verification_status == "pending" and doc.verified_at is None
