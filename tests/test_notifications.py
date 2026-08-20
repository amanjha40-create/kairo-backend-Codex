"""Route-contract tests for internal notification center APIs."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.services import get_notification_service
from app.api.dependencies.verification_admin import (
    require_admin_portal,
    require_reviewer,
    require_view_cases,
)
from app.main import app
from app.schemas.notification import (
    AdminNotificationInboxResponse,
    NotificationDeliveryResponse,
    NotificationDetailResponse,
    NotificationEventResponse,
    NotificationResponse,
    NotificationStatisticsResponse,
    NotificationUnreadCountResponse,
)
from app.schemas.pagination import ListQueryParams, Page, PageParams


class FakeNotificationService:
    def __init__(self) -> None:
        self.notification_public_id = UUID("00000000-0000-0000-0000-000000000701")
        self.delivery_public_id = UUID("00000000-0000-0000-0000-000000000702")
        self.event_public_id = UUID("00000000-0000-0000-0000-000000000703")
        self.now = datetime.now(tz=UTC)
        self.mark_read_calls: list[tuple[UUID, UUID]] = []
        self.mark_all_read_calls: list[UUID] = []

    def _notification(self) -> NotificationResponse:
        return NotificationResponse(
            public_id=self.notification_public_id,
            notification_type="transactional",
            event_type="trust_invitation_created",
            priority="normal",
            status="sent",
            recipient_user_id=None,
            recipient_email="aman3@test.com",
            recipient_phone=None,
            channel="email",
            template_key="trust_invitation",
            template_version="v1",
            payload={"subject_name": "Aman Jha"},
            metadata={"organization_public_id": str(uuid4())},
            scheduled_at=None,
            sent_at=self.now,
            failed_at=None,
            created_at=self.now,
            updated_at=self.now,
        )

    def _delivery(self) -> NotificationDeliveryResponse:
        return NotificationDeliveryResponse(
            public_id=self.delivery_public_id,
            channel="email",
            status="sent",
            provider="console",
            provider_message_id="msg_123",
            email_delivery_log_public_id=uuid4(),
            attempt_count=1,
            error_code=None,
            error_message=None,
            metadata={},
            dispatched_at=self.now,
            delivered_at=self.now,
            failed_at=None,
            created_at=self.now,
            updated_at=self.now,
        )

    def _event(self) -> NotificationEventResponse:
        return NotificationEventResponse(
            public_id=self.event_public_id,
            actor_user_id=uuid4(),
            event_type="notification_dispatch_completed",
            status="sent",
            metadata={},
            created_at=self.now,
            updated_at=self.now,
        )

    async def list_notifications(self, params: ListQueryParams) -> Page[NotificationResponse]:
        return Page[NotificationResponse].create(
            items=[self._notification()],
            total=1,
            params=PageParams(page=params.page, page_size=params.page_size),
        )

    async def get_detail(
        self,
        notification_public_id: UUID,
    ) -> NotificationDetailResponse:  # noqa: ARG002
        return NotificationDetailResponse(
            **self._notification().model_dump(),
            deliveries=[self._delivery()],
            history=[self._event()],
        )

    async def resend(
        self,
        notification_public_id: UUID,
        *,
        actor_user_id=None,
    ) -> NotificationDetailResponse:  # noqa: ARG002, ANN001
        return await self.get_detail(notification_public_id)

    async def list_history(
        self,
        notification_public_id: UUID,
        params: ListQueryParams,
    ) -> Page[NotificationEventResponse]:  # noqa: ARG002
        return Page[NotificationEventResponse].create(
            items=[self._event()],
            total=1,
            params=PageParams(page=params.page, page_size=params.page_size),
        )

    async def list_deliveries(
        self,
        notification_public_id: UUID,
        params: ListQueryParams,
    ) -> Page[NotificationDeliveryResponse]:  # noqa: ARG002
        return Page[NotificationDeliveryResponse].create(
            items=[self._delivery()],
            total=1,
            params=PageParams(page=params.page, page_size=params.page_size),
        )

    async def get_statistics(self) -> NotificationStatisticsResponse:
        return NotificationStatisticsResponse(
            total_notifications=4,
            by_status={"sent": 3, "failed": 1},
            by_channel={"email": 4},
        )

    async def list_admin_inbox(
        self,
        user_id: UUID,  # noqa: ARG002
        params: ListQueryParams,
    ) -> Page[AdminNotificationInboxResponse]:
        return Page[AdminNotificationInboxResponse].create(
            items=[
                AdminNotificationInboxResponse(
                    public_id=self.notification_public_id,
                    category="verification",
                    event_type="admin_verification_review_required",
                    title="Verification needs admin review",
                    body="A verification request is waiting for pre-dispatch admin review.",
                    metadata={"verification_request_public_id": str(uuid4())},
                    read_at=None,
                    created_at=self.now,
                    status="sent",
                    channel="in_app",
                    priority="normal",
                    updated_at=self.now,
                )
            ],
            total=1,
            params=PageParams(page=params.page, page_size=params.page_size),
        )

    async def unread_count(
        self,
        user_id: UUID,  # noqa: ARG002
    ) -> NotificationUnreadCountResponse:
        return NotificationUnreadCountResponse(unread_count=1)

    async def mark_user_read(self, user_id: UUID, notification_public_id: UUID) -> None:
        self.mark_read_calls.append((user_id, notification_public_id))

    async def mark_user_read_all(self, user_id: UUID) -> int:
        self.mark_all_read_calls.append(user_id)
        return 1


async def _allow_admin():  # noqa: D401
    return SimpleNamespace(id=uuid4())


@pytest.mark.asyncio
async def test_list_notifications_returns_page() -> None:
    app.dependency_overrides[get_notification_service] = lambda: FakeNotificationService()
    app.dependency_overrides[require_view_cases] = _allow_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/admin/notifications")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["event_type"] == "trust_invitation_created"


@pytest.mark.asyncio
async def test_get_notification_detail_returns_delivery_and_history() -> None:
    app.dependency_overrides[get_notification_service] = lambda: FakeNotificationService()
    app.dependency_overrides[require_view_cases] = _allow_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/admin/notifications/00000000-0000-0000-0000-000000000701"
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert len(response.json()["deliveries"]) == 1
    assert len(response.json()["history"]) == 1


@pytest.mark.asyncio
async def test_resend_notification_uses_reviewer_permission() -> None:
    app.dependency_overrides[get_notification_service] = lambda: FakeNotificationService()
    app.dependency_overrides[require_reviewer] = _allow_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/admin/notifications/00000000-0000-0000-0000-000000000701/resend"
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["public_id"] == "00000000-0000-0000-0000-000000000701"


@pytest.mark.asyncio
async def test_notification_statistics_returns_summary() -> None:
    app.dependency_overrides[get_notification_service] = lambda: FakeNotificationService()
    app.dependency_overrides[require_view_cases] = _allow_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/admin/notifications/statistics/summary")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["total_notifications"] == 4


@pytest.mark.asyncio
async def test_notification_history_and_deliveries_routes_return_pages() -> None:
    app.dependency_overrides[get_notification_service] = lambda: FakeNotificationService()
    app.dependency_overrides[require_view_cases] = _allow_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        history = await client.get(
            "/api/v1/admin/notifications/00000000-0000-0000-0000-000000000701/history"
        )
        deliveries = await client.get(
            "/api/v1/admin/notifications/00000000-0000-0000-0000-000000000701/deliveries"
        )

    app.dependency_overrides.clear()
    assert history.status_code == 200
    assert history.json()["total"] == 1
    assert deliveries.status_code == 200
    assert deliveries.json()["items"][0]["channel"] == "email"


@pytest.mark.asyncio
async def test_admin_notification_inbox_returns_current_user_items() -> None:
    service = FakeNotificationService()
    app.dependency_overrides[get_notification_service] = lambda: service
    app.dependency_overrides[require_admin_portal] = _allow_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/admin/notifications/inbox")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["event_type"] == "admin_verification_review_required"
    assert body["items"][0]["channel"] == "in_app"
    assert body["items"][0]["priority"] == "normal"


@pytest.mark.asyncio
async def test_admin_notification_unread_count_returns_backend_truth() -> None:
    service = FakeNotificationService()
    app.dependency_overrides[get_notification_service] = lambda: service
    app.dependency_overrides[require_admin_portal] = _allow_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/admin/notifications/unread-count")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"unread_count": 1}


@pytest.mark.asyncio
async def test_admin_notification_mark_read_uses_current_user_scope() -> None:
    service = FakeNotificationService()
    app.dependency_overrides[get_notification_service] = lambda: service
    app.dependency_overrides[require_admin_portal] = _allow_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/admin/notifications/00000000-0000-0000-0000-000000000701/read"
        )

    app.dependency_overrides.clear()
    assert response.status_code == 204
    assert len(service.mark_read_calls) == 1
    assert service.mark_read_calls[0][1] == UUID(
        "00000000-0000-0000-0000-000000000701"
    )


@pytest.mark.asyncio
async def test_admin_notification_mark_all_read_marks_current_user_inbox() -> None:
    service = FakeNotificationService()
    app.dependency_overrides[get_notification_service] = lambda: service
    app.dependency_overrides[require_admin_portal] = _allow_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/admin/notifications/read-all")

    app.dependency_overrides.clear()
    assert response.status_code == 204
    assert len(service.mark_all_read_calls) == 1
