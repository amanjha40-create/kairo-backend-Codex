"""Route and service tests for the admin communications center."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.services import get_admin_communication_service
from app.api.dependencies.verification_admin import require_reviewer, require_view_cases
from app.main import app
from app.schemas.admin_communication import (
    AdminCommunicationFullDetailResponse,
    AdminCommunicationListItemResponse,
    AdminCommunicationNotificationSummaryResponse,
    AdminCommunicationRelatedObjectResponse,
    AdminCommunicationResendResponse,
    AdminCommunicationSummaryResponse,
    AdminCommunicationTimelineEventResponse,
)
from app.schemas.pagination import Page, PageParams
from app.services.admin_communication_service import AdminCommunicationService


class FakeAdminCommunicationService:
    def __init__(self) -> None:
        self.communication_public_id = UUID("00000000-0000-0000-0000-000000009901")
        self.now = datetime.now(tz=UTC)

    def _item(self) -> AdminCommunicationListItemResponse:
        return AdminCommunicationListItemResponse(
            public_id=self.communication_public_id,
            channel="email",
            event_type="password_reset_requested",
            template_key="password_reset",
            template_version="v1",
            status="failed",
            recipient_masked="am***n@example.com",
            provider="brevo",
            provider_message_id="brevo-msg-1234567890",
            provider_message_id_display="brevo-ms...567890",
            subject="Reset your password",
            failure_reason="provider_timeout",
            queued_at=self.now,
            sent_at=None,
            failed_at=self.now,
            created_at=self.now,
            updated_at=self.now,
            retryable=False,
            retry_policy="requires_new_workflow_action",
            related_object=AdminCommunicationRelatedObjectResponse(
                kind="verification_request",
                public_id="11111111-1111-1111-1111-111111111111",
                label="Verification request",
            ),
            notification=AdminCommunicationNotificationSummaryResponse(
                public_id=UUID("00000000-0000-0000-0000-000000009902"),
                event_type="password_reset_requested",
                category="security",
                title="Password reset requested",
                status="failed",
                read_at=None,
                created_at=self.now,
            ),
        )

    async def list_communications(self, params) -> Page[AdminCommunicationListItemResponse]:  # noqa: ANN001
        return Page[AdminCommunicationListItemResponse].create(
            items=[self._item()],
            total=1,
            params=PageParams(page=params.page, page_size=params.page_size),
        )

    async def get_detail(
        self,
        communication_public_id: UUID,  # noqa: ARG002
    ) -> AdminCommunicationFullDetailResponse:
        return AdminCommunicationFullDetailResponse(
            **self._item().model_dump(),
            payload_summary={
                "ttl_minutes": 15,
                "verification_request_public_id": "11111111-1111-1111-1111-111111111111",
            },
            delivery_timeline=[
                AdminCommunicationTimelineEventResponse(
                    kind="queued",
                    occurred_at=self.now,
                    detail="Communication queued for provider dispatch.",
                    status="queued",
                ),
                AdminCommunicationTimelineEventResponse(
                    kind="failed",
                    occurred_at=self.now,
                    detail="provider_timeout",
                    status="failed",
                ),
            ],
            notification_public_id=UUID("00000000-0000-0000-0000-000000009902"),
            delivery_attempts=[],
            audit_history=[],
        )

    async def get_summary(self) -> AdminCommunicationSummaryResponse:
        return AdminCommunicationSummaryResponse(
            total=5,
            queued=1,
            sent=3,
            failed=1,
            recent_failures_24h=1,
            resendable_failed=1,
        )

    async def resend(
        self,
        communication_public_id: UUID,  # noqa: ARG002
        *,
        actor_user_id: UUID,  # noqa: ARG002
    ) -> AdminCommunicationResendResponse:
        return AdminCommunicationResendResponse(
            communication=await self.get_detail(self.communication_public_id)
        )


async def _allow_admin():  # noqa: D401
    return SimpleNamespace(id=uuid4())


@pytest.mark.asyncio
async def test_admin_communications_list_route_returns_page() -> None:
    app.dependency_overrides[get_admin_communication_service] = (
        lambda: FakeAdminCommunicationService()
    )
    app.dependency_overrides[require_view_cases] = _allow_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/admin/communications?status=failed&template_key=password_reset"
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["provider"] == "brevo"
    assert body["items"][0]["recipient_masked"] == "am***n@example.com"


@pytest.mark.asyncio
async def test_admin_communications_detail_route_returns_safe_payload_summary() -> None:
    app.dependency_overrides[get_admin_communication_service] = (
        lambda: FakeAdminCommunicationService()
    )
    app.dependency_overrides[require_view_cases] = _allow_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/admin/communications/00000000-0000-0000-0000-000000009901"
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["payload_summary"] == {
        "ttl_minutes": 15,
        "verification_request_public_id": "11111111-1111-1111-1111-111111111111",
    }
    assert len(body["delivery_timeline"]) == 2


@pytest.mark.asyncio
async def test_admin_communications_summary_route_returns_operational_counts() -> None:
    app.dependency_overrides[get_admin_communication_service] = (
        lambda: FakeAdminCommunicationService()
    )
    app.dependency_overrides[require_view_cases] = _allow_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/admin/communications/statistics/summary")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {
        "total": 5,
        "queued": 1,
        "sent": 3,
        "failed": 1,
        "recent_failures_24h": 1,
        "resendable_failed": 1,
    }


@pytest.mark.asyncio
async def test_admin_communications_resend_route_uses_reviewer_permission() -> None:
    app.dependency_overrides[get_admin_communication_service] = (
        lambda: FakeAdminCommunicationService()
    )
    app.dependency_overrides[require_reviewer] = _allow_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/admin/communications/00000000-0000-0000-0000-000000009901/resend"
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["communication"]["public_id"] == "00000000-0000-0000-0000-000000009901"


def test_admin_communication_service_payload_summary_excludes_sensitive_fields() -> None:
    service = AdminCommunicationService(None)  # type: ignore[arg-type]
    notification = SimpleNamespace(
        metadata_payload={
            "verification_request_public_id": "11111111-1111-1111-1111-111111111111",
            "organization_public_id": "22222222-2222-2222-2222-222222222222",
            "reset_token": "hidden",
        }
    )

    summary = service._payload_summary(  # noqa: SLF001
        {
            "ttl_minutes": 15,
            "reset_token": "secret",
            "api_key": "secret-key",
            "verification_request_public_id": "33333333-3333-3333-3333-333333333333",
        },
        notification,
    )

    assert summary == {
        "ttl_minutes": 15,
        "verification_request_public_id": "11111111-1111-1111-1111-111111111111",
        "organization_public_id": "22222222-2222-2222-2222-222222222222",
    }
    assert "reset_token" not in summary
    assert "api_key" not in summary


def test_admin_communication_service_related_object_prefers_notification_metadata() -> None:
    service = AdminCommunicationService(None)  # type: ignore[arg-type]
    log = SimpleNamespace(
        payload={"employer_verification_request_public_id": "44444444-4444-4444-4444-444444444444"}
    )
    notification = SimpleNamespace(
        metadata_payload={
            "verification_request_public_id": "11111111-1111-1111-1111-111111111111"
        }
    )

    related = service._related_object(log, notification)  # noqa: SLF001

    assert related is not None
    assert related.kind == "verification_request"
    assert related.public_id == "11111111-1111-1111-1111-111111111111"
