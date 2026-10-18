"""Synthetic reference trust-chain regressions against the isolated migrated database."""

import asyncio
import logging
import re
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import hash_refresh_token
from app.config import get_settings
from app.db.session import engine
from app.exceptions import ConflictError, NotFoundError, RateLimitError, ValidationAppError
from app.models import (
    EmailDeliveryLog,
    EmployerVerificationRequest,
    Employment,
    User,
    VerificationRequest,
)
from app.models.employment_reference import EmploymentReference as Reference
from app.models.employment_reference import EmploymentReferenceInvitation as Invitation
from app.models.verification_request_event import VerificationRequestEvent
from app.schemas.email_delivery import EmailSendResult
from app.schemas.employer_verification import EmployerVerifyBody
from app.schemas.employment_reference import (
    HRReference,
    ManagerNomination,
    ManagerResponse,
    ManagerValidation,
    SendReference,
)
from app.services.account_deletion_policy import revoke_and_scrub_related
from app.services.employer_verification_service import EmployerVerificationService
from app.services.employment_reference_service import EmploymentReferenceService, ReferenceGateError
from app.verification_requests.enums import VerificationRequestStatus, VerificationRequestType


@pytest.fixture
async def case():
    assert engine.url.host in {"localhost", "127.0.0.1"}, "Use isolated local test DB only"
    async with engine.connect() as conn:
        outer = await conn.begin()
        async with AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as db:
            user = User(email=f"candidate-{uuid4()}@example.com", role="user", is_active=True)
            other = User(email=f"other-{uuid4()}@example.com", role="user", is_active=True)
            db.add_all([user, other])
            await db.flush()
            emp = Employment(
                created_by_user_id=user.id,
                subject_full_name="Synthetic Candidate",
                subject_email=user.email,
                employer_legal_name="Synthetic Employer",
                job_title="Engineer",
                employment_type="full_time",
                start_date=date(2024, 1, 1),
                verification_method="employer_confirmation",
                verification_status="verified",
            )
            db.add(emp)
            await db.flush()
            token = "synthetic-hr-token-" + uuid4().hex
            hr = EmployerVerificationRequest(
                employment_id=emp.id,
                contact_name="Synthetic HR",
                verifier_email="hr@example.com",
                relationship_to_subject="hr",
                token_hash=hash_refresh_token(token),
                response="confirmed",
                sent_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
            db.add(hr)
            await db.flush()
            settings = get_settings().model_copy(
                update={"manager_reference_public_base_url": "https://api.example.test"}
            )
            svc = EmploymentReferenceService(db, settings)
            svc.provider = SimpleNamespace(
                provider_name="console",
                send=AsyncMock(return_value=EmailSendResult(provider="console", status="sent")),
            )
            yield SimpleNamespace(
                db=db, user=user, other=other, emp=emp, hr=hr, token=token, svc=svc
            )
        await outer.rollback()


def nomination(**overrides):
    return ManagerNomination(
        **(
            {
                "full_name": "Synthetic Manager",
                "designation": "Lead",
                "work_email": "manager@example.com",
            }
            | overrides
        )
    )


async def approved(case, **validation):
    await case.svc.nominate(case.user.id, case.emp.id, nomination())
    row = await case.svc.active(case.emp.id)
    await case.svc.record_hr(
        case.hr,
        HRReference(comments="Confidential HR comment"),
        ManagerValidation(
            **(
                {
                    "nomination_id": row.id,
                    "relationship_decision": "confirmed_reporting_manager",
                    "contact_provenance": "hr_confirmed",
                }
                | validation
            )
        ),
    )
    await case.db.commit()
    return row


async def invited(case):
    row = await approved(case)
    payload = SendReference(nomination_id=row.id, idempotency_key=uuid4())
    result = await case.svc.send(case.emp.id, payload)
    assert result["delivery_status"] == "sent"
    message = case.svc.provider.send.call_args.args[0]
    match = re.search(
        re.escape(case.svc.settings.manager_reference_public_base_url)
        + r"/api/v1/public/manager-references/([^/]+)/page", message.text_body
    )
    assert match
    return row, payload, match.group(1)


async def test_manager_origin_remains_independent(case, caplog):
    case.svc.settings = case.svc.settings.model_copy(update={
        "employer_portal_base_url": "https://hr.kairoid.com",
        "document_pack_public_base_url": "https://app.kairoid.com",
        "manager_reference_public_base_url": "https://api.kairoid.com",
    })
    _, _, token = await invited(case)
    message = case.svc.provider.send.call_args.args[0]
    expected = f"https://api.kairoid.com/api/v1/public/manager-references/{token}/page"
    assert expected in message.text_body
    assert "https://app.kairoid.com" not in message.text_body
    assert "https://hr.kairoid.com" not in message.text_body
    assert token not in caplog.text


def response(**overrides):
    return ManagerResponse(
        **(
            {
                "directly_managed": "yes",
                "working_relationship": "direct_manager",
                "overall_performance": 4,
                "reliability_ownership": 5,
                "communication": 3,
                "teamwork_collaboration": 4,
                "attested": True,
                "additional_comments": "Confidential manager comment",
            }
            | overrides
        )
    )


async def test_empty_summary_and_nomination_ownership(case):
    safe = await case.svc.summary(case.user.id, case.emp.id)
    assert safe.completed_count == 0 and safe.reporting_manager.status == "not_started"
    with pytest.raises(NotFoundError):
        await case.svc.nominate(case.other.id, case.emp.id, nomination())
    safe = await case.svc.nominate(case.user.id, case.emp.id, nomination())
    assert safe.reporting_manager.status == "awaiting_hr_validation"
    assert "work_email" not in safe.model_dump_json()
    with pytest.raises(ReferenceGateError, match="validation"):
        await case.svc.send(
            case.emp.id,
            SendReference(
                nomination_id=safe.reporting_manager.nomination_id, idempotency_key=uuid4()
            ),
        )


async def test_internal_reference_comments_never_reach_passport_or_export(case):
    from io import BytesIO

    from pypdf import PdfReader

    from app.models.passport_share_link import PassportShareLink
    from app.schemas.passport_share import PassportSharePermissions
    from app.services.hr_v2_service import HRV2Service
    from app.services.passport_engine_service import PassportEngineService
    from app.services.passport_pdf_service import build_passport_pdf_projection, render_passport_pdf
    from app.services.public_passport_service import PublicPassportService

    _, _, manager_token = await invited(case)
    await case.svc.respond(manager_token, response())
    internal = await case.svc.report(case.emp.id)
    assert "Confidential HR comment" in str(internal)
    assert "Confidential manager comment" in str(internal)
    # The structured internal report retains its allowlisted free-text fields.
    hr_rows = await HRV2Service(case.db, case.svc.settings)._reference_items(
        [SimpleNamespace(employment_id=case.emp.id)]
    )
    assert "Confidential HR comment" in str(hr_rows)
    assert "Confidential manager comment" in str(hr_rows)
    assert any(row.name == nomination().full_name for row in hr_rows)
    assert any(row.title_or_relationship == nomination().designation for row in hr_rows)

    public = PublicPassportService(case.db, case.svc.settings)
    permissions = PassportSharePermissions(include_employments=True, show_trust_score=False)
    share_token = uuid4().hex
    case.db.add(PassportShareLink(
        owner_user_id=case.user.id, token_hash=public._hash_token(share_token),
        permissions=permissions.model_dump(),
    ))
    await case.db.flush()
    shared = await public.get_by_token(share_token)
    vault = await public.build_vault_for_user(case.user.id, permissions, public_only=True)
    owner = await PassportEngineService(case.db, case.svc.settings).get_owner_passport(case.user.id)
    projection = build_passport_pdf_projection(owner, generated_at=datetime.now(UTC))
    pdf = PdfReader(BytesIO(render_passport_pdf(projection)))
    surfaces = [shared.model_dump_json(), vault.model_dump_json(), owner.model_dump_json(),
                projection.model_dump_json(), "\n".join(page.extract_text() for page in pdf.pages),
                (await case.svc.summary(case.user.id, case.emp.id)).model_dump_json()]
    assert shared.vault.employments
    for surface in surfaces:
        for comment in ("Confidential HR comment", "Confidential manager comment"):
            assert comment not in surface


async def test_structured_report_excludes_superseded_nomination_without_deleting_history(case):
    from app.services.hr_v2_service import HRV2Service

    previous = await approved(case)
    previous_id = previous.id
    await case.svc.nominate(case.user.id, case.emp.id, nomination(full_name="New Synthetic Manager"), replace=True)
    rows = await HRV2Service(case.db, case.svc.settings)._reference_items(
        [SimpleNamespace(employment_id=case.emp.id)], require_pair=True)
    assert all(row.evidence_id != previous_id for row in rows)
    assert any(row.name == "New Synthetic Manager" for row in rows)
    assert previous.active is False and previous.superseded_at is not None
    assert previous.nomination["full_name"] == nomination().full_name


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"work_email": "bad"},
        {"work_email": None, "phone": "123"},
        {"work_email": None},
        {"phone": "+00123"},
        {"extra_field": "bad"},
    ],
)
def test_invalid_nomination(payload):
    with pytest.raises(ValidationError):
        ManagerNomination(**payload) if not payload else nomination(**payload)


