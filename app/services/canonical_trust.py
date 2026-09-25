"""Resolve one trust state per fact. Sources explain a result, never multiply points."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.models import DigiLockerIdentityVerification, UserDocument


def resolve_fact(sources):
    """Adapters must establish ownership, integrity and currentness before resolution."""
    sources = sorted(sources, key=lambda item: (item["source"], item["document_type"]))
    return {
        "state": "verified" if any(s["current"] for s in sources) else "unverified",
        "sources": sources,
    }


def identity_current(row, user, today):
    return bool(
        row.match_result == "VERIFIED_MATCH"
        and row.integrity_result == "verified"
        and row.verified_at is not None
        and row.profile_revision_at == user.updated_at
        and (row.document_valid_until is None or row.document_valid_until >= today)
    )


def identity_public_reason(row):
    # Existing clients accept mismatch reasons only. Success provenance stays private.
    return None if row.match_result == "VERIFIED_MATCH" else row.match_reason


async def resolve_identity(session, user, now=None):
    now = now or datetime.now(UTC)
    sources = []
    documents = (
        (
            await session.execute(
                select(UserDocument).where(
                    UserDocument.user_id == user.id,
                    UserDocument.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    # Keep the established manual-document scoring contract; do not expand file eligibility.
    if any(doc.verification_status in {"approved", "verified"} for doc in documents):
        sources.append(
            {
                "source": "kairo",
                "document_type": "identity",
                "current": True,
                "match_result": "VERIFIED_MATCH",
                "reason": None,
            }
        )
    rows = (
        (
            await session.execute(
                select(DigiLockerIdentityVerification).where(
                    DigiLockerIdentityVerification.user_id == user.id,
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        sources.append(
            {
                "source": "digilocker",
                "document_type": row.document_type,
                "current": identity_current(row, user, now.date()),
                "match_result": row.match_result,
                "reason": identity_public_reason(row),
            }
        )
    return resolve_fact(sources)
