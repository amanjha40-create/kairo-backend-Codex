"""Route-contract tests for trust invitation management."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_trust_invitation_service
from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.main import app
from app.schemas.pagination import filter_sort_paginate
from app.services.trust_invitation_service import TrustInvitationService
from app.schemas.trust_invitation import (
    TrustInvitationAcceptResponse,
    TrustInvitationCreateResponse,
    TrustInvitationDetailResponse,
    TrustInvitationPublicLookupResponse,
    TrustInvitationResponse,
    TrustInvitationSummaryResponse,
    TrustInvitationTimelineEventResponse,
)
from app.trust_invitations.enums import (
    TrustInvitationDeliveryMethod,
    TrustInvitationDeliveryState,
    TrustInvitationEventType,
    TrustInvitationStatus,
    TrustInvitationVerificationType,
)


class FakeTrustInvitationService:
    def __init__(self) -> None:
        self._org_public_id = uuid4()
        self._invitation_public_id = uuid4()
        self._now = datetime.now(tz=UTC)

    def _timeline(self) -> list[TrustInvitationTimelineEventResponse]:
        return [
            TrustInvitationTimelineEventResponse(
                id=uuid4(),
                event_type=TrustInvitationEventType.CREATED,
                occurred_at=self._now - timedelta(days=1),
                actor_user_id=uuid4(),
                actor_email="owner@example.com",
                actor_full_name="Owner User",
                metadata={},
            ),
            TrustInvitationTimelineEventResponse(
                id=uuid4(),
                event_type=TrustInvitationEventType.SENT,
                occurred_at=self._now - timedelta(hours=20),
                actor_user_id=uuid4(),
                actor_email="owner@example.com",
                actor_full_name="Owner User",
                metadata={},
            ),
        ]

    def _response(
        self,
        status: TrustInvitationStatus = TrustInvitationStatus.PENDING,
        *,
        delivery_state: TrustInvitationDeliveryState = TrustInvitationDeliveryState.DELIVERED,
    ) -> TrustInvitationResponse:
        accepted_at = self._now if status == TrustInvitationStatus.ACCEPTED else None
        cancelled_at = self._now if status == TrustInvitationStatus.CANCELLED else None
        opened_at = self._now if delivery_state == TrustInvitationDeliveryState.OPENED else None
        sent_at = self._now - timedelta(hours=20) if status != TrustInvitationStatus.DRAFT else None
        return TrustInvitationResponse(
            public_id=self._invitation_public_id,
            organization_public_id=self._org_public_id,
            subject_name="Aman Jha",
            subject_email="aman3@test.com",
            subject_phone="+919999999999",
            purpose="Software Engineer Hiring",
            requested_verification_types=[
                TrustInvitationVerificationType.IDENTITY,
                TrustInvitationVerificationType.EMPLOYMENT,
            ],
            message="Please complete this verification.",
            status=status,
            delivery_method=TrustInvitationDeliveryMethod.EMAIL,
            delivery_state=delivery_state,
            created_by_email="owner@example.com",
            created_by_full_name="Owner User",
            expires_at=self._now + timedelta(days=3),
            sent_at=sent_at,
            opened_at=opened_at,
            accepted_at=accepted_at,
            cancelled_at=cancelled_at,
            related_verification_request_public_id=uuid4() if status == TrustInvitationStatus.ACCEPTED else None,
            created_at=self._now - timedelta(days=1),
            updated_at=self._now,
        )

    async def create(self, actor_user_id, org_public_id, payload):  # noqa: ANN001
        status = TrustInvitationStatus.DRAFT if payload.mode == "draft" else TrustInvitationStatus.PENDING
        delivery_state = (
            TrustInvitationDeliveryState.QUEUED
            if status == TrustInvitationStatus.DRAFT
            else TrustInvitationDeliveryState.DELIVERED
        )
        return TrustInvitationCreateResponse(
            **self._response(status, delivery_state=delivery_state).model_dump(),
            invitation_url="https://candidate.example.com/trust-invitations/v2.token.signature",
        )

    async def get_summary(self, actor_user_id, org_public_id):  # noqa: ANN001
        return TrustInvitationSummaryResponse(
            active_count=4,
            accepted_count=2,
            cancelled_count=1,
            expiring_soon_count=1,
            draft_count=1,
        )

    async def list_for_organization(self, actor_user_id, org_public_id, params=None):  # noqa: ANN001
        if org_public_id == UUID("00000000-0000-0000-0000-00000000ffff"):
            raise NotFoundError("Organization not found")
        items = [
            self._response(),
            self._response(TrustInvitationStatus.ACCEPTED, delivery_state=TrustInvitationDeliveryState.OPENED),
        ]
        if params:
            return filter_sort_paginate(
                items,
                params=params,
                search_fields=("subject_name", "subject_email", "purpose", "status", "delivery_state"),
                allowed_sort_fields=(
                    "created_at",
                    "updated_at",
                    "expires_at",
                    "subject_name",
                    "subject_email",
                    "purpose",
                    "status",
                    "delivery_state",
                    "sent_at",
                    "opened_at",
                ),
                default_sort_by="created_at",
            )
        return items

    async def get_detail(self, actor_user_id, invitation_public_id):  # noqa: ANN001
        if invitation_public_id == UUID("00000000-0000-0000-0000-00000000ffff"):
            raise NotFoundError("Trust invitation not found")
        return TrustInvitationDetailResponse(
            **self._response().model_dump(),
            invitation_url="https://candidate.example.com/trust-invitations/v2.token.signature",
            timeline=self._timeline(),
        )

    async def send(self, actor_user_id, invitation_public_id):  # noqa: ANN001
        return TrustInvitationDetailResponse(
            **self._response().model_dump(),
            invitation_url="https://candidate.example.com/trust-invitations/v2.token.signature",
            timeline=self._timeline(),
        )

    async def resend(self, actor_user_id, invitation_public_id):  # noqa: ANN001
        if invitation_public_id == UUID("00000000-0000-0000-0000-00000000dddd"):
            raise ConflictError("Expired trust invitations are no longer actionable")
        return TrustInvitationDetailResponse(
            **self._response().model_dump(),
            invitation_url="https://candidate.example.com/trust-invitations/v2.token.signature",
            timeline=self._timeline(),
        )

    async def delete(self, actor_user_id, invitation_public_id):  # noqa: ANN001
        if invitation_public_id == UUID("00000000-0000-0000-0000-00000000ffff"):
            raise NotFoundError("Trust invitation not found")
        return None

    async def get_public_by_token(self, raw_token: str) -> TrustInvitationPublicLookupResponse:
        if raw_token in {"unknown-token", "accepted-token", "expired-token", "cancelled-token"}:
            raise NotFoundError("Trust invitation not found")
        return TrustInvitationPublicLookupResponse(
            public_id=self._invitation_public_id,
            organization_name="Kairo Verification Ops",
            subject_name="Aman Jha",
            purpose="Software Engineer Hiring",
            requested_verification_types=[
                TrustInvitationVerificationType.IDENTITY,
                TrustInvitationVerificationType.EMPLOYMENT,
            ],
            expires_at=self._now + timedelta(days=3),
            status=TrustInvitationStatus.PENDING,
        )

    async def accept(self, raw_token: str, actor_user_id, actor_email: str):  # noqa: ANN001
        if raw_token in {"unknown-token", "accepted-token", "expired-token", "cancelled-token"}:
            raise NotFoundError("Trust invitation not found")
        if actor_email != "aman3@test.com":
            raise ForbiddenError("This trust invitation is not assigned to the authenticated account")
        return TrustInvitationAcceptResponse(
            public_id=self._invitation_public_id,
            organization_public_id=self._org_public_id,
            status=TrustInvitationStatus.ACCEPTED,
            accepted_at=self._now,
        )

    async def cancel(self, actor_user_id, invitation_public_id: UUID):  # noqa: ANN001
        if invitation_public_id == UUID("00000000-0000-0000-0000-00000000ffff"):
            raise NotFoundError("Trust invitation not found")
        if invitation_public_id == UUID("00000000-0000-0000-0000-00000000eeee"):
            raise ForbiddenError("Only organization owners or admins can cancel trust invitations")
        return self._response(TrustInvitationStatus.CANCELLED)


def _override_current_user_factory(email: str):
    async def _override_current_user() -> CurrentUser:
        return CurrentUser(id=uuid4(), email=email, role="user")

    return _override_current_user


@pytest.mark.asyncio
async def test_create_trust_invitation_returns_url_once() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory("owner@example.com")
    app.dependency_overrides[get_trust_invitation_service] = lambda: FakeTrustInvitationService()

    transport = ASGITransport(app=app)
    org_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/organizations/{org_public_id}/trust-invitations",
            json={
                "subject_name": "Aman Jha",
                "subject_email": "aman3@test.com",
                "purpose": "Software Engineer Hiring",
                "requested_verification_types": ["identity", "employment"],
                "delivery_method": "email",
                "mode": "send",
                "expires_at": (datetime.now(tz=UTC) + timedelta(days=3)).isoformat(),
            },
        )

    app.dependency_overrides.clear()
    assert response.status_code == 201
    body = response.json()
    assert body["invitation_url"] == "https://candidate.example.com/trust-invitations/v2.token.signature"
    assert body["purpose"] == "Software Engineer Hiring"


@pytest.mark.asyncio
async def test_list_trust_invitations_omits_url() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory("member@example.com")
    app.dependency_overrides[get_trust_invitation_service] = lambda: FakeTrustInvitationService()

    transport = ASGITransport(app=app)
    org_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/organizations/{org_public_id}/trust-invitations")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert "invitation_url" not in body[0]
    assert body[0]["delivery_state"] == "delivered"


@pytest.mark.asyncio
async def test_list_trust_invitations_supports_paginated_mode() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory("member@example.com")
    app.dependency_overrides[get_trust_invitation_service] = lambda: FakeTrustInvitationService()

    transport = ASGITransport(app=app)
    org_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/organizations/{org_public_id}/trust-invitations?paginate=true&page=1&page_size=1"
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 1


@pytest.mark.asyncio
async def test_summary_endpoint_returns_workspace_counts() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory("member@example.com")
    app.dependency_overrides[get_trust_invitation_service] = lambda: FakeTrustInvitationService()

    transport = ASGITransport(app=app)
    org_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/organizations/{org_public_id}/trust-invitations/summary")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["active_count"] == 4


@pytest.mark.asyncio
async def test_authenticated_detail_returns_timeline_and_url() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory("member@example.com")
    app.dependency_overrides[get_trust_invitation_service] = lambda: FakeTrustInvitationService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/trust-invitations/by-id/{uuid4()}")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["invitation_url"] == "https://candidate.example.com/trust-invitations/v2.token.signature"
    assert body["timeline"][0]["event_type"] == "created"


@pytest.mark.asyncio
async def test_send_endpoint_returns_detail_payload() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory("member@example.com")
    app.dependency_overrides[get_trust_invitation_service] = lambda: FakeTrustInvitationService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/v1/trust-invitations/{uuid4()}/send")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_resend_endpoint_maps_conflict() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory("member@example.com")
    app.dependency_overrides[get_trust_invitation_service] = lambda: FakeTrustInvitationService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/trust-invitations/00000000-0000-0000-0000-00000000dddd/resend")

    app.dependency_overrides.clear()
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


@pytest.mark.asyncio
async def test_delete_draft_returns_no_content() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory("member@example.com")
    app.dependency_overrides[get_trust_invitation_service] = lambda: FakeTrustInvitationService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.delete(f"/api/v1/trust-invitations/{uuid4()}")

    app.dependency_overrides.clear()
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_non_org_user_cannot_list_trust_invitations() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory("outsider@example.com")
    app.dependency_overrides[get_trust_invitation_service] = lambda: FakeTrustInvitationService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/organizations/00000000-0000-0000-0000-00000000ffff/trust-invitations")

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_public_lookup_returns_sanitized_payload() -> None:
    app.dependency_overrides[get_trust_invitation_service] = lambda: FakeTrustInvitationService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/trust-invitations/valid-token")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["organization_name"] == "Kairo Verification Ops"
    assert "subject_email" not in body
    assert body["requested_verification_types"] == ["identity", "employment"]


@pytest.mark.asyncio
async def test_public_lookup_fails_closed_for_invalid_states() -> None:
    app.dependency_overrides[get_trust_invitation_service] = lambda: FakeTrustInvitationService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/trust-invitations/accepted-token")

    app.dependency_overrides.clear()
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_accept_trust_invitation_requires_matching_email() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory("wrong@example.com")
    app.dependency_overrides[get_trust_invitation_service] = lambda: FakeTrustInvitationService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/trust-invitations/valid-token/accept")

    app.dependency_overrides.clear()
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


@pytest.mark.asyncio
async def test_accept_trust_invitation_succeeds_for_matching_email() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory("aman3@test.com")
    app.dependency_overrides[get_trust_invitation_service] = lambda: FakeTrustInvitationService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/trust-invitations/valid-token/accept")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"


@pytest.mark.asyncio
async def test_owner_or_admin_can_cancel_invitation() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory("owner@example.com")
    app.dependency_overrides[get_trust_invitation_service] = lambda: FakeTrustInvitationService()

    transport = ASGITransport(app=app)
    invitation_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/v1/trust-invitations/{invitation_public_id}/cancel")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_member_cannot_cancel_invitation() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory("member@example.com")
    app.dependency_overrides[get_trust_invitation_service] = lambda: FakeTrustInvitationService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/trust-invitations/00000000-0000-0000-0000-00000000eeee/cancel")

    app.dependency_overrides.clear()
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


@pytest.mark.asyncio
async def test_person_sync_failure_does_not_reaccess_expired_invitation() -> None:
    service = TrustInvitationService.__new__(TrustInvitationService)
    service._people = SimpleNamespace(resolve_for_trust_invitation=AsyncMock(side_effect=RuntimeError("sync failed")))
    service._session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    invitation = SimpleNamespace(public_id=uuid4())

    await service._sync_person_link_best_effort(invitation, actor_user_id=uuid4())  # type: ignore[attr-defined]

    service._session.rollback.assert_awaited_once()  # type: ignore[attr-defined]