@pytest.mark.parametrize(
    "field",
    ["overall_performance", "reliability_ownership", "communication", "teamwork_collaboration"],
)
@pytest.mark.parametrize("value", [0, 6, True, "5"])
def test_stable_rating_scale(field, value):
    with pytest.raises(ValidationError):
        response(**{field: value})


async def test_hr_gate_does_not_bypass_canonical_finalization(case):
    row = await approved(case)
    case.emp.verification_status = "under_review"
    await case.db.flush()
    with pytest.raises(ReferenceGateError) as error:
        await case.svc.send(
            case.emp.id, SendReference(nomination_id=row.id, idempotency_key=uuid4())
        )
    assert error.value.code == "employment_not_verified"
    assert case.svc.provider.send.await_count == 0
    assert (
        await case.svc.summary(case.user.id, case.emp.id)
    ).reporting_manager.invitation_blocked_reason == "employment_not_verified"


@pytest.mark.parametrize("provenance", ["hr_confirmed", "hr_corrected", "hr_supplied"])
async def test_hr_contact_paths_and_private_summary(case, provenance):
    extra = {"contact_provenance": provenance}
    if provenance != "hr_confirmed":
        extra["confirmed_contact"] = nomination(
            work_email="private-manager@example.com", full_name="Private Referee"
        )
    row = await approved(case, **extra)
    assert row.status == "ready_to_invite"
    safe = (await case.svc.summary(case.user.id, case.emp.id)).model_dump_json()
    for secret in (
        "private-manager",
        "Private Referee",
        "Confidential",
        "eligible_for_rehire",
        "contact_provenance",
    ):
        assert secret not in safe
    report = await case.svc.report(case.emp.id)
    assert "Confidential HR comment" in str(report)
    assert "@example.com" not in str(report)
    candidate = await case.svc.summary(case.user.id, case.emp.id)
    if provenance != "hr_confirmed":
        assert candidate.reporting_manager.identity_withheld
        assert candidate.reporting_manager.full_name is None
        assert candidate.reporting_manager.designation is None


