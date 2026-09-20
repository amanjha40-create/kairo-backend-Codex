"""Canonical Candidate ownership to durable cleanup identities; no storage IO."""

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import (
    Certification,
    DocumentSharePack,
    DocumentSharePackItem,
    EducationDocument,
    EmploymentDocument,
    FreelanceContractDocument,
    InternshipDocument,
    PortfolioItem,
    ResumeDocument,
    UserDocument,
    VerificationRequestEvidence,
)
from app.models.account_deletion import AccountDeletion, AccountDeletionItem


def identity(kind, key):
    return hashlib.sha256(f"{kind}:{key}".encode()).hexdigest()


def safe_key(key):
    return bool(
        key
        and len(key) <= 1024
        and not key.startswith("/")
        and not any(c in key for c in ("\\", "?", "#", "\x00", "\n", "\r", "://"))
        and all(part not in {".", "..", ""} for part in key.rstrip("/").split("/"))
    )


async def inventory_deletion(session, settings, user, snapshot):
    now = datetime.now(UTC)
    # Issued PUT capabilities cannot be revoked by a DB write. Delay first purge until
    # their maximum TTL; recurring exact-namespace reconciliation catches late PUTs.
    due = now + timedelta(seconds=max(settings.s3_presigned_put_ttl_seconds, 900))
    prefix = settings.s3_document_key_prefix.strip("/")
    request = AccountDeletion(
        user_id=user.id,
        storage_bucket=settings.s3_documents_bucket,
        storage_prefix=prefix,
        status="purge_pending",
        requested_at=now,
        db_committed_at=now,
        next_attempt_at=due,
    )
    session.add(request)
    await session.flush()
    seen = set()

    def add(kind, source, key=None, scope=None, source_id=None, error=None):
        fingerprint = identity(kind, key or str(source_id))
        if fingerprint in seen:
            return
        seen.add(fingerprint)
        if kind in {"object", "namespace"} and (
            not safe_key(key) or not safe_key(scope) or not key.startswith(scope)
        ):
            error = "unsafe_legacy_reference"
        session.add(
            AccountDeletionItem(
                deletion_id=request.id,
                identity_hash=fingerprint,
                source_type=source,
                source_id=source_id,
                kind=kind,
                object_key=None if error else key,
                scope_prefix=scope,
                status="review" if error else "pending",
                last_error_category=error,
                next_attempt_at=due,
            )
        )

    owner_scopes = {
        "resume": f"resumes/{user.id}/",
        "vault": f"{prefix}/user-documents/{user.id}/",
        "employment": f"{prefix}/users/{user.id}/employments/",
        "internship": f"{prefix}/users/{user.id}/internships/",
        "freelance": f"{prefix}/users/{user.id}/freelance/",
        "certification": f"{prefix}/certifications/{user.id}/",
        "portfolio": f"{prefix}/portfolio/{user.id}/",
    }
    for source, scope in owner_scopes.items():
        add("namespace", source, scope, scope)
    for parent in snapshot.education_ids:
        scope = f"{prefix}/education-documents/{parent}/"
        add("namespace", "education", scope, scope, parent)

    selections = [
        ("resume", ResumeDocument, ResumeDocument.user_id == user.id, "storage_key"),
        ("vault", UserDocument, UserDocument.user_id == user.id, "object_key"),
        (
            "employment",
            EmploymentDocument,
            EmploymentDocument.employment_id.in_(snapshot.employment_ids),
            "object_key",
        ),
        (
            "education",
            EducationDocument,
            EducationDocument.education_id.in_(snapshot.education_ids),
            "object_key",
        ),
        (
            "internship",
            InternshipDocument,
            InternshipDocument.internship_id.in_(snapshot.internship_ids),
            "object_key",
        ),
        (
            "freelance",
            FreelanceContractDocument,
            FreelanceContractDocument.freelance_contract_id.in_(snapshot.freelance_ids),
            "object_key",
        ),
        ("certification", Certification, Certification.user_id == user.id, "object_key"),
        ("portfolio", PortfolioItem, PortfolioItem.user_id == user.id, "object_key"),
    ]
    known_evidence = set()
    for source, model, predicate, key_field in selections:
        for row in (await session.scalars(select(model).where(predicate))).all():
            key = getattr(row, key_field)
            if key:
                scope = (
                    f"{prefix}/education-documents/{row.education_id}/"
                    if source == "education"
                    else owner_scopes[source]
                )
                error = (
                    "legacy_bucket_mismatch"
                    if source == "resume" and row.storage_bucket != request.storage_bucket
                    else None
                )
                add("object", source, key, scope, row.id, error)
                known_evidence.add(row.id)
    if user.avatar_key:
        # Avatar uses a fixed, canonical per-user filename, not an arbitrary user prefix.
        add("object", "avatar", user.avatar_key, f"{prefix}/users/{user.id}/avatar.")
    for suffix in ("jpg", "jpeg", "png", "webp"):
        key = f"{prefix}/users/{user.id}/avatar.{suffix}"
        add("object", "avatar", key, f"{prefix}/users/{user.id}/avatar.")

    packs = (
        await session.scalars(
            select(DocumentSharePack)
            .where(DocumentSharePack.owner_user_id == user.id)
            .with_for_update()
        )
    ).all()
    for pack in packs:
        scope = f"{prefix}/document-share-packs/{pack.id}/"
        add("namespace", "pack_snapshot", scope, scope, pack.id)
        for item in (
            await session.scalars(
                select(DocumentSharePackItem).where(DocumentSharePackItem.pack_id == pack.id)
            )
        ).all():
            if item.owns_snapshot:
                add("object", "pack_snapshot", item.object_key, scope, item.id)
            elif item.object_key:
                # Version-bound sources may have been detached since the pack was made.
                source_scope = owner_scopes.get(item.source_type)
                if item.source_type == "education":
                    source_scope = next(
                        (
                            f"{prefix}/education-documents/{eid}/"
                            for eid in snapshot.education_ids
                            if item.object_key.startswith(f"{prefix}/education-documents/{eid}/")
                        ),
                        None,
                    )
                add("object", item.source_type, item.object_key, source_scope, item.source_id)

    requests = (
        snapshot.verification_request_ids_to_purge | snapshot.verification_request_ids_to_retain
    )
    for evidence in (
        await session.scalars(
            select(VerificationRequestEvidence).where(
                VerificationRequestEvidence.verification_request_id.in_(requests)
            )
        )
    ).all():
        refs = [
            evidence.document_id,
            evidence.employment_document_id,
            evidence.education_document_id,
        ]
        if evidence.evidence_type == "document" and not any(
            ref in known_evidence for ref in refs if ref
        ):
            add(
                "unresolved",
                "legacy_evidence",
                source_id=evidence.id,
                error="legacy_evidence_unresolved",
            )
    for signup_id in snapshot.pending_signup_ids:
        add("otp", "signup", source_id=signup_id)
    return request
