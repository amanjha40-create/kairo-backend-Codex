"""Route-contract tests for authenticated passport share management."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_passport_share_service
from app.main import app
from app.schemas.passport_share import PassportShareCreateResponse, PassportSharePermissions, PassportShareResponse


class FakePassportShareService:
    def __init__(self) -> None:
        self._share_id = uuid4()
        self._now = datetime.now(tz=UTC)

    def _base_response(self) -> PassportShareResponse:
        return PassportShareResponse(
            id=self._share_id,
            label="Investor Demo",
            permissions=PassportSharePermissions(),
            track_views=True,
            expires_at=self._now + timedelta(days=7),
            revoked_at=None,
            last_viewed_at=None,
            created_at=self._now,
            updated_at=self._now,
            state="active",
        )

    async def create(self, owner_user_id, payload) -> PassportShareCreateResponse:  # noqa: ANN001
        base = self._base_response()
        return PassportShareCreateResponse(**base.model_dump(), share_url="https://app.example.com/passport/raw-token")

    async def list_for_user(self, owner_user_id, *, offset=0, limit=20):  # noqa: ANN001
        return [self._base_response()], 1

    async def get_owned(self, owner_user_id, share_id):  # noqa: ANN001
        return self._base_response()

    async def update(self, owner_user_id, share_id, payload):  # noqa: ANN001
        return self._base_response()

    async def revoke(self, owner_user_id, share_id):  # noqa: ANN001
        response = self._base_response()
        return response.model_copy(update={"state": "revoked", "revoked_at": self._now})


async def _override_current_user() -> CurrentUser:
    return CurrentUser(id=uuid4(), email="investor@example.com", role="user")


@pytest.mark.asyncio
async def test_create_passport_share_returns_share_url_once() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_passport_share_service] = lambda: FakePassportShareService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/passport-shares",
            json={"label": "Investor Demo"},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 201
    body = response.json()
    assert body["share_url"] == "https://app.example.com/passport/raw-token"
    assert body["state"] == "active"


@pytest.mark.asyncio
async def test_list_passport_shares_omits_share_url() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_passport_share_service] = lambda: FakePassportShareService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/passport-shares")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert body["total_pages"] == 1
    assert "share_url" not in body["items"][0]


@pytest.mark.asyncio
async def test_revoke_passport_share_returns_revoked_state() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_passport_share_service] = lambda: FakePassportShareService()

    transport = ASGITransport(app=app)
    share_id = str(uuid4())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/v1/passport-shares/{share_id}/revoke")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "revoked"