@pytest.mark.parametrize(
    "decision",
    [
        "worked_here_but_not_reporting_manager",
        "not_recognized",
        "details_incorrect",
        "cannot_confirm",
    ],
)
async def test_negative_hr_relationship_blocks_delivery(case, decision):
    row = await approved(case, relationship_decision=decision)
    assert row.status == "needs_review"
    with pytest.raises(ReferenceGateError):
        await case.svc.send(
            case.emp.id, SendReference(nomination_id=row.id, idempotency_key=uuid4())
        )


async def test_former_manager_is_valid_and_cannot_share_is_not_invitable(case):
    row = await approved(case, relationship_decision="left_organization")
    assert row.status == "ready_to_invite"
    assert (
        await case.svc.summary(case.user.id, case.emp.id)
    ).reporting_manager.relationship == "former_reporting_manager"
    await case.svc.nominate(
        case.user.id, case.emp.id, nomination(full_name="New Manager"), replace=True
    )
    row = await case.svc.active(case.emp.id)
    await case.svc.validate_manager(
        case.hr,
        ManagerValidation(
            nomination_id=row.id,
            relationship_decision="confirmed_reporting_manager",
            contact_provenance="hr_cannot_confirm",
        ),
    )
    with pytest.raises(ReferenceGateError):
        await case.svc.send(
            case.emp.id, SendReference(nomination_id=row.id, idempotency_key=uuid4())
        )


async def test_candidate_change_revokes_and_requires_fresh_hr_approval(case):
    old, _, token = await invited(case)
    with pytest.raises(ValidationAppError) as error:
        await case.svc.nominate(
            case.user.id, case.emp.id, nomination(full_name="Replacement Manager")
        )
    assert error.value.code == "manager_nomination_locked"
    result = await case.svc.nominate(
        case.user.id, case.emp.id, nomination(full_name="Replacement Manager"), replace=True
    )
    assert result.reporting_manager.status == "awaiting_hr_validation"
    assert result.reporting_manager.nomination_id != old.id
    assert not old.active and old.validation["contact_provenance"] == "hr_confirmed"
    with pytest.raises(NotFoundError):
        await case.svc.context(token)
    with pytest.raises(ConflictError):
        await case.svc.validate_manager(
            case.hr,
            ManagerValidation(
                nomination_id=old.id,
                relationship_decision="confirmed_reporting_manager",
                contact_provenance="hr_confirmed",
            ),
        )


async def test_scoped_hashed_expiring_revocable_tokens_and_resend(case):
    row, payload, token = await invited(case)
    invitation = await case.svc.invitation(row.id)
    assert invitation.token_hash == hash_refresh_token(token)
    assert token not in str(invitation.__dict__)
    assert (await case.svc.send(case.emp.id, payload))["idempotent"]
    assert case.svc.provider.send.await_count == 1
    with pytest.raises(RateLimitError):
        await case.svc.send(
            case.emp.id, SendReference(nomination_id=row.id, idempotency_key=uuid4())
        )
    assert (await case.svc.context(token))["status"] == "opened"
    invitation.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    invitation.created_at = datetime.now(UTC) - timedelta(minutes=16)
    await case.db.flush()
    with pytest.raises(NotFoundError):
        await case.svc.context(token)
    assert (await case.svc.summary(case.user.id, case.emp.id)).reporting_manager.status == "expired"
    await case.svc.send(case.emp.id, SendReference(nomination_id=row.id, idempotency_key=uuid4()))
    with pytest.raises(NotFoundError):
        await case.svc.respond(token, response())
    latest = await case.svc.invitation(row.id)
    await case.svc.revoke(case.emp.id, row.id)
    assert latest.revoked_at is not None
    assert case.emp.verification_status == "verified"


@pytest.mark.parametrize(
    "directly_managed, expected",
    [("yes", "completed"), ("no", "needs_review"), ("cannot_confirm", "needs_review")],
)
async def test_manager_result_independent_from_verified_employment(
    case, directly_managed, expected
):
    row, _, token = await invited(case)
    body = response(directly_managed=directly_managed)
    result = await case.svc.respond(token, body)
    assert result["status"] == expected
    assert (await case.svc.respond(token, body))["idempotent"]
    with pytest.raises(ConflictError):
        await case.svc.respond(token, decline=True)
    assert case.emp.verification_status == "verified"
    safe = await case.svc.summary(case.user.id, case.emp.id)
    assert safe.completed_count == (2 if expected == "completed" else 1)
    assert "Confidential" not in safe.model_dump_json()


async def test_decline_is_truthful_and_not_a_get_decision(case):
    row, _, token = await invited(case)
    await case.svc.context(token)
    assert row.answers == {} and row.completed_at is None
    assert (await case.svc.respond(token, decline=True))["status"] == "declined"
    assert case.emp.verification_status == "verified"


async def test_database_uniqueness(case):
    await approved(case)
    for kind in ("hr_reference", "reporting_manager_reference"):
        with pytest.raises(IntegrityError):
            async with case.db.begin_nested():
                case.db.add(Reference(employment_id=case.emp.id, kind=kind, status="pending"))
                await case.db.flush()
    with pytest.raises(IntegrityError):
        async with case.db.begin_nested():
            case.db.add(
                Reference(
                    employment_id=case.emp.id, kind="hr_reference", active=False, status="pending"
                )
            )
            await case.db.flush()


