"""Unit tests for Trust Invitation email integration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import MissingGreenlet

from app.config import Settings
from app.exceptions import ValidationAppError
from app.notifications.contracts import NotificationRequest
from app.organization.enums import OrganizationRole
from app.schemas.trust_invitation import TrustInvitationCreateRequest
from app.services.trust_invitation_service import TrustInvitationService
from app.trust_invitations.enums import TrustInvitationDeliveryState, TrustInvitationStatus


def _settings(**overrides: object) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://kairo:kairo@localhost:5432/kairo",
        "jwt_secret_key": "test-jwt-secret-key-32-chars-minimum!!",
        "candidate_portal_base_url": "https://candidate.example.com",
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
        self.get_by_public_id_calls: list[tuple[object, bool]] = []

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
        self.get_by_public_id_calls.append((invitation_public_id, include_events))
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
    def __init__(self) -> None:
        self.calls = 0

    async def resolve_for_trust_invitation(self, invitation, *, actor_user_id=None):  # noqa: ANN001
        self.calls += 1
        return invitation


class FailingOrganizationPersonService:
    async def resolve_for_trust_invitation(self, invitation, *, actor_user_id=None):  # noqa: ANN001
        raise RuntimeError("people sync unavailable")


class AssertLoadedEventsOrganizationPersonService:
    def __init__(self) -> None:
        self.calls = 0

    async def resolve_for_trust_invitation(self, invitation, *, actor_user_id=None):  # noqa: ANN001
        self.calls += 1
        _ = [event.occurred_at for event in invitation.events]
        invitation.organization_person_id = uuid4()
        return invitation


class ExpiredInvitationState:
    def __init__(self, target) -> None:  # noqa: ANN001
        object.__setattr__(self, "_target", target)

    def __getattr__(self, name: str):  # noqa: ANN201
        if name == "events":
            raise MissingGreenlet("greenlet_spawn has not been called")
        return getattr(self._target, name)

    def __setattr__(self, name: str, value) -> None:  # noqa: ANN001
        setattr(self._target, name, value)

    @property
    def events(self):  # noqa: ANN201
        raise MissingGreenlet("greenlet_spawn has not been called")


@pytest.mark.asyncio
async def test_create_trust_invitation_dispatches_notification_without_changing_response_shape(
) -> None:
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

    assert response.invitation_url.startswith("https://candidate.example.com/trust-invitations/")
    assert "/api/v1/" not in response.invitation_url
    assert response.subject_email == "aman3@test.com"
    assert response.status == TrustInvitationStatus.PENDING
    assert response.delivery_state.value == "queued"
    assert response.sent_at is None
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
    assert response.invitation_url.startswith("https://candidate.example.com/trust-invitations/")
    assert "/api/v1/" not in response.invitation_url


@pytest.mark.asyncio
async def test_create_trust_invitation_requires_candidate_portal_origin() -> None:
    session = FakeSession()
    organization = SimpleNamespace(
        id=UUID("00000000-0000-0000-0000-000000000100"),
        public_id=UUID("00000000-0000-0000-0000-000000000101"),
        name="Kairo Verification Ops",
    )
    repo = FakeTrustInvitationRepository(organization)
    service = TrustInvitationService(
        session,  # type: ignore[arg-type]
        _settings(candidate_portal_base_url=None),
        repo=repo,  # type: ignore[arg-type]
        organizations=FakeOrganizationService(organization),  # type: ignore[arg-type]
        notifications=FakeNotificationService(),  # type: ignore[arg-type]
        people=FakeOrganizationPersonService(),  # type: ignore[arg-type]
    )

    with pytest.raises(ValidationAppError, match="CANDIDATE_PORTAL_BASE_URL"):
        await service.create(
            UUID("00000000-0000-0000-0000-000000000111"),
            organization.public_id,
            TrustInvitationCreateRequest(
                subject_name="Aman Jha",
                subject_email="aman3@test.com",
                expires_at=datetime.now(tz=UTC) + timedelta(days=3),
            ),
        )


@pytest.mark.asyncio
async def test_public_lookup_records_opened_without_mutating_delivery_state() -> None:
    session = FakeSession()
    organization = SimpleNamespace(
        id=UUID("00000000-0000-0000-0000-000000000100"),
        public_id=UUID("00000000-0000-0000-0000-000000000101"),
        name="Kairo Verification Ops",
    )
    repo = FakeTrustInvitationRepository(organization)
    service = TrustInvitationService(
        session,  # type: ignore[arg-type]
        _settings(),
        repo=repo,  # type: ignore[arg-type]
        organizations=FakeOrganizationService(organization),  # type: ignore[arg-type]
        notifications=FakeNotificationService(),  # type: ignore[arg-type]
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
    raw_token = response.invitation_url.rsplit("/", 1)[-1]

    async def _resolve_active_token(raw_token_value: str):  # noqa: ANN001
        assert raw_token_value == raw_token
        return repo.invitation

    service._resolve_active_token = _resolve_active_token  # type: ignore[assignment]

    lookup = await service.get_public_by_token(raw_token)

    assert lookup.public_id == response.public_id
    assert repo.invitation.delivery_state.value == "queued"
    assert repo.invitation.opened_at is not None
    assert repo.events[-1].event_type == "opened"


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
    assert response.invitation_url.startswith("https://candidate.example.com/trust-invitations/")
    assert "/api/v1/" not in response.invitation_url
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

    async def _resolve_token_for_accept(raw_token_value: str):  # noqa: ANN001
        assert raw_token_value == raw_token
        return repo.invitation

    service._resolve_token_for_accept = _resolve_token_for_accept  # type: ignore[assignment]
    service._people = FailingOrganizationPersonService()  # type: ignore[assignment]

    accepted = await service.accept(raw_token, actor_id, "aman3@test.com")

    assert accepted.status == TrustInvitationStatus.ACCEPTED
    assert session.commits >= 3
    assert session.rollbacks == 1


@pytest.mark.asyncio
async def test_accept_trust_invitation_refetches_events_for_people_sync_after_primary_commit(
) -> None:
    session = FakeSession()
    organization = SimpleNamespace(
        id=UUID("00000000-0000-0000-0000-000000000100"),
        public_id=UUID("00000000-0000-0000-0000-000000000101"),
        name="Kairo Verification Ops",
    )
    repo = FakeTrustInvitationRepository(organization)
    people = AssertLoadedEventsOrganizationPersonService()
    service = TrustInvitationService(
        session,  # type: ignore[arg-type]
        _settings(),
        repo=repo,  # type: ignore[arg-type]
        organizations=FakeOrganizationService(organization),  # type: ignore[arg-type]
        notifications=FakeNotificationService(),  # type: ignore[arg-type]
        people=people,  # type: ignore[arg-type]
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
    repo.invitation.delivery_state = TrustInvitationDeliveryState.DELIVERED
    people.calls = 0

    expired_invitation = ExpiredInvitationState(repo.invitation)

    async def _resolve_token_for_accept(raw_token_value: str):  # noqa: ANN001
        assert raw_token_value == raw_token
        return expired_invitation

    service._resolve_token_for_accept = _resolve_token_for_accept  # type: ignore[assignment]

    accepted = await service.accept(raw_token, actor_id, "aman3@test.com")

    assert accepted.status == TrustInvitationStatus.ACCEPTED
    assert people.calls == 1
    assert any(
        public_id == repo.invitation.public_id and include_events
        for public_id, include_events in repo.get_by_public_id_calls
    )
    assert session.rollbacks == 0
    assert repo.invitation.accepted_at is not None
    assert repo.invitation.delivery_state == TrustInvitationDeliveryState.DELIVERED
    assert [event.event_type for event in repo.events].count("accepted") == 1


@pytest.mark.asyncio
async def test_accept_trust_invitation_retry_is_idempotent_after_primary_acceptance_persists(
) -> None:
    session = FakeSession()
    organization = SimpleNamespace(
        id=UUID("00000000-0000-0000-0000-000000000100"),
        public_id=UUID("00000000-0000-0000-0000-000000000101"),
        name="Kairo Verification Ops",
    )
    repo = FakeTrustInvitationRepository(organization)
    service = TrustInvitationService(
        session,  # type: ignore[arg-type]
        _settings(),
        repo=repo,  # type: ignore[arg-type]
        organizations=FakeOrganizationService(organization),  # type: ignore[arg-type]
        notifications=FakeNotificationService(),  # type: ignore[arg-type]
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
    repo.invitation.delivery_state = TrustInvitationDeliveryState.DELIVERED

    async def _resolve_token_for_accept(raw_token_value: str):  # noqa: ANN001
        assert raw_token_value == raw_token
        return repo.invitation

    service._resolve_token_for_accept = _resolve_token_for_accept  # type: ignore[assignment]
    service._people = FailingOrganizationPersonService()  # type: ignore[assignment]

    first_accept = await service.accept(raw_token, actor_id, "aman3@test.com")

    assert first_accept.status == TrustInvitationStatus.ACCEPTED
    assert [event.event_type for event in repo.events].count("accepted") == 1

    retry_people = AssertLoadedEventsOrganizationPersonService()
    service._people = retry_people  # type: ignore[assignment]

    second_accept = await service.accept(raw_token, actor_id, "aman3@test.com")

    assert second_accept.status == TrustInvitationStatus.ACCEPTED
    assert retry_people.calls == 1
    assert [event.event_type for event in repo.events].count("accepted") == 1
    assert repo.invitation.accepted_at is not None
