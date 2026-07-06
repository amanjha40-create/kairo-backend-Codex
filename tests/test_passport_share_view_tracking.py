"""Route-contract tests for passport share view tracking and analytics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import (
    get_passport_share_view_service,
    get_public_passport_service,
)
from app.exceptions import NotFoundError
from app.main import app
from app.schemas.passport_share import (
    PassportShareAnalyticsResponse,
    PassportSharePermissions,
    PassportShareRecentViewResponse,
)
from app.schemas.public_passport import (
    PublicPassportProfile,
    PublicPassportResponse,
    PublicPassportShareMetadata,
    PublicPassportVault,
)


class FakePublicPassportService:
    def __init__(self, share_id) -> None:  # noqa: ANN001
        self._share_id = share_id

    async def get_by_token(self, token: str) -> PublicPassportResponse:
        if token == "missing":
            raise NotFoundError("Trust Passport not found")
        return PublicPassportResponse(
            profile=PublicPassportProfile(
                full_name="Demo User",
                headline="Engineer",
                location="Bengaluru",
                avatar_url=None,
                profile_slug="demo-user",
            ),
            trust_score=None,
            vault=PublicPassportVault(
                employments=[],
                educations=[],
                internships=[],
                freelance=[],
                gig_platforms=[],
                portfolio=[],
                certifications=[],
                user_documents=[],
            ),
            share=PublicPassportShareMetadata(
                id=self._share_id,
                label="Demo",
                expires_at=datetime.now(tz=UTC) + timedelta(days=7),
                track_views=True,
                permissions=PassportSharePermissions(),
            ),
        )


class FakePassportShareViewService:
    def __init__(self) -> None:
        self.record_calls: list[dict[str, object]] = []
        self.analytics_calls: list[dict[str, object]] = []

    async def record_successful_view(self, **kwargs) -> None:  # noqa: ANN003
        self.record_calls.append(kwargs)

    async def get_analytics(self, *, owner_user_id, share_id) -> PassportShareAnalyticsResponse:  # noqa: ANN001
        self.analytics_calls.append({"owner_user_id": owner_user_id, "share_id": share_id})
        if str(owner_user_id).endswith("ffff"):
            raise NotFoundError("Passport share link not found")
        return PassportShareAnalyticsResponse(
            share_id=share_id,
            total_views=3,
            unique_views=2,
            last_viewed_at=datetime.now(tz=UTC),
            recent_views=[
                PassportShareRecentViewResponse(
                    viewed_at=datetime.now(tz=UTC),
                    user_agent="Mozilla/5.0",
                    referrer="https://example.com",
                    is_unique_view=True,
                )
            ],
        )


def _override_current_user_factory(user_id: UUID):
    async def _override_current_user() -> CurrentUser:
        return CurrentUser(id=user_id, email="owner@example.com", role="user")

    return _override_current_user


@pytest.mark.asyncio
async def test_public_passport_success_records_view() -> None:
    share_id = uuid4()
    fake_view_service = FakePassportShareViewService()
    app.dependency_overrides[get_public_passport_service] = lambda: FakePublicPassportService(share_id)
    app.dependency_overrides[get_passport_share_view_service] = lambda: fake_view_service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/public/passport/demo-token",
            headers={
                "user-agent": "Mozilla/5.0",
                "referer": "https://example.com",
            },
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert len(fake_view_service.record_calls) == 1
    assert fake_view_service.record_calls[0]["share_id"] == share_id
    assert fake_view_service.record_calls[0]["user_agent"] == "Mozilla/5.0"


@pytest.mark.asyncio
async def test_public_passport_failed_lookup_does_not_record_view() -> None:
    share_id = uuid4()
    fake_view_service = FakePassportShareViewService()
    app.dependency_overrides[get_public_passport_service] = lambda: FakePublicPassportService(share_id)
    app.dependency_overrides[get_passport_share_view_service] = lambda: fake_view_service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/public/passport/missing")

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert fake_view_service.record_calls == []


@pytest.mark.asyncio
async def test_passport_share_analytics_requires_owner_scoped_service() -> None:
    share_id = uuid4()
    fake_view_service = FakePassportShareViewService()
    app.dependency_overrides[get_current_user] = _override_current_user_factory(uuid4())
    app.dependency_overrides[get_passport_share_view_service] = lambda: fake_view_service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/passport-shares/{share_id}/analytics")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["share_id"] == str(share_id)
    assert body["total_views"] == 3
    assert len(fake_view_service.analytics_calls) == 1


@pytest.mark.asyncio
async def test_passport_share_analytics_non_owner_fails_closed() -> None:
    share_id = uuid4()
    fake_view_service = FakePassportShareViewService()
    app.dependency_overrides[get_current_user] = _override_current_user_factory(
        UUID("00000000-0000-0000-0000-00000000ffff")
    )
    app.dependency_overrides[get_passport_share_view_service] = lambda: fake_view_service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/passport-shares/{share_id}/analytics")

    app.dependency_overrides.clear()
    assert response.status_code == 404