async def test_private_references_erased_even_with_retained_employment(case):
    row, _, token = await invited(case)
    await case.svc.respond(token, response())
    snapshot = SimpleNamespace(
        employment_ids={case.emp.id},
        verification_request_ids_to_purge=set(),
        verification_request_ids_to_retain=set(),
    )
    await revoke_and_scrub_related(case.db, case.user.id, snapshot, datetime.now(UTC))
    await case.db.flush()
    assert await case.db.get(Employment, case.emp.id) is not None
    assert (
        await case.db.scalar(
            select(func.count())
            .select_from(Reference)
            .where(Reference.employment_id == case.emp.id)
        )
        == 0
    )
    assert (
        await case.db.scalar(
            select(func.count()).select_from(Invitation).where(Invitation.reference_id == row.id)
        )
        == 0
    )
    assert (
        await case.db.scalar(
            select(func.count())
            .select_from(EmailDeliveryLog)
            .where(EmailDeliveryLog.payload["employment_id"].astext == str(case.emp.id))
        )
        == 0
    )
    with pytest.raises(NotFoundError):
        await case.svc.context(token)


async def test_inactive_owner_fails_closed(case):
    _, _, token = await invited(case)
    case.user.is_active = False
    await case.db.flush()
    with pytest.raises(NotFoundError):
        await case.svc.respond(token, response())


@pytest.mark.parametrize("email_source", ["candidate", "hr"])
async def test_hr_correction_rechecks_distinct_identity(case, email_source):
    await case.svc.nominate(case.user.id, case.emp.id, nomination())
    row = await case.svc.active(case.emp.id)
    with pytest.raises(ValidationAppError) as error:
        await case.svc.validate_manager(
            case.hr,
            ManagerValidation(
                nomination_id=row.id,
                relationship_decision="confirmed_reporting_manager",
                contact_provenance="hr_corrected",
                confirmed_contact=nomination(
                    work_email=case.user.email
                    if email_source == "candidate"
                    else case.hr.verifier_email
                ),
            ),
        )
    assert error.value.code == "reference_identity_conflict"


@pytest.mark.parametrize("pack_origin", ["https://app.kairoid.com", "https://candidate.example.test"])
async def test_renew_expired_hr_capability_preserves_factual_decision(case, pack_origin):
    case.svc.settings = case.svc.settings.model_copy(update={
        "employer_portal_base_url": "https://hr.kairoid.com/",
        "document_pack_public_base_url": pack_origin,
        "manager_reference_public_base_url": "https://api.kairoid.com",
    })
    old, _, manager_token = await invited(case)
    case.hr.expires_at = datetime.now(UTC) - timedelta(days=1)
    case.hr.remarks = "Original factual response"
    case.hr.response_metadata = {"employment_existed": True}
    await case.db.flush()
    await case.svc.nominate(
        case.user.id, case.emp.id, nomination(full_name="Replacement Manager"), replace=True
    )
    row = await case.svc.active(case.emp.id)
    payload = SendReference(nomination_id=row.id, idempotency_key=uuid4())
    assert (await case.svc.renew_hr_link(case.emp.id, payload))["delivery_status"] == "sent"
    message = case.svc.provider.send.call_args.args[0]
    token = re.search(r"/employer-verification/([^\s]+)", message.text_body).group(1)
    assert f"https://hr.kairoid.com/employer-verification/{token}" in message.text_body
    assert pack_origin not in message.text_body
    employer = EmployerVerificationService(case.db, case.svc.settings)
    with pytest.raises(NotFoundError):
        await employer._load_portal_token_for_update(case.token)
    hr = await employer._load_portal_token_for_update(token)
    assert hr.response == "confirmed" and hr.remarks == "Original factual response"
    assert hr.response_metadata == {"employment_existed": True}
    assert case.emp.verification_status == "verified"
    with pytest.raises(ReferenceGateError):
        await case.svc.send(case.emp.id, payload)
    assert (await case.svc.renew_hr_link(case.emp.id, payload))["idempotent"]
    await case.svc.validate_manager(
        hr,
        ManagerValidation(
            nomination_id=row.id,
            relationship_decision="confirmed_reporting_manager",
            contact_provenance="hr_confirmed",
        ),
    )
    await case.db.commit()
    assert row.status == "ready_to_invite"


async def test_real_hr_response_atomic_and_no_confidential_timeline(case):
    await case.svc.nominate(case.user.id, case.emp.id, nomination())
    row = await case.svc.active(case.emp.id)
    case.emp.verification_status = "submitted"
    request = VerificationRequest(
        subject_name=case.emp.subject_full_name,
        subject_email=case.user.email,
        subject_user_id=case.user.id,
        employment_id=case.emp.id,
        requested_by_user_id=case.user.id,
        request_type=VerificationRequestType.EMPLOYMENT,
        status=VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE,
    )
    case.db.add(request)
    await case.db.flush()
    case.hr.verification_request_id = request.id
    case.hr.response = "pending"
    await case.db.flush()
    employer = EmployerVerificationService(case.db, case.svc.settings)
    employer._notify_admin_quality_review_needed = AsyncMock()
    result = await employer.verify_from_portal(
        case.token,
        EmployerVerifyBody(
            employment_existed=True,
            dates_correct=True,
            role_correct=True,
            hr_reference=HRReference(comments="Private HR answer"),
            manager_validation=ManagerValidation(
                nomination_id=row.id,
                relationship_decision="confirmed_reporting_manager",
                contact_provenance="hr_confirmed",
            ),
        ),
    )
    assert result.verification_request_status == "pending_admin_quality_review"
    assert case.emp.verification_status == "submitted"
    assert (await case.svc.active(case.emp.id, "hr_reference")).status == "completed"
    events = (
        await case.db.scalars(
            select(VerificationRequestEvent).where(
                VerificationRequestEvent.verification_request_id == request.id
            )
        )
    ).all()
    assert "Private" not in str([event.metadata_payload for event in events])
    assert "manager" not in str(case.hr.response_metadata)
    assert (
        await employer.verify_from_portal(
            case.token,
            EmployerVerifyBody(employment_existed=True, dates_correct=True, role_correct=True),
        )
    ).idempotent


