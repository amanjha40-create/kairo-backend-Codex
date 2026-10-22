"""Passport recipient links use the portal without moving unrelated API links."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

from app.schemas.passport_share import PassportShareCreateRequest
from app.services.employer_verification_service import EmployerVerificationService
from app.services.passport_share_service import PassportShareService
from app.services.passport_sharing_policy import resolve_policy, stored_v2


@pytest.mark.parametrize("portal", ["https://app.kairoid.com", "https://candidate-staging.example.test/"])
@pytest.mark.asyncio
async def test_creation_uses_portal_and_preserves_token_and_policy(portal, monkeypatch):
    settings = SimpleNamespace(
        candidate_portal_base_url=portal,
        app_public_base_url="https://api.kairoid.com",
        api_v1_prefix="/api/v1",
    )
    session = AsyncMock()
    service = PassportShareService(session, settings)
    service._repo = AsyncMock()
    token = "synthetic_opaque-token_with-URLsafe_Characters"
    generator = []

    def generate(size):
        generator.append(size)
        return token

    monkeypatch.setattr("app.services.passport_share_service.secrets.token_urlsafe", generate)
    now = datetime.now(UTC)

    async def refresh(link):
        link.id = uuid4()
        link.created_at = now
        link.updated_at = now

    session.refresh.side_effect = refresh
    payload = PassportShareCreateRequest(
        label="Synthetic URL contract", expires_at=now + timedelta(days=1)
    )
    result = await service.create(uuid4(), payload)
    assert result.share_url == f"{portal.rstrip('/')}/passport/{token}"
    assert urlsplit(result.share_url).hostname != "api.kairoid.com"
    assert result.expires_at == payload.expires_at
    assert result.revoked_at is None and result.state == "active"
    assert result.permissions.model_dump() == resolve_policy(
        stored_v2(payload.sharing_mode, payload.permissions)
    ).permissions.model_dump()
    assert generator == [32]
    stored = service._repo.create.call_args.args[0]
    assert stored.token_hash == service._hash_token(token)

    unrelated = object.__new__(EmployerVerificationService)
    unrelated._settings = settings
    assert unrelated._public_link(token, "approve") == (
        f"https://api.kairoid.com/api/v1/public/employer-verification/{token}/approve"
    )
    assert settings.app_public_base_url == "https://api.kairoid.com"


def test_legacy_unconfigured_portal_retains_existing_local_contract():
    service = PassportShareService(
        AsyncMock(),
        SimpleNamespace(candidate_portal_base_url=None, app_public_base_url="http://localhost:8000/"),
    )
    assert service._build_share_url("synthetic-token") == "http://localhost:8000/passport/synthetic-token"
