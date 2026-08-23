"""Security and lifecycle regression coverage for Admin access invitations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.auth.tokens import hash_refresh_token
from app.config import Settings
from app.exceptions import ConflictError, NotFoundError
from app.models import AdminAccessInvitation
from app.services.admin_settings_service import AdminSettingsService

RAW_TOKEN = "single-use-admin-invitation-token-1234567890"


class FakeSession:
    def __init__(self, invitation: AdminAccessInvitation | None) -> None:
        self.invitation = invitation

    async def scalar(self, *_args, **_kwargs):
        return self.invitation


def make_settings(
    admin_portal_base_url: str = "https://admin-staging.example.com/",
) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://kairo:kairo@localhost:5432/kairo",
        jwt_secret_key="test-jwt-secret-key-32-chars-minimum!!",
        admin_portal_base_url=admin_portal_base_url,
    )


def make_invitation(*, status: str = "pending", expired: bool = False) -> AdminAccessInvitation:
    now = datetime.now(tz=UTC)
    return AdminAccessInvitation(
        invited_by_user_id=uuid4(),
        invitee_email="invited-admin@example.com",
        role="support",
        status=status,
        token_hash=hash_refresh_token(RAW_TOKEN),
        expires_at=now - timedelta(minutes=1) if expired else now + timedelta(days=1),
        sent_at=now,
    )


def make_service(
    monkeypatch: pytest.MonkeyPatch,
    invitation: AdminAccessInvitation | None,
    admin_portal_base_url: str = "https://admin-staging.example.com/",
) -> AdminSettingsService:
    monkeypatch.setattr(
        "app.services.admin_settings_service.get_email_sender",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    return AdminSettingsService(
        FakeSession(invitation),  # type: ignore[arg-type]
        make_settings(admin_portal_base_url),
    )


def test_admin_invitation_url_uses_configured_frontend_and_fragment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = make_service(monkeypatch, None)

    invitation_url = service._admin_invitation_url(RAW_TOKEN)  # noqa: SLF001

    assert invitation_url == (
        "https://admin-staging.example.com/admin/accept-invitation#"
        "token=single-use-admin-invitation-token-1234567890"
    )
    assert "?token=" not in invitation_url


def test_admin_invitation_production_url_targets_canonical_admin_domain_without_sending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = make_service(monkeypatch, None, "https://admin.kairoid.com")

    invitation_url = service._admin_invitation_url(RAW_TOKEN)  # noqa: SLF001

    assert invitation_url == (
        "https://admin.kairoid.com/admin/accept-invitation#"
        "token=single-use-admin-invitation-token-1234567890"
    )
    assert "staging" not in invitation_url
    assert "amplifyapp.com" not in invitation_url


def test_admin_invitation_persists_only_token_hash() -> None:
    invitation = make_invitation()

    assert invitation.token_hash == hash_refresh_token(RAW_TOKEN)
    assert invitation.token_hash != RAW_TOKEN
    assert "token" not in invitation.__dict__


@pytest.mark.asyncio
async def test_valid_admin_invitation_token_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    invitation = make_invitation()
    service = make_service(monkeypatch, invitation)

    resolved = await service._resolve_invitation_token(RAW_TOKEN)  # noqa: SLF001

    assert resolved is invitation
    assert resolved.status == "pending"


@pytest.mark.asyncio
async def test_invalid_admin_invitation_token_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    service = make_service(monkeypatch, None)

    with pytest.raises(NotFoundError, match="Admin invitation not found"):
        await service._resolve_invitation_token(RAW_TOKEN)  # noqa: SLF001


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["revoked", "accepted"])
async def test_non_actionable_admin_invitation_fails(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    service = make_service(monkeypatch, make_invitation(status=status))

    with pytest.raises(ConflictError, match="no longer actionable"):
        await service._resolve_invitation_token(RAW_TOKEN)  # noqa: SLF001


@pytest.mark.asyncio
async def test_expired_admin_invitation_fails_and_is_marked_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invitation = make_invitation(expired=True)
    service = make_service(monkeypatch, invitation)

    with pytest.raises(ConflictError, match="no longer actionable"):
        await service._resolve_invitation_token(RAW_TOKEN)  # noqa: SLF001

    assert invitation.status == "expired"