async def test_reservation_rechecks_replacement_before_delivery(case, monkeypatch):
    row = await approved(case)
    original = case.svc.employment
    calls = 0

    async def replace_between_transactions(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            other_service = EmploymentReferenceService(case.db, case.svc.settings)
            await other_service.nominate(
                case.user.id, case.emp.id, nomination(full_name="Changed Before Send"), replace=True
            )
        return await original(*args, **kwargs)

    monkeypatch.setattr(case.svc, "employment", replace_between_transactions)
    with pytest.raises(ConflictError):
        await case.svc.send(
            case.emp.id, SendReference(nomination_id=row.id, idempotency_key=uuid4())
        )
    case.svc.provider.send.assert_not_awaited()
    assert not row.active


async def test_ambiguous_delivery_is_not_automatically_retried(case):
    row = await approved(case)
    case.svc.provider.send.side_effect = TimeoutError()
    payload = SendReference(nomination_id=row.id, idempotency_key=uuid4())
    assert (await case.svc.send(case.emp.id, payload))["delivery_status"] == "unknown"
    assert (await case.svc.send(case.emp.id, payload))["idempotent"]
    assert case.svc.provider.send.await_count == 1
    assert (await case.svc.invitation(row.id)).revoked_at


def test_logging_redacts_manager_credentials_in_both_access_modes():
    from app.logging.request_redaction import redact_request_credentials
    from app.logging.setup import CredentialRedactionFilter

    url = "/api/v1/public/manager-references/private-secret/response"
    assert "private-secret" not in redact_request_credentials(url)
    record = logging.LogRecord(
        "uvicorn.access",
        20,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("local", "POST", url, "1.1", 200),
        None,
    )
    CredentialRedactionFilter().filter(record)
    assert "private-secret" not in record.getMessage()


async def test_public_authorization_errors_headers_and_page(case):
    from app.api.v1.routes.employment_references import service
    from app.main import app

    _, _, token = await invited(case)
    app.dependency_overrides[service] = lambda: case.svc
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://api.example.test"
        ) as client:
            page = await client.get(f"/api/v1/public/manager-references/{token}/page")
            assert page.status_code == 200 and "<form" in page.text
            assert "form-action 'self'" in page.headers["content-security-policy"]
            for method, suffix in (("GET", ""), ("POST", "/decline"), ("POST", "/response")):
                result = await client.request(
                    method,
                    f"/api/v1/public/manager-references/{token}{suffix}",
                    headers={"Authorization": "Bearer candidate-jwt"},
                    json=response().model_dump(mode="json"),
                )
                assert result.status_code == 403
                assert "no-store" in result.headers["cache-control"]
                assert result.headers["referrer-policy"] == "no-referrer"
            result = await client.get("/api/v1/public/manager-references/invalid-token-value")
            assert result.status_code == 404 and "no-store" in result.headers["cache-control"]
            result = await client.get(f"/api/v1/public/manager-references/{token}/decline")
            assert result.status_code == 405
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("state", ["invalid", "expired", "revoked"])
async def test_manager_browser_rejection_is_safe_html_but_api_stays_json(case, state):
    from app.api.v1.routes.employment_references import service
    from app.main import app

    row, _, token = await invited(case)
    invitation = await case.svc.invitation(row.id)
    if state == "invalid":
        token = "synthetic-unknown-capability-" + uuid4().hex
    elif state == "expired":
        invitation.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    else:
        invitation.revoked_at = datetime.now(UTC)
    await case.db.commit()
    app.dependency_overrides[service] = lambda: case.svc
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://api.example.test"
        ) as client:
            path = f"/api/v1/public/manager-references/{token}"
            for method, suffix in (("GET", "/page"), ("POST", "/respond-form")):
                result = await client.request(method, path + suffix, data={"action": "decline"})
                assert result.status_code == 404
                assert result.headers["content-type"].startswith("text/html")
                assert "This reference link is no longer available." in result.text
                assert "<form" not in result.text and '"error"' not in result.text
                for private in (token, str(row.id), str(invitation.id), str(case.emp.id)):
                    assert private not in result.text
                assert "no-store" in result.headers["cache-control"]
                assert result.headers["referrer-policy"] == "no-referrer"
                assert "default-src 'none'" in result.headers["content-security-policy"]
            for method, suffix in (("GET", ""), ("POST", "/decline"), ("POST", "/response")):
                result = await client.request(
                    method, path + suffix, json=response().model_dump(mode="json")
                )
                assert result.status_code == 404
                assert result.headers["content-type"].startswith("application/json")
                assert result.json()["error"]["code"] == "not_found"
            assert invitation.opened_at is None
            assert row.answers == {} and row.completed_at is None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("method", "suffix", "headers"),
    [
        (
            "GET",
            "/page",
            {"Authorization": "Bearer synthetic-not-a-candidate-session"},
        ),
        (
            "POST",
            "/respond-form",
            {"Origin": "https://untrusted.example.test"},
        ),
    ],
)
async def test_manager_browser_capability_guards_still_reject_before_service(
    case, method, suffix, headers
):
    from app.api.v1.routes.employment_references import service
    from app.main import app

    guarded = SimpleNamespace(context=AsyncMock(), respond=AsyncMock())
    app.dependency_overrides[service] = lambda: guarded
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://api.example.test"
        ) as client:
            result = await client.request(
                method,
                "/api/v1/public/manager-references/synthetic-invalid" + suffix,
                headers=headers,
                data={"action": "decline"},
            )
            assert result.status_code == 403
            assert result.headers["content-type"].startswith("text/html")
            assert "This reference link is no longer available." in result.text
            guarded.context.assert_not_awaited()
            guarded.respond.assert_not_awaited()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("origin", ["https://api.example.test", None, "null"])
