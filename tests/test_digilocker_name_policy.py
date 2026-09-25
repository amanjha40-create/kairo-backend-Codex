"""Synthetic identity facts only; success never discloses extracted name tokens."""

import asyncio
from datetime import date

import pytest
from sqlalchemy import func, select
from test_digilocker_identity import DOB, TODAY, certificate, identity  # noqa: F401
from test_digilocker_lifecycle import harness  # noqa: F401
from test_digilocker_trust import source
from test_trust_score_v1 import _Session, _settings, _user

from app.db.session import async_session_factory
from app.integrations.digilocker.identity import match_document, normalize_name
from app.models import DigiLockerIdentityVerification, TrustScoreSnapshot
from app.schemas.trust_score import IdentityTrustResponse
from app.services.canonical_trust import resolve_identity
from app.services.trust_score_service import TrustScoreService


@pytest.mark.parametrize("doctype", ["PANCR", "DRVLC"])
@pytest.mark.parametrize(
    "profile,provider,dob,result,reason",
    [
        ("Aman Jha", "Aman Jha", DOB, "VERIFIED_MATCH", "NAME_EXACT_MATCH"),
        ("Aman Jha", "Aman Kumar Jha", DOB, "VERIFIED_MATCH", "FIRST_LAST_MATCH_MIDDLE_IGNORED"),
        ("Aman Kumar Jha", "Aman Jha", DOB, "VERIFIED_MATCH", "FIRST_LAST_MATCH_MIDDLE_IGNORED"),
        (
            "Aman Rajesh Jha",
            "Aman Kumar Jha",
            DOB,
            "VERIFIED_MATCH",
            "FIRST_LAST_MATCH_MIDDLE_IGNORED",
        ),
        (
            "Aman Kumar Prasad Jha",
            "Aman Jha",
            DOB,
            "VERIFIED_MATCH",
            "FIRST_LAST_MATCH_MIDDLE_IGNORED",
        ),
        ("Aman Jha", "Arman Kumar Jha", DOB, "MISMATCH", "NAME_MISMATCH"),
        ("Aman Jha", "Aman Kumar Singh", DOB, "MISMATCH", "NAME_MISMATCH"),
        ("Aman Jha", "Aman Kumar Jha", date(1980, 1, 1), "MISMATCH", "DOB_MISMATCH"),
        ("Aman Jha", "Other Name", date(1980, 1, 1), "MISMATCH", "NAME_AND_DOB_MISMATCH"),
        ("Aman Jha", "Aman Kumar Jha", None, "PARTIAL_MATCH", "REQUIRED_FIELD_MISSING"),
        ("  Mr. AMAN   Jha ", "Aman.Jha", DOB, "VERIFIED_MATCH", "NAME_EXACT_MATCH"),
        ("Dr. Aman Jha", "\uff21man Jha", DOB, "VERIFIED_MATCH", "NAME_EXACT_MATCH"),
        ("Aman", "Aman", DOB, "VERIFIED_MATCH", "NAME_EXACT_MATCH"),
        ("Aman", "Aman Kumar", DOB, "MISMATCH", "NAME_MISMATCH"),
        ("Aman Kumar", "Aman", DOB, "MISMATCH", "NAME_MISMATCH"),
        ("Aman", "Arman", DOB, "MISMATCH", "NAME_MISMATCH"),
        ("Aman Jha", "Jha Aman", DOB, "MISMATCH", "NAME_MISMATCH"),
        ("Aman Jha", "A Jha", DOB, "MISMATCH", "NAME_MISMATCH"),
        ("Aman Jha", "Aman Jharkhand", DOB, "MISMATCH", "NAME_MISMATCH"),
        ("Aman Jha", "Shri Aman Jha", DOB, "MISMATCH", "NAME_MISMATCH"),
        (
            "Anne-Marie O'Neil",
            "Anne\u2011Marie O\u2019Neil",
            DOB,
            "VERIFIED_MATCH",
            "NAME_EXACT_MATCH",
        ),
        ("Anne-Marie Test", "Anne Marie Test", DOB, "MISMATCH", "NAME_MISMATCH"),
    ],
)
def test_name_policy(doctype, profile, provider, dob, result, reason):
    match = match_document(certificate(doctype, name=provider), doctype, profile, dob, TODAY)
    assert match.result == result
    key = "name_match_reason" if result == "VERIFIED_MATCH" else "mismatch_reason"
    assert match.diagnostics[key] == reason
    assert provider not in str(match.diagnostics)


