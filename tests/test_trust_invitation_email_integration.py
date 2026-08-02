"""Unit tests for Trust Invitation email integration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.config import Settings
from app.notifications.contracts import NotificationRequest
from app.organization.enums import OrganizationRole
from app.schemas.trust_invitation import TrustInvitationCreateRequest
from app.services.trust_invitation_service import TrustInvitationService
from app.trust_invitations.enums import TrustInvitationStatus


def _settings(**overrides: object) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://kairo:kairo@localhost:5432/kairo",
        "jwt_secret_key": "test-jwt-secret-key-32-chars-minimum!!",
        "app_public_base_url": "https://api.example.com",
    }
    base.update(overrides)
    return Settings(**base)


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def refresh(self, obj) -> None:  # noqa: ANN001
        return None


class FakeTrustInvitationRepository:
    def __init__(self, organization) -> None:  # noqa: ANN001
        self.organization = organization
        self.invitation = None
        self.events = []

    async def create(self, invitation):  # noqa: ANN001
        invitation.id = 1
        invitation.public_id = uuid4()
        invitation.created_at = datetime.now(tz=UTC)
        invitation.updated_at = invitation.created_at
        self.invitation = invitation
        return invitation

    async def add_event(self, event):  # noqa: ANN001
        event.id = uuid4()
        event.occurred_at = datetime.now(tz=UTC)
        self.events.append(event)
        return event

    async def get_by_public_id(self, invitation_public_id, include_events: bool = False):  # noqa: ANN001
        if self.invitation is None or self.invitation.public_id != invitation_public_id:
            return None
        created_by_user = SimpleNamespace(
            id=self.invitation.created_by_user_id,
            email="owner@example.com",
            full_name="Owner User",
        )
        events = []
        if include_events:
            for event in self.events:
                events.append(
                    SimpleNamespace(
                        id=event.id,
                        event_type=event.event_type,
                        occurred_at=event.occurred_at,
                        actor_user_id=event.actor_user_id,
                        actor_user=created_by_user if event.actor_user_id else None,
                        metadata_payload=event.metadata_payload,
                    )
                )
        return SimpleNamespace(
            id=self.invitation.id,
            public_id=self.invitation.public_id,
            organization=self.organization,
            subject_name=self.invitation.subject_name,
            subject_email=self.invitation.subject_email,
            subject_phone=self.invitation.subject_phone,
            purpose=self.invitation.purpose,
            requested_verification_types=self.invitation.requested_verification_types,
            message=self.invitation.message,
            status=self.invitation.status,
            delivery_method=self.invitation.delivery_method,
            delivery_state=self.invitation.delivery_state,
            expires_at=self.invitation.expires_at,
            sent_at=self.invitation.sent_at,
            opened_at=self.invitation.opened_at,
            accepted_at=self.invitation.accepted_at,
            cancelled_at=self.invitation.cancelled_at,
            created_by_user=created_by_user,
            accepted_by_user=None,
            verification_requests=[],
            events=events,
            created_at=self.invitation.created_at,
            updated_at=self.invitation.updated_at,
        )


class FakeOrganizationService:
    def __init__(self, organization) -> None:  # noqa: ANN001
        self.organization = organization

    async def require_org_member(self, actor_user_id, org_public_id):  # noqa: ANN001
        membership = SimpleNamespace(role=OrganizationRole.OWNER)
        return self.organization, membership


class FakeNotificationService:
    def __init__(self, *, should_raise: bool = False) -> None:
        self.should_raise = should_raise
        self.calls: list[dict[str, object]] = []

    async def create_and_dispatch(self, request: NotificationRequest, *, actor_user_id=None):  # noqa: ANN001
        self.calls.append({"request": request, "actor_user_id": actor_user_id})
        if self.should_raise:
            raise RuntimeError("notifications down")


class FakeOrganizationPersonService:
    async def resolve_for_trust_invitation(self, invitation, *, actor_user_id=None):  # noqa: ANN001
        return invitation


class FailingOrganizationPersonService:
    async def resolve_for_trust_invitation(self, invitation, *, actor_user_id=None):  # noqa: ANN001
        raise RuntimeError("people sync unavailable")


@pytest.mark.asyncio
async def test_create_trust_invitation_dispatches_notification_without_changing_response_shape() -> None:
    session = FakeSession()
    organization = SimpleNamespace(
        id=UUID("00000000-0000-0000-0000-000000000100"),
        public_id=UUID("00000000-0000-0000-0000-000000000101"),
        name="Kairo Verification Ops",
    )
    repo = FakeTrustInvitationRepository(organization)
    notifications = FakeNotificationService()
    service = TrustInvitationService(
        session,  # type: ignore[arg-type]
        _settings(),
        repo=repo,  # type: ignore[arg-type]
        organizations=FakeOrganizationService(organization),  # type: ignore[arg-type]
        notifications=notifications,  # type: ignore[arg-type]
        people=FakeOrganizationPersonService(),  # type: ignore[arg-type]
    )

    response = await service.create(
        UUID("00000000-0000-0000-0000-000000000111"),
        organization.public_id,
        TrustInvitationCreateRequest(
            subject_name="Aman Jha",
            subject_email="aman3@test.com",
            expires_at=datetime.now(tz=UTC) + timedelta(days=3),
        ),
    )

    assert response.invitation_url.startswith("https://api.example.com/api/v1/trust-invitations/")
    assert response.subject_email == "aman3@test.com"
    assert response.status == TrustInvitationStatus.PENDING
    assert len(notifications.calls) == 1
    request = notifications.calls[0]["request"]
    assert isinstance(request, NotificationRequest)
    assert request.event_type == "trust_invitation_created"
    assert request.recipient_email == "aman3@test.com"
    assert request.payload["invitation_url"] == response.invitation_url


@pytest.mark.asyncio
async def test_create_trust_invitation_survives_notification_delivery_failure() -> None:
    session = FakeSession()
    organization = SimpleNamespace(
        id=UUID("00000000-0000-0000-0000-000000000100"),
        public_id=UUID("00000000-0000-0000-0000-000000000101"),
        name="Kairo Verification Ops",
    )
    repo = FakeTrustInvitationRepository(organization)
    notifications = FakeNotificationService(should_raise=True)
    service = TrustInvitationService(
        session,  # type: ignore[arg-type]
        _settings(),
        repo=repo,  # type: ignore[arg-type]
        organizations=FakeOrganizationService(organization),  # type: ignore[arg-type]
        notifications=notifications,  # type: ignore[arg-type]
        people=FakeOrganizationPersonService(),  # type: ignore[arg-type]
    )

    response = await service.create(
        UUID("00000000-0000-0000-0000-000000000111"),
        organization.public_id,
        TrustInvitationCreateRequest(
            subject_name="Aman Jha",
            subject_email="aman3@test.com",
            expires_at=datetime.now(tz=UTC) + timedelta(days=3),
        ),
    )

    assert response.status == TrustInvitationStatus.PENDING
    assert response.invitation_url.startswith("https://api.example.com/api/v1/trust-invitations/")


@pytest.mark.asyncio
async def test_create_trust_invitation_survives_people_sync_failure() -> None:
    session = FakeSession()
    organization = SimpleNamespace(
        id=UUID("00000000-0000-0000-0000-000000000100"),
        public_id=UUID("00000000-0000-0000-0000-000000000101"),
        name="Kairo Verification Ops",
    )
    repo = FakeTrustInvitationRepository(organization)
    notifications = FakeNotificationService()
    service = TrustInvitationService(
        session,  # type: ignore[arg-type]
        _settings(),
        repo=repo,  # type: ignore[arg-type]
        organizations=FakeOrganizationService(organization),  # type: ignore[arg-type]
        notifications=notifications,  # type: ignore[arg-type]
        people=FailingOrganizationPersonService(),  # type: ignore[arg-type]
    )

    response = await service.create(
        UUID("00000000-0000-0000-0000-000000000111"),
        organization.public_id,
        TrustInvitationCreateRequest(
            subject_name="Aman Jha",
            subject_email="aman3@test.com",
            expires_at=datetime.now(tz=UTC) + timedelta(days=3),
        ),
    )

    assert response.status == TrustInvitationStatus.PENDING
    assert response.invitation_url.startswith("https://api.example.com/api/v1/trust-invitations/")
    assert session.commits >= 2
    assert session.rollbacks == 1


@pytest.mark.asyncio
async def test_accept_trust_invitation_survives_people_sync_failure() -> None:
    session = FakeSession()
    organization = SimpleNamespace(
        id=UUID("00000000-0000-0000-0000-000000000100"),
        public_id=UUID("00000000-0000-0000-0000-000000000101"),
        name="Kairo Verification Ops",
    )
    repo = FakeTrustInvitationRepository(organization)
    notifications = FakeNotificationService()
    service = TrustInvitationService(
        session,  # type: ignore[arg-type]
        _settings(),
        repo=repo,  # type: ignore[arg-type]
        organizations=FakeOrganizationService(organization),  # type: ignore[arg-type]
        notifications=notifications,  # type: ignore[arg-type]
        people=FakeOrganizationPersonService(),  # type: ignore[arg-type]
    )

    actor_id = UUID("00000000-0000-0000-0000-000000000111")
    response = await service.create(
        actor_id,
        organization.public_id,
        TrustInvitationCreateRequest(
            subject_name="Aman Jha",
            subject_email="aman3@test.com",
            expires_at=datetime.now(tz=UTC) + timedelta(days=3),
        ),
    )
    raw_token = response.invitation_url.rsplit("/", 1)[-1]

    async def _resolve_active_token(raw_token_value: str):  # noqa: ANN001
        assert raw_token_value == raw_token
        return repo.invitation

    service._resolve_active_token = _resolve_active_token  # type: ignore[assignment]
    service._people = FailingOrganizationPersonService()  # type: ignore[assignment]

    accepted = await service.accept(raw_token, actor_id, "aman3@test.com")

    assert accepted.status == TrustInvitationStatus.ACCEPTED
    assert session.commits >= 3
    assert session.rollbacks == 1
