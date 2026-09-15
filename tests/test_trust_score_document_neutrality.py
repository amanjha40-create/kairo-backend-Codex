"""Real DB lifecycle: files are evidence, never verification merely by existing."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import Certification, PortfolioItem, TrustScoreSnapshot
from app.schemas.user_document import UserDocumentUploadIntentRequest
from app.services.trust_score_service import TrustScoreService
from app.services.user_document_service import UserDocumentService
from test_document_share_packs import setup as document_pack_setup, payload_for, token_from

setup = document_pack_setup


def signals(response):
    return (
        response.overall,
        response.breakdown.model_dump(),
        response.domain_details,
        response.positive_contributors,
    )


async def consent(c):
    c.owner.trust_score_consent_at = datetime.now(UTC)
    c.owner.trust_score_consent_version = "v1-consent"
    c.owner.email_verified_at = datetime.now(UTC)
    c.owner.phone_verified_at = datetime.now(UTC)
    await c.session.commit()


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
async def test_upload_complete_and_remove_each_identity_type_is_score_neutral(
    setup, monkeypatch, kind
):
    c = setup
    await consent(c)
    score = TrustScoreService(c.session, c.settings)
    baseline = await score.calculate_trust_score(c.owner.id)

    async def synthetic_put(**kwargs):
        return "https://upload.example.test/synthetic"

    monkeypatch.setattr(
        "app.services.user_document_service.generate_presigned_put_url", synthetic_put
    )
    service = UserDocumentService(c.session, c.settings)
    intent = await service.create_upload_intent(
        c.owner.id,
        UserDocumentUploadIntentRequest(
            document_type=kind,
            original_filename="synthetic.pdf",
            content_type="application/pdf",
            byte_size=25,
        ),
    )
    assert signals(await score.calculate_trust_score(c.owner.id)) == signals(baseline)
    doc = await service.complete_upload(c.owner.id, intent.document_id, "a" * 64)
    assert doc.verification_status == "pending"
    assert signals(await score.calculate_trust_score(c.owner.id)) == signals(baseline)
    await service.delete(c.owner.id, intent.document_id)
    assert signals(await score.calculate_trust_score(c.owner.id)) == signals(baseline)


async def test_certification_project_attachments_and_pack_lifecycle_are_neutral(setup):
    c = setup
    await consent(c)
    score = TrustScoreService(c.session, c.settings)
    baseline = await score.calculate_trust_score(c.owner.id)
    payload = await payload_for(c)
    for model in (Certification, PortfolioItem):
        fields = dict(
            id=uuid4(),
            user_id=c.owner.id,
            title="Synthetic attachment",
            object_key="synthetic/only",
            original_filename="synthetic.pdf",
            content_type="application/pdf",
            byte_size=25,
        )
        if model is Certification:
            fields["checksum_sha256"] = "a" * 64
        else:
            fields["upload_completed_at"] = datetime.now(UTC)
        c.session.add(model(**fields))
        await c.session.commit()
        assert signals(await score.calculate_trust_score(c.owner.id)) == signals(baseline)
    created = await c.svc.create(c.owner.id, payload)
    assert signals(await score.calculate_trust_score(c.owner.id)) == signals(baseline)
    await c.svc.recipient(token_from(created))
    assert signals(await score.calculate_trust_score(c.owner.id)) == signals(baseline)
    await c.svc.revoke(c.owner.id, created.public_id)
    assert signals(await score.calculate_trust_score(c.owner.id)) == signals(baseline)


async def test_new_formula_appends_v2_and_never_rewrites_historical_snapshot(setup):
    c = setup
    await consent(c)
    service = TrustScoreService(c.session, c.settings)
    await service.calculate_trust_score(c.owner.id)
    old = (
        await c.session.execute(
            select(TrustScoreSnapshot).where(TrustScoreSnapshot.user_id == c.owner.id)
        )
    ).scalar_one()
    # Fixture representing an existing historical v1 snapshot, not production history.
    old.score_version = "v1"
    await c.session.commit()
    await c.session.refresh(old)
    old_values = {column.name: getattr(old, column.name) for column in old.__table__.columns}
    current = await service.calculate_trust_score(c.owner.id)
    assert current.score_version == "v2"
    await c.session.refresh(old)
    assert {
        column.name: getattr(old, column.name) for column in old.__table__.columns
    } == old_values
    snapshots = (
        (
            await c.session.execute(
                select(TrustScoreSnapshot).where(TrustScoreSnapshot.user_id == c.owner.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(snapshots) == 2
    assert {row.score_version for row in snapshots} == {"v1", "v2"}