@pytest.mark.parametrize("profile", ["Aman Jha", "Aman Kumar Jha"])
def test_missing_source_dob_cannot_verify_middle_difference(profile):
    other = "Aman Kumar Jha" if profile == "Aman Jha" else "Aman Jha"
    result = match_document(certificate(name=other, dob=""), "PANCR", profile, DOB, TODAY)
    assert result.result == "PARTIAL_MATCH"
    assert result.diagnostics["name_match_reason"] is None


@pytest.mark.parametrize("title", ["Mr", "Mrs", "Ms", "Dr"])
def test_approved_prefix_only(title):
    assert normalize_name(f"{title}. Test Candidate") == "test candidate"
    assert normalize_name(f"Test {title} Candidate") == f"test {title.lower()} candidate"


def test_normalization_fail_closed_and_no_transliteration():
    assert normalize_name("Aman\t Jha\n") == "aman jha"
    assert normalize_name("Aman\u200b Jha") == ""
    assert normalize_name("Dr.") == ""
    assert normalize_name("Aman - Jha") == ""
    assert normalize_name("a" * 256) == ""
    assert normalize_name("\u0905\u092e\u0928 \u091d\u093e") != normalize_name("Aman Jha")


@pytest.mark.parametrize("doctype", ["PANCR", "DRVLC"])
async def test_private_success_provenance_idempotency_and_client_compatibility(
    identity, caplog, doctype  # noqa: F811
):
    t = identity
    t.docs.retrieve.side_effect = lambda *args, **kwargs: certificate(
        doctype, name="Test PrivateMiddleCanary Candidate"
    )
    caplog.set_level("INFO", logger="app.services.digilocker_identity_service")
    responses = await asyncio.gather(t.call([doctype]), t.call([doctype]))
    assert responses[0]["items"][0]["id"] == responses[1]["items"][0]["id"]
    assert all(r["items"][0]["match_reason"] is None and r["identity_verified"] for r in responses)
    async with async_session_factory() as session:
        rows = (
            await session.scalars(
                select(DigiLockerIdentityVerification).where(
                    DigiLockerIdentityVerification.user_id == t.h.ids[0]
                )
            )
        ).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.match_reason == "FIRST_LAST_MATCH_MIDDLE_IGNORED"
        stored = str({c.name: getattr(row, c.name) for c in row.__table__.columns})
        from app.models import User

        user = await session.get(User, t.h.ids[0])
        trust = IdentityTrustResponse.model_validate(await resolve_identity(session, user))
        assert trust.state == "verified" and trust.sources[0].reason is None
        assert (
            await session.scalar(
                select(func.count())
                .select_from(TrustScoreSnapshot)
                .where(TrustScoreSnapshot.user_id == user.id)
            )
            == 0
        )
    logged = str([r.__dict__ for r in caplog.records])
    for canary in ("PrivateMiddleCanary", "SYNTHETIC-PRIVATE-ID", "<Certificate", "02-01-1990"):
        assert canary not in stored + logged + str(responses)


@pytest.mark.parametrize("first,second", [("PANCR", "DRVLC"), ("DRVLC", "PANCR")])
async def test_second_source_middle_match_does_not_add_score_or_snapshot(first, second):
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    user = _user(updated_at=now, trust_score_consent_at=now)
    session = _Session(user)
    session.digilocker = [source(user, first, match_reason="NAME_EXACT_MATCH")]
    service = TrustScoreService(session, _settings())
    before = await service.calculate_trust_score(user.id)
    session.snapshot.calculated_at = before.last_calculated_at
    snapshots = len(session.added)
    session.digilocker.append(source(user, second, match_reason="FIRST_LAST_MATCH_MIDDLE_IGNORED"))
    after = await service.calculate_trust_score(user.id)
    assert after.overall == before.overall
    assert len(session.added) == snapshots
    assert len([c for c in after.positive_contributors if c.code == "identity_authoritative"]) == 1
    assert all(s.reason is None for s in after.identity_sources)