async def test_manager_browser_form_tolerates_private_browser_session_headers(
    case, monkeypatch, origin
):
    from app.api.v1.routes.employment_references import service
    from app.main import app

    row, _, token = await invited(case)
    monkeypatch.setattr(
        "app.api.dependencies.reference_capability.get_settings",
        lambda: case.svc.settings,
    )
    app.dependency_overrides[service] = lambda: case.svc
    headers = {"Authorization": "Bearer incidental-browser-session"}
    if origin is not None:
        headers["Origin"] = origin
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://api.example.test"
        ) as client:
            path = f"/api/v1/public/manager-references/{token}"
            data = response().model_dump(mode="json", exclude_none=True)
            data.update(attested="yes", action="submit")
            result = await client.post(path + "/respond-form", headers=headers, data=data)
            assert result.status_code == 200
            assert "Thank you. Your response has been recorded." in result.text
            assert row.status == "completed"

            api_result = await client.post(path + "/response", headers=headers, json=data)
            assert api_result.status_code == 403
    finally:
        app.dependency_overrides.clear()


async def test_manager_valid_browser_submission_and_completed_state_unchanged(case):
    from app.api.v1.routes.employment_references import service
    from app.main import app

    row, _, token = await invited(case)
    app.dependency_overrides[service] = lambda: case.svc
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://api.example.test"
        ) as client:
            path = f"/api/v1/public/manager-references/{token}"
            page = await client.get(path + "/page")
            assert page.status_code == 200 and "Professional reference" in page.text
            assert "action='respond-form'" in page.text
            assert token not in page.text
            data = response().model_dump(mode="json", exclude_none=True)
            data.update(attested="yes", action="submit")
            result = await client.post(path + "/respond-form", data=data)
            assert result.status_code == 200
            assert "Thank you. Your response has been recorded." in result.text
            assert "Reference submitted" in result.text and 'role="status"' in result.text
            assert row.status == "completed"
            page = await client.get(path + "/page")
            assert page.status_code == 200
            assert "Your response has already been recorded." in page.text
            assert "Reference already submitted" in page.text
            assert "<form" not in page.text and token not in page.text
            assert page.headers["content-type"].startswith("text/html")
            context = await client.get(path)
            assert context.json()["status"] == "completed"
    finally:
        app.dependency_overrides.clear()


async def test_manager_browser_error_never_reflects_domain_details(case):
    from app.api.v1.routes.employment_references import service
    from app.main import app

    private = "<script>private-database-id</script>"
    stub = SimpleNamespace(context=AsyncMock(side_effect=NotFoundError(private)))
    app.dependency_overrides[service] = lambda: stub
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://api.example.test"
        ) as client:
            result = await client.get("/api/v1/public/manager-references/synthetic-invalid/page")
            assert result.status_code == 404
            assert "private-database-id" not in result.text
            assert "<script>" not in result.text
    finally:
        app.dependency_overrides.clear()


def test_configured_origin_validation_and_proxy_safe_checks(monkeypatch):
    from starlette.requests import Request

    from app.api.dependencies.reference_capability import employer_capability, manager_capability
    from app.exceptions import ForbiddenError

    settings = get_settings().model_copy(
        update={
            "manager_reference_public_base_url": "https://staging-api.kairoid.com",
            "cors_origins": ["https://hr.example.com"],
        }
    )
    monkeypatch.setattr("app.api.dependencies.reference_capability.get_settings", lambda: settings)

    def request(origin):
        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/",
                "scheme": "http",
                "server": ("internal", 8000),
                "headers": [(b"origin", origin.encode())],
            }
        )

    manager_capability(request("https://staging-api.kairoid.com"))
    employer_capability(request("https://hr.example.com"))
    with pytest.raises(ForbiddenError):
        manager_capability(request("https://hr.example.com"))
    with pytest.raises(ForbiddenError):
        employer_capability(request("https://untrusted.example.com"))
    for value in (
        "http://api.example.com",
        "https://api.example.com/path",
        "https://user:pass@api.example.com",
        "https://api.example.com/?token=bad",
    ):
        with pytest.raises(ValidationError):
            type(settings)(MANAGER_REFERENCE_PUBLIC_BASE_URL=value)


async def test_candidate_has_no_invite_or_internal_report_authority(case):
    from app.api.dependencies.auth import CurrentUser, get_current_user
    from app.api.v1.routes.employment_references import service
    from app.main import app

    row = await approved(case)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=case.user.id, email=case.user.email, role="user"
    )
    app.dependency_overrides[service] = lambda: case.svc
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            payload = SendReference(nomination_id=row.id, idempotency_key=uuid4()).model_dump(
                mode="json"
            )
            assert (
                await client.get(f"/api/v1/employments/{case.emp.id}/references")
            ).status_code == 200
            assert (
                await client.post(
                    f"/api/v1/employments/{case.emp.id}/references/reporting-manager/invite",
                    json=payload,
                )
            ).status_code == 404
            for suffix in ("reporting-manager/invite", "hr-link/renew"):
                assert (
                    await client.post(
                        f"/api/v1/admin/employments/{case.emp.id}/references/{suffix}", json=payload
                    )
                ).status_code == 403
            assert (
                await client.get(f"/api/v1/admin/employments/{case.emp.id}/references")
            ).status_code == 403
    finally:
        app.dependency_overrides.clear()


