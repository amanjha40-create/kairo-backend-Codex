from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from test_digilocker_identity import identity  # noqa: F401
from test_digilocker_lifecycle import harness  # noqa: F401
from test_trust_score_v1 import _Session, _settings, _user

from app.db.session import async_session_factory
from app.models import DigiLockerIdentityVerification, TrustScoreSnapshot, User
from app.schemas.public_passport import PublicPassportTrustScore
from app.schemas.trust_score import IdentityTrustResponse
from app.services.canonical_trust import identity_current, resolve_fact
from app.services.digilocker_identity_service import DigiLockerIdentityService
from app.services.trust_score_service import TrustScoreService


def source(user, doctype="DRVLC", result="VERIFIED_MATCH", **changes):
    values = dict(
        document_type=doctype,
        match_result=result,
        integrity_result="verified",
        verified_at=user.updated_at if result == "VERIFIED_MATCH" else None,
        profile_revision_at=user.updated_at,
        document_valid_until=None,
        match_reason="NAME_MISMATCH" if result == "MISMATCH" else None,
    )
    values.update(changes)
    return SimpleNamespace(**values)


@pytest.mark.parametrize("manual", [False, True])
async def test_verified_sources_contribute_once_and_pan_does_not_veto(manual):
    now = datetime.now(UTC)
    user = _user(updated_at=now, trust_score_consent_at=now)
    session = _Session(
        user, documents=[SimpleNamespace(verification_status="approved")] if manual else []
    )
    service = TrustScoreService(session, _settings())
    before = await service.calculate_trust_score(user.id)
    session.digilocker = [source(user), source(user, "PANCR", "MISMATCH")]
    after = await service.calculate_trust_score(user.id)
    assert after.identity_state == "verified"
    assert after.breakdown.identity == 100
    contributors = [s for s in after.positive_contributors if s.code == "identity_authoritative"]
    assert len(contributors) == 1 and contributors[0].points == 40
    assert (after.overall == before.overall) is manual
    assert any(s.reason == "NAME_MISMATCH" for s in after.identity_sources)
    snapshots = len(session.added)
    session.snapshot.calculated_at = after.last_calculated_at
    again = await service.calculate_trust_score(user.id)
    assert again.overall == after.overall and len(session.added) == snapshots
    session.digilocker.append(source(user, "PANCR"))
    assert (await service.calculate_trust_score(user.id)).overall == after.overall
    assert len(session.added) == snapshots


@pytest.mark.parametrize(
    "changes",
    [
        {"integrity_result": "failed"},
        {"verified_at": None},
        {"profile_revision_at": datetime(2000, 1, 1, tzinfo=UTC)},
        {"document_valid_until": datetime.now(UTC).date() - timedelta(days=1)},
        {"match_result": "MISMATCH"},
        {"match_result": "PARTIAL_MATCH"},
    ],
)
async def test_only_current_integrity_checked_provenance_scores(changes):
    now = datetime.now(UTC)
    user = _user(updated_at=now, trust_score_consent_at=now)
    session = _Session(user)
    session.digilocker = [source(user, **changes)]
    assert not identity_current(session.digilocker[0], user, now.date())
    result = await TrustScoreService(session, _settings()).calculate_trust_score(user.id)
    assert result.identity_state == "unverified"
    assert not any(s.code == "identity_authoritative" for s in result.positive_contributors)


def test_recipient_allowlist_strips_source_details_and_private_identifiers():
    public = PublicPassportTrustScore.model_validate(
        {
            "overall": 80,
            "status": "calculated",
            "identity_state": "verified",
            "identity_sources": [{"document_type": "PANCR", "reason": "NAME_MISMATCH"}],
            "pan": "PRIVATE-CANARY",
            "dl_number": "PRIVATE-CANARY",
            "provider_uri": "PRIVATE-CANARY",
        }
    ).model_dump_json()
    assert '"identity_state":"verified"' in public
    assert all(
        v not in public for v in ("CANARY", "PANCR", "MISMATCH", "identity_sources", "provider_uri")
    )


def test_fact_resolver_does_not_stack_sources_or_require_unanimity():
    sources = [
        dict(source="digilocker", document_type="DRVLC", current=True),
        dict(source="digilocker", document_type="PANCR", current=False),
    ]
    assert resolve_fact(sources)["state"] == "verified"
    assert resolve_fact(sources * 3)["state"] == "verified"
    assert resolve_fact([])["state"] == "unverified"


async def test_owner_result_reads_saved_provenance_without_provider_access(identity):  # noqa: F811
    t = identity
    await t.call(["DRVLC"])
    t.docs.issued.reset_mock()
    t.docs.retrieve.reset_mock()
    async with async_session_factory() as session:
        service = DigiLockerIdentityService(session, t.h.config, t.h.redis, documents=t.docs)
        result = IdentityTrustResponse.model_validate(await service.trust(t.h.ids[0]))
        assert result.state == "verified"
        assert result.sources[0].document_type == "DRVLC"
        other = await service.trust(t.h.ids[1])
        assert other == {"state": "unverified", "sources": []}
        user = await session.get(User, t.h.ids[0])
        user.updated_at += timedelta(seconds=1)
        await session.commit()
        assert (await service.trust(t.h.ids[0]))["state"] == "unverified"
    t.docs.issued.assert_not_called()
    t.docs.retrieve.assert_not_called()


async def test_match_reason_persists_without_extracted_values(identity):  # noqa: F811
    t = identity
    from test_digilocker_identity import certificate

    t.docs.retrieve.side_effect = None
    t.docs.retrieve.return_value = certificate(name="Synthetic Other Name")
    result = await t.call(["PANCR"])
    assert result["items"][0]["match_reason"] == "NAME_MISMATCH"
    async with async_session_factory() as session:
        row = await session.scalar(
            select(DigiLockerIdentityVerification).where(
                DigiLockerIdentityVerification.user_id == t.h.ids[0]
            )
        )
        values = str({col.name: getattr(row, col.name) for col in row.__table__.columns})
        assert "Synthetic Other Name" not in values and "SYNTHETIC-PRIVATE-ID" not in values
        assert row.match_reason == "NAME_MISMATCH"


async def test_concurrent_score_reads_create_one_snapshot(identity):  # noqa: F811
    import asyncio
    from sqlalchemy import func

    t = identity
    await t.call(["DRVLC"])
    async with async_session_factory() as session:
        user = await session.get(User, t.h.ids[0])
        user.trust_score_consent_at = datetime.now(UTC)
        await session.commit()

    async def read():
        async with async_session_factory() as session:
            return await TrustScoreService(session, _settings()).calculate_trust_score(t.h.ids[0])

    results = await asyncio.gather(read(), read())
    assert results[0].overall == results[1].overall
    async with async_session_factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(TrustScoreSnapshot)
                .where(TrustScoreSnapshot.user_id == t.h.ids[0])
            )
            == 1
        )
