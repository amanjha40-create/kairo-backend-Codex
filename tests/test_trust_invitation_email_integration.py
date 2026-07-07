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

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, obj) -> None:  # noqa: ANN001
        return None


class FakeTrustInvitationRepository:
    def __init__(self, organization) -> None:  # noqa: ANN001
        self.organization = organization
        self.invitation = None

    async def create(self, invitation):  # noqa: ANN001
        invitation.public_id = uuid4()
        invitation.created_at = datetime.now(tz=UTC)
        invitation.updated_at = invitation.created_at
        self.invitation = invitation
        return invitation

    async def get_by_public_id(self, invitation_public_id):  # noqa: ANN001
        if self.invitation is None or self.invitation.public_id != invitation_public_id:
            return None
        return SimpleNamespace(
            public_id=self.invitation.public_id,
            organization=self.organization,
            subject_name=self.invitation.subject_name,
            subject_email=self.invitation.subject_email,
            status=self.invitation.status,
            expires_at=self.invitation.expires_at,
            accepted_at=self.invitation.accepted_at,
            cancelled_at=self.invitation.cancelled_at,
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