async def test_phone_only_nomination_is_not_delivery_proof(case):
    await case.svc.nominate(
        case.user.id, case.emp.id, nomination(work_email=None, phone="+919876543210")
    )
    row = await case.svc.active(case.emp.id)
    await case.svc.validate_manager(
        case.hr,
        ManagerValidation(
            nomination_id=row.id,
            relationship_decision="confirmed_reporting_manager",
            contact_provenance="hr_confirmed",
        ),
    )
    await case.db.flush()
    safe = await case.svc.summary(case.user.id, case.emp.id)
    assert safe.reporting_manager.invitation_blocked_reason == "email_required"
    with pytest.raises(ValidationAppError) as error:
        await case.svc.send(
            case.emp.id, SendReference(nomination_id=row.id, idempotency_key=uuid4())
        )
    assert error.value.code == "reference_email_required"


async def test_cross_employment_nomination_cannot_validate_or_send(case):
    row = await approved(case)
    for operation in (
        lambda: case.svc.validate_manager(
            case.hr,
            ManagerValidation(
                nomination_id=uuid4(),
                relationship_decision="confirmed_reporting_manager",
                contact_provenance="hr_confirmed",
            ),
        ),
        lambda: case.svc.send(
            case.emp.id, SendReference(nomination_id=uuid4(), idempotency_key=uuid4())
        ),
    ):
        with pytest.raises(ConflictError):
            await operation()
    with pytest.raises(ValidationError):
        response(employment_id=str(case.emp.id))
    assert row.status == "ready_to_invite"


async def test_explicit_change_can_request_fresh_review_of_same_nominee(case):
    row = await approved(case, contact_provenance="hr_cannot_confirm")
    same = await case.svc.nominate(case.user.id, case.emp.id, nomination())
    assert same.reporting_manager.nomination_id == row.id
    changed = await case.svc.nominate(case.user.id, case.emp.id, nomination(), replace=True)
    assert changed.reporting_manager.nomination_id != row.id
    assert not changed.reporting_manager.nomination_locked
    assert changed.reporting_manager.status == "awaiting_hr_validation"


@pytest.mark.parametrize("actor", ["candidate", "hr"])
async def test_resend_rechecks_candidate_and_hr_email_collisions(case, actor):
    row, _, _ = await invited(case)
    invitation = await case.svc.invitation(row.id)
    invitation.created_at = datetime.now(UTC) - timedelta(minutes=16)
    if actor == "hr":
        case.hr.verifier_email = "manager@example.com"
    else:
        case.user.email = "manager@example.com"
    await case.db.flush()
    with pytest.raises(ReferenceGateError if actor == "hr" else ValidationAppError):
        await case.svc.send(
            case.emp.id, SendReference(nomination_id=row.id, idempotency_key=uuid4())
        )
    assert case.svc.provider.send.await_count == 1


