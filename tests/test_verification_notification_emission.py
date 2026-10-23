"""Privacy-safe Candidate notification emission contracts."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.notifications.contracts import NotificationPreferenceDecision
from app.services.account_notification import notify_identity_result, notify_password_changed
from app.services.notification_in_app_channel import NotificationInAppChannel
from app.services.trust_invitation_service import TrustInvitationService
from app.services.verification_notification import notify_verification_attention
from app.services.verification_request_admin_review_service import (
    VerificationRequestAdminReviewService,
)
from app.trust_invitations.enums import TrustInvitationEventType
from app.verification_requests.enums import VerificationRequestStatus
from tests.test_notification_service import _build_service


def request_fixture():
    return SimpleNamespace(
        public_id=uuid4(),
        subject_user_id=uuid4(),
        subject_email="synthetic@example.test",
        subject_name="Synthetic Candidate",
        organization=None,
        target_organization_name="Synthetic Organization",
        request_type="education",
        employment_id=None,
        education_id=uuid4(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome,title",
    [
        ("verified", "Verification approved"),
        ("rejected", "Verification rejected"),
        ("unable_to_verify", "Verification could not be completed"),
    ],
)
async def test_final_outcome_keeps_existing_event_and_recipient(outcome, title):
    request = request_fixture()
    service = VerificationRequestAdminReviewService.__new__(VerificationRequestAdminReviewService)
    service._notifications = SimpleNamespace(create_and_dispatch=AsyncMock())
    service._session = SimpleNamespace(rollback=AsyncMock())
    await service._notify_finalization(request, uuid4(), outcome)
    notice = service._notifications.create_and_dispatch.await_args.args[0]
    assert notice.event_type == "verification_completed"
    assert notice.title == title
    assert notice.metadata["outcome"] == outcome
    assert notice.recipient_user_id == request.subject_user_id
    assert notice.metadata["verification_request_public_id"] == str(request.public_id)
    assert notice.dedupe_key == f"verification-final:{request.public_id}:{outcome}:candidate"


@pytest.mark.asyncio
async def test_attention_has_safe_metadata_and_dedupes_same_transition():
    request = request_fixture()
    event = SimpleNamespace(public_id=uuid4())
    service = _build_service(
        dispatcher=SimpleNamespace(dispatch=NotificationInAppChannel().send),
        preference_decision=NotificationPreferenceDecision(enabled=True, selected_channel="in_app"),
    )
    session = SimpleNamespace(rollback=AsyncMock())
    for _ in range(2):
        await notify_verification_attention(service, session, request, event)
    assert len(service._notifications.items) == 1
    notice = service._notifications.items[0]
    assert notice.recipient_user_id == request.subject_user_id
    assert notice.read_at is None
    assert notice.payload == {}
    assert notice.recipient_email is None
    assert notice.metadata_payload["verification_request_public_id"] == str(request.public_id)
    assert notice.title == "Verification needs your attention"
    session.rollback.assert_not_awaited()
    await notify_verification_attention(
        service, session, request, SimpleNamespace(public_id=uuid4())
    )
    assert len(service._notifications.items) == 2


@pytest.mark.asyncio
async def test_notification_failure_does_not_fail_committed_workflow():
    session = SimpleNamespace(rollback=AsyncMock())
    await notify_verification_attention(
        SimpleNamespace(create_and_dispatch=AsyncMock(side_effect=RuntimeError("synthetic"))),
        session,
        request_fixture(),
        SimpleNamespace(public_id=uuid4()),
    )
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_inbox_only_notice_does_not_attempt_email_preference_fallback():
    service = _build_service(
        dispatcher=SimpleNamespace(dispatch=NotificationInAppChannel().send),
        preference_decision=NotificationPreferenceDecision(enabled=True, selected_channel="email"),
    )
    await notify_verification_attention(
        service,
        SimpleNamespace(rollback=AsyncMock()),
        request_fixture(),
        SimpleNamespace(public_id=uuid4()),
    )
    assert service._notifications.items[0].channel == "in_app"
    assert service._notifications.items[0].status == "sent"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome", ["VERIFIED_MATCH", "PARTIAL_MATCH", "UNABLE_TO_VERIFY", "MISMATCH"]
)
async def test_identity_notice_contains_only_safe_result_metadata(monkeypatch, outcome):
    send = AsyncMock()
    monkeypatch.setattr(
        "app.services.account_notification.NotificationService",
        lambda *args: SimpleNamespace(create_and_dispatch=send),
    )
    user_id = uuid4()
    await notify_identity_result(
        None, None, user_id, document_type="DRVLC", result=outcome, event_id="synthetic-attempt"
    )
    notice = send.await_args.args[0]
    assert notice.metadata == {"document_type": "DRVLC", "outcome": outcome}
    assert notice.payload == {}
    assert notice.recipient_user_id == user_id
    assert notice.recipient_email is None
    assert "verification_request_public_id" not in notice.metadata
    assert notice.channel == "in_app"


@pytest.mark.asyncio
async def test_password_notice_has_no_recovery_secret(monkeypatch):
    send = AsyncMock()
    monkeypatch.setattr(
        "app.services.account_notification.NotificationService",
        lambda *args: SimpleNamespace(create_and_dispatch=send),
    )
    user_id = uuid4()
    await notify_password_changed(None, None, user_id, uuid4())
    notice = send.await_args.args[0]
    assert notice.event_type == "password_changed"
    assert notice.recipient_user_id == user_id
    assert notice.payload == notice.metadata == {}
    assert notice.recipient_email is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exists,active,verified,linked",
    [
        (True, True, True, True),
        (True, False, True, False),
        (True, True, False, False),
        (False, False, False, False),
    ],
)
async def test_invitation_links_only_active_verified_email_owner(
    monkeypatch,
    exists,
    active,
    verified,
    linked,
):
    recipient = SimpleNamespace(
        id=uuid4(), is_active=active, email_verified_at=datetime.now(UTC) if verified else None
    )
    lookup = AsyncMock(return_value=recipient if exists else None)
    monkeypatch.setattr(
        "app.services.trust_invitation_service.UserRepository",
        lambda session: SimpleNamespace(get_by_email=lookup),
    )
    service = TrustInvitationService.__new__(TrustInvitationService)
    service._session = None
    service._notifications = SimpleNamespace(create_and_dispatch=AsyncMock())
    service._build_invitation_url = lambda value: "https://example.invalid/synthetic"
    invitation = SimpleNamespace(
        public_id=uuid4(),
        subject_email="Synthetic@Example.Invalid",
        subject_name="Synthetic",
        organization=SimpleNamespace(name="Synthetic", public_id=uuid4()),
        expires_at=datetime.now(UTC),
        purpose="synthetic",
    )
    await service._deliver_invitation(
        invitation,
        actor_user_id=None,
        trigger_event=TrustInvitationEventType.SENT,
        record_event=False,
    )
    lookup.assert_awaited_once_with("synthetic@example.invalid")
    notice = service._notifications.create_and_dispatch.await_args.args[0]
    assert notice.recipient_user_id == (recipient.id if linked else None)
    assert notice.dedupe_key == f"trust-invitation:{invitation.public_id}:sent"
    assert "verification_request_public_id" not in notice.metadata


@pytest.mark.asyncio
async def test_admin_corrections_emit_after_workflow_commit():
    request = request_fixture()
    request.id = uuid4()
    event = SimpleNamespace(public_id=uuid4())
    service = VerificationRequestAdminReviewService.__new__(VerificationRequestAdminReviewService)
    service._require_admin_reviewable_request = AsyncMock(return_value=request)
    service._get_or_create_review = AsyncMock(return_value=SimpleNamespace())
    service._workflow = SimpleNamespace(transition=AsyncMock(return_value=event))
    service._session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    service._requests = SimpleNamespace(get_by_public_id=AsyncMock(return_value=request))
    service._to_request_response = AsyncMock(return_value="response")

    async def send(notice, **kwargs):
        service._session.commit.assert_awaited_once()
        assert notice.recipient_user_id == request.subject_user_id
        assert str(event.public_id) in notice.dedupe_key

    service._notifications = SimpleNamespace(create_and_dispatch=AsyncMock(side_effect=send))
    assert (
        await service.request_corrections(
            uuid4(), request.public_id, SimpleNamespace(corrections=[])
        )
        == "response"
    )
    service._notifications.create_and_dispatch.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", [VerificationRequestStatus.REJECTED, VerificationRequestStatus.UNABLE_TO_VERIFY]
)
async def test_pre_dispatch_closed_request_emits_final_notice_after_commit(status):
    request = request_fixture()
    request.education_id = None
    service = VerificationRequestAdminReviewService.__new__(VerificationRequestAdminReviewService)
    service._get_or_create_review = AsyncMock(return_value=SimpleNamespace())
    service._workflow = SimpleNamespace(transition=AsyncMock())
    service._session = SimpleNamespace(commit=AsyncMock())
    service._requests = SimpleNamespace(get_by_public_id=AsyncMock(return_value=request))
    service._to_request_response = AsyncMock(return_value="response")
    service._notify_finalization = AsyncMock()
    actor = uuid4()
    await service._close_pre_dispatch_request(
        request, actor, target_status=status, decision_summary="Synthetic decision"
    )
    service._session.commit.assert_awaited_once()
    service._notify_finalization.assert_awaited_once_with(request, actor, status.value)
