"""One-shot synthetic Staging certification for the clean-slate orchestrator."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from redis.asyncio import Redis
from sqlalchemy import delete, func, select, text

from app.config import get_settings
from app.db.session import async_session_factory, engine
from app.infrastructure.s3.client import get_s3_client
from app.models import (
    AccountDeletion,
    AccountDeletionItem,
    DigiLockerConnection,
    Education,
    Employment,
    Notification,
    Organization,
    OrganizationDeletionResolution,
    OrganizationMember,
    PassportShareLink,
    PendingSignup,
    ResumeDocument,
    ResumeParsedResult,
    ResumeProcessingJob,
    ResumeReviewItem,
    ResumeReviewSession,
    Skill,
    User,
)
from app.organization.enums import OrganizationRole, OrganizationType
from app.services.account_deletion_purge import PurgeStorage, sweep_deletions
from app.services.clean_slate_orchestrator import (
    CleanSlateAllowlist,
    CleanSlateOrchestrator,
    CleanSlateSafetyError,
    storage_identity,
)


class CanaryFailure(RuntimeError):
    pass


async def _s3_exists(client, bucket: str, key: str) -> bool:  # noqa: ANN001
    try:
        await asyncio.to_thread(client.head_object, Bucket=bucket, Key=key)
        return True
    except client.exceptions.ClientError as error:
        if error.response.get("Error", {}).get("Code") in {"404", "NoSuchKey"}:
            return False
        raise


async def _create_fixtures(
    settings, *, run: str, target_id: UUID
) -> dict[str, object]:  # noqa: ANN001
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        target = User(
            id=target_id,
            email=f"clean-slate-target-{run}@example.test",
            full_name="Synthetic Clean Slate Target",
            role="user",
            is_active=True,
            email_verified_at=now,
        )
        survivor = User(
            email=f"clean-slate-survivor-{run}@example.test",
            full_name="Synthetic Clean Slate Survivor",
            role="user",
            is_active=True,
            email_verified_at=now,
        )
        protected = User(
            email=f"clean-slate-admin-{run}@example.test",
            full_name="Synthetic Protected Admin",
            role="admin",
            is_active=True,
            email_verified_at=now,
        )
        session.add_all((target, survivor, protected))
        await session.flush()
        approved_org = Organization(
            created_by_user_id=target.id,
            name=f"Synthetic HR Closure {run}",
            organization_type=OrganizationType.EMPLOYER,
        )
        retained_org = Organization(
            created_by_user_id=survivor.id,
            name=f"Synthetic Institution Preserve {run}",
            organization_type=OrganizationType.UNIVERSITY,
        )
        session.add_all((approved_org, retained_org))
        await session.flush()
        session.add_all(
            (
                OrganizationMember(
                    organization_id=approved_org.id,
                    user_id=target.id,
                    role=OrganizationRole.OWNER,
                ),
                OrganizationMember(
                    organization_id=retained_org.id,
                    user_id=survivor.id,
                    role=OrganizationRole.OWNER,
                ),
                OrganizationMember(
                    organization_id=retained_org.id,
                    user_id=target.id,
                    role=OrganizationRole.REVIEWER,
                ),
            )
        )
        target.active_organization_id = approved_org.id
        session.add_all(
            (
                Employment(
                    created_by_user_id=target.id,
                    subject_full_name="Synthetic Candidate",
                    subject_email=target.email,
                    employer_legal_name="Synthetic Employer",
                    job_title="Synthetic Analyst",
                ),
                Education(
                    user_id=target.id,
                    institution_name="Synthetic University",
                    degree="Synthetic Degree",
                ),
                Skill(
                    user_id=target.id,
                    name="Synthetic Skill",
                    normalized_name=f"synthetic-skill-{run}",
                ),
                DigiLockerConnection(user_id=target.id, status="pending"),
                PassportShareLink(
                    owner_user_id=target.id,
                    token_hash=hashlib.sha256(uuid4().bytes).hexdigest(),
                    permissions={"education": True},
                ),
                Notification(
                    notification_type="in_app",
                    event_type="synthetic.clean_slate",
                    category="system",
                    title="Synthetic canary",
                    body="Synthetic clean-slate certification only.",
                    recipient_user_id=target.id,
                    recipient_email=target.email,
                    channel="in_app",
                    template_key="synthetic_clean_slate",
                    dedupe_key=f"synthetic-clean-slate-{run}",
                ),
            )
        )
        pending = PendingSignup(
            email=target.email,
            expires_at=now + timedelta(hours=1),
            completed_user_id=target.id,
            completed_at=now,
        )
        session.add(pending)
        storage_key = f"resumes/{target.id}/clean-slate-{run}.pdf"
        resume = ResumeDocument(
            user_id=target.id,
            storage_bucket=settings.s3_documents_bucket,
            storage_key=storage_key,
            original_filename="synthetic-clean-slate.pdf",
            normalized_filename="synthetic-clean-slate.pdf",
            content_type="application/pdf",
            file_size_bytes=28,
            upload_status="uploaded",
            processing_status="needs_review",
            consent_at=now,
            consent_version="v1",
        )
        session.add(resume)
        await session.flush()
        job = ResumeProcessingJob(
            resume_document_id=resume.id,
            user_id=target.id,
            status="completed",
            idempotency_key=f"clean-slate-{run}",
        )
        session.add(job)
        await session.flush()
        parsed = ResumeParsedResult(
            job_id=job.id,
            user_id=target.id,
            schema_version="1",
            structured_result={"synthetic": True},
            parser_metadata={"canary": True},
            warnings=[],
        )
        session.add(parsed)
        await session.flush()
        review = ResumeReviewSession(
            user_id=target.id,
            resume_document_id=resume.id,
            processing_job_id=job.id,
            parsed_result_id=parsed.id,
            status="draft",
            schema_version="1",
        )
        session.add(review)
        await session.flush()
        session.add(
            ResumeReviewItem(
                review_session_id=review.id,
                user_id=target.id,
                claim_type="skill",
                source_claim_id=f"synthetic-{run}",
                original_payload={"name": "Synthetic Skill"},
                edited_payload={"name": "Synthetic Skill"},
            )
        )
        await session.commit()
        return {
            "run": run,
            "target": target.id,
            "survivor": survivor.id,
            "protected": protected.id,
            "approved_org": approved_org.id,
            "retained_org": retained_org.id,
            "pending": pending.id,
            "storage_key": storage_key,
            "drift_key": f"resumes/{target.id}/unexpected-{run}.pdf",
        }


async def _cleanup(fixtures: dict[str, object], settings) -> None:  # noqa: ANN001
    storage = PurgeStorage(settings)
    for field in ("storage_key", "drift_key"):
        await storage.purge(settings.s3_documents_bucket, str(fixtures[field]))
    user_ids = (
        fixtures["target"],
        fixtures["survivor"],
        fixtures["protected"],
    )
    organization_ids = (fixtures["approved_org"], fixtures["retained_org"])
    async with async_session_factory() as session:
        deletion_ids = select(AccountDeletion.id).where(AccountDeletion.user_id.in_(user_ids))
        await session.execute(
            delete(OrganizationDeletionResolution).where(
                OrganizationDeletionResolution.deletion_id.in_(deletion_ids)
            )
        )
        await session.execute(delete(Organization).where(Organization.id.in_(organization_ids)))
        await session.execute(
            delete(AccountDeletionItem).where(AccountDeletionItem.deletion_id.in_(deletion_ids))
        )
        await session.execute(
            delete(AccountDeletion).where(AccountDeletion.user_id.in_(user_ids))
        )
        await session.execute(delete(PendingSignup).where(PendingSignup.id == fixtures["pending"]))
        await session.execute(
            delete(Notification).where(Notification.recipient_user_id.in_(user_ids))
        )
        await session.execute(delete(ResumeDocument).where(ResumeDocument.user_id.in_(user_ids)))
        await session.execute(
            delete(DigiLockerConnection).where(DigiLockerConnection.user_id.in_(user_ids))
        )
        await session.execute(delete(Employment).where(Employment.created_by_user_id.in_(user_ids)))
        await session.execute(delete(Education).where(Education.user_id.in_(user_ids)))
        await session.execute(delete(Skill).where(Skill.user_id.in_(user_ids)))
        await session.execute(
            delete(PassportShareLink).where(PassportShareLink.owner_user_id.in_(user_ids))
        )
        await session.execute(delete(User).where(User.id.in_(user_ids)))
        await session.commit()


async def certify() -> dict[str, object]:
    settings = get_settings()
    if settings.app_env.value != "staging":
        raise CanaryFailure("staging_environment_required")
    if settings.s3_documents_bucket is None:
        raise CanaryFailure("staging_storage_required")
    run = os.environ.get("CLEAN_SLATE_CANARY_RUN", "")
    raw_target_id = os.environ.get("CLEAN_SLATE_CANARY_TARGET_ID", "")
    try:
        target_id = UUID(raw_target_id)
    except ValueError as error:
        raise CanaryFailure("preseeded_target_id_required") from error
    if len(run) != 32 or any(character not in "0123456789abcdef" for character in run):
        raise CanaryFailure("preseeded_run_id_required")
    s3 = get_s3_client(settings)
    storage = PurgeStorage(settings)
    resume_scope = f"resumes/{target_id}/"

    async def list_versioned_objects(bucket: str, scopes: tuple[str, ...]) -> set[str]:
        if resume_scope not in scopes:
            raise CanaryFailure("resume_storage_scope_missing")
        keys: set[str] = set()
        discovered, truncated = await storage.discover(bucket, resume_scope)
        if truncated:
            raise CanaryFailure("storage_listing_truncated")
        keys.update(discovered)
        return keys

    fixtures = await _create_fixtures(settings, run=run, target_id=target_id)
    results: dict[str, object] = {}
    try:
        if not await _s3_exists(
            s3, settings.s3_documents_bucket, str(fixtures["storage_key"])
        ) or not await _s3_exists(
            s3, settings.s3_documents_bucket, str(fixtures["drift_key"])
        ):
            raise CanaryFailure("preseeded_storage_required")
        async with Redis.from_url(settings.redis_url) as redis:
            async with async_session_factory() as session:
                protected_ids = frozenset(
                    (
                        await session.scalars(
                            select(User.id).where(
                                User.role != "user",
                                User.deleted_at.is_(None),
                            )
                        )
                    ).all()
                )
                base = CleanSlateAllowlist(
                    schema_version=1,
                    environment="staging",
                    approved_user_ids=frozenset({fixtures["target"]}),
                    approved_pending_signup_ids=frozenset({fixtures["pending"]}),
                    approved_organization_ids=frozenset({fixtures["approved_org"]}),
                    approved_storage_object_ids=frozenset(),
                    protected_user_ids=protected_ids,
                )
                orchestrator = CleanSlateOrchestrator(
                    session,
                    settings,
                    redis,
                    object_lister=list_versioned_objects,
                )
                before = await session.scalar(
                    select(func.count()).select_from(User).where(
                        User.id.in_((fixtures["target"], fixtures["survivor"]))
                    )
                )
                await orchestrator.plan(base)
                await session.rollback()
                async with async_session_factory() as verify:
                    after = await verify.scalar(
                        select(func.count()).select_from(User).where(
                            User.id.in_((fixtures["target"], fixtures["survivor"]))
                        )
                    )
                    target = await verify.get(User, fixtures["target"])
                results["A_DRY_RUN_ZERO_MUTATIONS"] = (
                    before == after == 2 and target is not None and target.deleted_at is None
                )
                strict = CleanSlateAllowlist(
                    **{
                        **base.__dict__,
                        "approved_storage_object_ids": frozenset(
                            {
                                storage_identity(
                                    settings.s3_documents_bucket,
                                    str(fixtures["storage_key"]),
                                )
                            }
                        ),
                    }
                )
                blocked_admin = CleanSlateAllowlist(
                    schema_version=1,
                    environment="staging",
                    approved_user_ids=frozenset({fixtures["protected"]}),
                    approved_pending_signup_ids=frozenset(),
                    approved_organization_ids=frozenset(),
                    approved_storage_object_ids=frozenset(),
                    protected_user_ids=protected_ids,
                )
                try:
                    await orchestrator.plan(blocked_admin)
                    results["D_PROTECTED_ADMIN_BLOCKED"] = False
                except CleanSlateSafetyError as error:
                    results["D_PROTECTED_ADMIN_BLOCKED"] = (
                        str(error) == "protected_identity_targeted"
                    )
                try:
                    await orchestrator.plan(strict, require_storage_allowlist=True)
                    results["H_UNKNOWN_STORAGE_FAILS_CLOSED"] = False
                except CleanSlateSafetyError as error:
                    results["H_UNKNOWN_STORAGE_FAILS_CLOSED"] = (
                        str(error) == "storage_allowlist_mismatch"
                    )
                await storage.purge(
                    settings.s3_documents_bucket, str(fixtures["drift_key"])
                )
                health_calls = 0

                async def health() -> None:
                    nonlocal health_calls
                    health_calls += 1
                    revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
                    if revision != "096":
                        raise CanaryFailure("database_revision_mismatch")

                progress: list[dict[str, object]] = []
                deletion_ids = await orchestrator.execute(
                    strict,
                    confirmation="EXECUTE STAGING CLEAN SLATE",
                    backup_verified=True,
                    health_check=health,
                    progress=progress.append,
                )
                if len(deletion_ids) != 1:
                    raise CanaryFailure("unexpected_deletion_count")
                deletion_id = deletion_ids[0]
            async with async_session_factory() as sweep_session:
                sweep = await sweep_deletions(
                    sweep_session,
                    settings,
                    redis,
                    deletion_id=deletion_id,
                    now=datetime.now(UTC) + timedelta(days=1),
                )
                if sweep is None:
                    raise CanaryFailure("deletion_sweep_not_claimed")
            async with async_session_factory() as verify:
                request = await verify.get(AccountDeletion, deletion_id)
                target = await verify.get(User, fixtures["target"])
                survivor = await verify.get(User, fixtures["survivor"])
                approved_org = await verify.get(Organization, fixtures["approved_org"])
                retained_org = await verify.get(Organization, fixtures["retained_org"])
                review_count = int(
                    await verify.scalar(
                        select(func.count()).select_from(AccountDeletionItem).where(
                            AccountDeletionItem.deletion_id == deletion_id,
                            AccountDeletionItem.status == "review",
                        )
                    )
                    or 0
                )
                pending_count = int(
                    await verify.scalar(
                        select(func.count()).select_from(AccountDeletionItem).where(
                            AccountDeletionItem.deletion_id == deletion_id,
                            AccountDeletionItem.status != "complete",
                        )
                    )
                    or 0
                )
                results.update(
                    {
                        "B_APPROVED_USER_COMPLETE": request is not None
                        and request.status == "complete",
                        "C_NONALLOWLISTED_USER_PRESERVED": survivor is not None
                        and survivor.deleted_at is None
                        and survivor.is_active,
                        "E_APPROVED_ORG_DEPENDENCY_SAFE": approved_org is not None
                        and approved_org.closed_at is not None,
                        "F_NONALLOWLISTED_ORG_PRESERVED": retained_org is not None
                        and retained_org.closed_at is None,
                        "I_AUDIT_TOMBSTONE_RETAINED": target is not None
                        and target.deleted_at is not None
                        and request is not None,
                        "review_count": review_count,
                        "pending_count": pending_count,
                        "health_checks": health_calls,
                    }
                )
            results["G_EXACT_S3_REMOVED"] = not await _s3_exists(
                s3, settings.s3_documents_bucket, str(fixtures["storage_key"])
            )
            async with async_session_factory() as session:
                orchestrator = CleanSlateOrchestrator(
                    session,
                    settings,
                    redis,
                    object_lister=list_versioned_objects,
                )

                async def health_again() -> None:
                    revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
                    if revision != "096":
                        raise CanaryFailure("database_revision_mismatch")

                rerun = await orchestrator.execute(
                    strict,
                    confirmation="EXECUTE STAGING CLEAN SLATE",
                    backup_verified=True,
                    health_check=health_again,
                    progress=lambda _event: None,
                )
                results["J_RERUN_IDEMPOTENT"] = rerun == [deletion_id]
        required = [
            key
            for key in results
            if key[:2] in {"A_", "B_", "C_", "D_", "E_", "F_", "G_", "H_", "I_", "J_"}
        ]
        if len(required) != 10 or not all(results[key] for key in required):
            raise CanaryFailure("certification_assertion_failed")
        if results["review_count"] or results["pending_count"]:
            raise CanaryFailure("deletion_not_fully_complete")
        return {"status": "PASS", **results}
    finally:
        await _cleanup(fixtures, settings)


async def main_async() -> None:
    try:
        result = await certify()
        print(json.dumps(result, sort_keys=True), flush=True)
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(asyncio.wait_for(main_async(), timeout=600))


if __name__ == "__main__":
    main()