async def test_factual_binding_rechecked_after_send_reservation(case, monkeypatch):
    row = await approved(case)
    original = case.svc.employment
    calls = 0

    async def change_claim_after_reservation(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            case.emp.job_title = "Changed during reservation gap"
            await case.db.flush()
        return await original(*args, **kwargs)

    monkeypatch.setattr(case.svc, "employment", change_claim_after_reservation)
    with pytest.raises(ReferenceGateError):
        await case.svc.send(
            case.emp.id, SendReference(nomination_id=row.id, idempotency_key=uuid4())
        )
    case.svc.provider.send.assert_not_awaited()


async def test_stale_hr_token_read_rechecks_hash_after_owner_wait(case, monkeypatch):
    employer = EmployerVerificationService(case.db, case.svc.settings)
    original = EmploymentReferenceService.employment

    async def rotate_while_waiting(self, *args, **kwargs):
        case.hr.token_hash = hash_refresh_token("replacement-capability-" + uuid4().hex)
        await case.db.flush()
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(EmploymentReferenceService, "employment", rotate_while_waiting)
    with pytest.raises(NotFoundError):
        await employer._load_portal_token(case.token)


@pytest.mark.parametrize("change", ["cycle", "response", "verifier", "claim"])
async def test_approval_bound_to_factual_cycle_and_claim(case, change):
    row, _, token = await invited(case)
    invitation = await case.svc.invitation(row.id)
    invitation.created_at = datetime.now(UTC) - timedelta(minutes=16)
    if change == "cycle":
        case.hr.sent_at = datetime.now(UTC) + timedelta(seconds=1)
    elif change == "response":
        case.hr.responded_at = datetime.now(UTC) + timedelta(seconds=1)
    elif change == "verifier":
        case.hr.verifier_email = "another-hr@example.com"
    else:
        case.emp.job_title = "Changed claim after rejection"
    await case.db.flush()
    with pytest.raises(ReferenceGateError):
        await case.svc.send(
            case.emp.id, SendReference(nomination_id=row.id, idempotency_key=uuid4())
        )
    with pytest.raises(NotFoundError):
        await case.svc.respond(token, response())
    assert case.svc.provider.send.await_count == 1
    summary = await case.svc.summary(case.user.id, case.emp.id)
    assert not summary.reporting_manager.relationship_confirmed_by_hr
    assert summary.reporting_manager.status == "needs_review"
    assert summary.hr_reference.status == "pending"
    assert "factual_binding" not in str(await case.svc.hr_context(case.emp.id))
    await case.svc.validate_manager(
        case.hr,
        ManagerValidation(
            nomination_id=row.id,
            relationship_decision="confirmed_reporting_manager",
            contact_provenance="hr_confirmed",
        ),
    )
    fresh = await case.svc.active(case.emp.id)
    assert fresh.id != row.id and fresh.status == "ready_to_invite"
    assert not row.active and row.validation.get("factual_binding")


async def test_actual_hr_row_reuse_invalidates_prior_manager_approval(case):
    from app.schemas.employer_verification import EmployerVerificationRequestBody

    row, _, old_token = await invited(case)
    case.emp.verification_status = "draft"
    await case.db.flush()
    employer = EmployerVerificationService(case.db, case.svc.settings)
    employer._email = SimpleNamespace(send_employer_verification=AsyncMock())
    await employer.request_verification(
        case.user.id,
        case.emp.id,
        EmployerVerificationRequestBody(
            contact_name="Second HR", verifier_email="second-hr@example.com", relationship="hr"
        ),
    )
    assert not row.active
    fresh = await case.svc.active(case.emp.id)
    assert fresh.status == "awaiting_hr_validation"
    case.hr.response = "confirmed"
    case.hr.responded_at = datetime.now(UTC)
    case.emp.verification_status = "verified"
    await case.db.flush()
    with pytest.raises(ReferenceGateError):
        await case.svc.send(
            case.emp.id, SendReference(nomination_id=fresh.id, idempotency_key=uuid4())
        )
    with pytest.raises(NotFoundError):
        await case.svc.context(old_token)
    assert case.svc.provider.send.await_count == 1


def test_migration_only_adds_three_empty_tables(monkeypatch):
    import importlib.util
    from pathlib import Path

    path = Path(__file__).parents[1] / "alembic/versions/087_employment_references.py"
    spec = importlib.util.spec_from_file_location("reference_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    tables = []
    monkeypatch.setattr(
        migration,
        "op",
        SimpleNamespace(
            create_table=lambda name, *args: tables.append(name),
            create_index=lambda *args, **kwargs: None,
        ),
    )
    migration.upgrade()
    assert migration.revision == "087" and migration.down_revision == "086"
    assert tables == [
        "employment_references",
        "employment_reference_invitations",
        "employment_reference_events",
    ]


async def test_held_delivery_lock_blocks_concurrent_replacement():
    """Real independent connections, unlike the savepoint fixtures above."""
    assert engine.url.host in {"localhost", "127.0.0.1"}
    uid = eid = None
    settings = get_settings().model_copy(
        update={"manager_reference_public_base_url": "https://api.example.test"}
    )
    try:
        async with AsyncSession(engine, expire_on_commit=False) as setup:
            user = User(email=f"race-{uuid4()}@example.com", role="user", is_active=True)
            setup.add(user)
            await setup.flush()
            uid = user.id
            emp = Employment(
                created_by_user_id=uid,
                subject_full_name="Race Candidate",
                employer_legal_name="Race Employer",
                job_title="Engineer",
                verification_status="verified",
            )
            setup.add(emp)
            await setup.flush()
            eid = emp.id
            hr = EmployerVerificationRequest(
                employment_id=eid,
                contact_name="Race HR",
                verifier_email="race-hr@example.com",
                relationship_to_subject="hr",
                token_hash=hash_refresh_token(uuid4().hex),
                response="confirmed",
                sent_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
            setup.add(hr)
            await setup.commit()
            svc = EmploymentReferenceService(setup, settings)
            await svc.nominate(uid, eid, nomination())
            row = await svc.active(eid)
            await svc.validate_manager(
                hr,
                ManagerValidation(
                    nomination_id=row.id,
                    relationship_decision="confirmed_reporting_manager",
                    contact_provenance="hr_confirmed",
                ),
            )
            rid = row.id
            await setup.commit()
        entered, release, changing = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def provider_send(message):
            entered.set()
            await asyncio.wait_for(release.wait(), 10)
            return EmailSendResult(provider="console", status="sent")

        async def sending():
            async with AsyncSession(engine, expire_on_commit=False) as db:
                svc = EmploymentReferenceService(db, settings)
                svc.provider = SimpleNamespace(provider_name="console", send=provider_send)
                return await svc.send(
                    eid, SendReference(nomination_id=rid, idempotency_key=uuid4())
                )

        async def changing_nomination():
            async with AsyncSession(engine, expire_on_commit=False) as db:
                changing.set()
                return await EmploymentReferenceService(db, settings).nominate(
                    uid, eid, nomination(full_name="Replacement During Delivery"), replace=True
                )

        send_task = asyncio.create_task(sending())
        await asyncio.wait_for(entered.wait(), 10)
        change_task = asyncio.create_task(changing_nomination())
        await changing.wait()
        await asyncio.sleep(0.1)
        assert not change_task.done()
        release.set()
        sent, changed = await asyncio.wait_for(asyncio.gather(send_task, change_task), 10)
        assert sent["delivery_status"] == "sent"
        assert changed.reporting_manager.status == "awaiting_hr_validation"
        async with AsyncSession(engine) as db:
            assert (await db.get(Reference, rid)).active is False
            invitation = await db.scalar(select(Invitation).where(Invitation.reference_id == rid))
            assert invitation.revoked_at is not None
    finally:
        async with AsyncSession(engine) as cleanup:
            if eid:
                await cleanup.execute(
                    delete(EmailDeliveryLog).where(
                        EmailDeliveryLog.payload["employment_id"].astext == str(eid)
                    )
                )
                await cleanup.execute(delete(Employment).where(Employment.id == eid))
            if uid:
                await cleanup.execute(delete(User).where(User.id == uid))
            await cleanup.commit()
