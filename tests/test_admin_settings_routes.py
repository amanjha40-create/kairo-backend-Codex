"""Route-contract tests for Admin settings and administration APIs."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.services import get_admin_settings_service
from app.auth.deps import CurrentUser, get_current_user
from app.config import get_settings
from app.exceptions import ConflictError
from app.main import app
from app.models.user import User
from app.schemas.admin_settings import (
    AdminAccessAuditEventResponse,
    AdminAccessInvitationResponse,
    AdminAdministratorActionCapabilities,
    AdminAdministratorDetailResponse,
    AdminAdministratorListItemResponse,
    AdminRoleResponse,
    AdminSettingsMeResponse,
    AdminSettingsNotificationCategoryResponse,
    AdminSettingsNotificationPreferencesResponse,
    AdminSettingsSessionResponse,
)
from app.schemas.auth import TokenResponse
from app.schemas.pagination import Page, PageParams
from app.services.admin_settings_service import AdminSettingsService

NOW = datetime(2026, 8, 23, 10, 30, tzinfo=UTC)
ADMIN_ID = UUID("11111111-1111-1111-1111-111111111111")
OTHER_ADMIN_ID = UUID("22222222-2222-2222-2222-222222222222")
INVITATION_ID = UUID("33333333-3333-3333-3333-333333333333")
SESSION_ID = UUID("44444444-4444-4444-4444-444444444444")
AUDIT_EVENT_ID = UUID("55555555-5555-5555-5555-555555555555")


def _session_item(*, current: bool = False) -> AdminSettingsSessionResponse:
    return AdminSettingsSessionResponse(
        id=SESSION_ID,
        created_at=NOW,
        expires_at=NOW,
        last_active_at=NOW,
        current=current,
        status="active",
        revoked_at=None,
    )


def _me_response() -> AdminSettingsMeResponse:
    return AdminSettingsMeResponse(
        id=ADMIN_ID,
        full_name="Ada Admin",
        email="admin@example.com",
        role_key="admin",
        role_label="Admin",
        account_status="active",
        permissions=["admin_settings_read", "admin_access_read", "access_admin_portal"],
        email_verified=True,
        joined_at=NOW,
        last_sign_in_at=NOW,
        last_activity_at=NOW,
    )


def _notifications_response() -> AdminSettingsNotificationPreferencesResponse:
    return AdminSettingsNotificationPreferencesResponse(
        categories=[
            AdminSettingsNotificationCategoryResponse(
                key="verification_operations",
                label="Verification operations",
                description="Queue and review notifications.",
                enabled=True,
                required=False,
                event_types=["verification_queue"],
            ),
            AdminSettingsNotificationCategoryResponse(
                key="account_security",
                label="Account security",
                description="Mandatory security notices.",
                enabled=True,
                required=True,
                event_types=["account_security"],
            ),
        ]
    )


def _audit_event() -> AdminAccessAuditEventResponse:
    return AdminAccessAuditEventResponse(
        id=AUDIT_EVENT_ID,
        actor_user_id=ADMIN_ID,
        actor_display_name="Ada Admin",
        actor_role="admin",
        subject_user_id=OTHER_ADMIN_ID,
        subject_email="other-admin@example.com",
        action="admin_role_changed",
        summary="Admin role changed",
        metadata={"before": {"role_key": "support"}, "after": {"role_key": "admin"}},
        created_at=NOW,
    )


def _administrator_detail() -> AdminAdministratorDetailResponse:
    return AdminAdministratorDetailResponse(
        id=OTHER_ADMIN_ID,
        full_name="Other Admin",
        email="other-admin@example.com",
        role_key="support",
        role_label="Support",
        account_status="active",
        email_verified=True,
        joined_at=NOW,
        last_sign_in_at=NOW,
        last_activity_at=NOW,
        permissions=["admin_settings_read"],
        sessions=[_session_item()],
        access_history=[_audit_event()],
        capabilities=AdminAdministratorActionCapabilities(
            can_change_role=True,
            can_deactivate=True,
            can_restore=False,
        ),
        is_current_actor=False,
    )


def _invitation_response(status: str = "pending") -> AdminAccessInvitationResponse:
    return AdminAccessInvitationResponse(
        id=INVITATION_ID,
        email="invitee@example.com",
        role_key="support",
        role_label="Support",
        status=status,
        invited_by_display_name="Ada Admin",
        accepted_by_display_name=None,
        created_at=NOW,
        expires_at=NOW,
        sent_at=NOW,
        accepted_at=None,
        revoked_at=None,
        resend_count=0,
    )


async def _admin_user() -> CurrentUser:
    return CurrentUser(
        id=ADMIN_ID,
        email="admin@example.com",
        role="admin",
        full_name="Ada Admin",
        is_active=True,
        session_family_id=SESSION_ID,
    )


async def _superadmin_user() -> CurrentUser:
    return CurrentUser(
        id=ADMIN_ID,
        email="superadmin@example.com",
        role="superadmin",
        full_name="Sam Superadmin",
        is_active=True,
        session_family_id=SESSION_ID,
    )


async def _candidate_user() -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        email="candidate@example.com",
        role="user",
        full_name="Casey Candidate",
        is_active=True,
        session_family_id=None,
    )


class FakeAdminSettingsService:
    def __init__(self) -> None:
        self.updated_me_payloads: list[object] = []
        self.revoked_session_ids: list[UUID] = []
        self.revoke_others_calls = 0
        self.notification_updates: list[object] = []
        self.list_params: list[object] = []
        self.role_updates: list[tuple[UUID, object]] = []
        self.deactivate_payloads: list[tuple[UUID, object]] = []
        self.restore_payloads: list[tuple[UUID, object]] = []
        self.invitation_payloads: list[object] = []
        self.revoked_invitation_ids: list[UUID] = []
        self.resent_invitation_ids: list[UUID] = []
        self.accept_payloads: list[object] = []

    async def get_me(self, actor: CurrentUser) -> AdminSettingsMeResponse:  # noqa: ARG002
        return _me_response()

    async def update_me(
        self,
        actor: CurrentUser,  # noqa: ARG002
        payload,  # noqa: ANN001
    ) -> AdminSettingsMeResponse:
        self.updated_me_payloads.append(payload)
        return _me_response().model_copy(update={"full_name": payload.full_name})

    async def list_my_sessions(
        self,
        actor: CurrentUser,  # noqa: ARG002
    ) -> list[AdminSettingsSessionResponse]:
        return [_session_item(current=True)]

    async def revoke_my_session(
        self,
        actor: CurrentUser,  # noqa: ARG002
        session_family_id: UUID,
    ) -> list[AdminSettingsSessionResponse]:
        self.revoked_session_ids.append(session_family_id)
        return [_session_item()]

    async def revoke_other_sessions(
        self,
        actor: CurrentUser,  # noqa: ARG002
    ) -> list[AdminSettingsSessionResponse]:
        self.revoke_others_calls += 1
        return [_session_item(current=True)]

    async def get_notification_preferences(
        self,
        actor: CurrentUser,  # noqa: ARG002
    ) -> AdminSettingsNotificationPreferencesResponse:
        return _notifications_response()

    async def update_notification_preferences(
        self,
        actor: CurrentUser,  # noqa: ARG002
        payload,  # noqa: ANN001
    ) -> AdminSettingsNotificationPreferencesResponse:
        self.notification_updates.append(payload)
        return _notifications_response()

    async def list_administrators(self, params) -> Page[AdminAdministratorListItemResponse]:  # noqa: ANN001
        self.list_params.append(params)
        return Page[AdminAdministratorListItemResponse].create(
            items=[
                AdminAdministratorListItemResponse(
                    id=OTHER_ADMIN_ID,
                    full_name="Other Admin",
                    email="other-admin@example.com",
                    role_key="support",
                    role_label="Support",
                    account_status="active",
                    email_verified=True,
                    joined_at=NOW,
                    last_sign_in_at=NOW,
                    last_activity_at=NOW,
                )
            ],
            total=1,
            params=PageParams(page=params.page, page_size=params.page_size),
        )

    async def get_administrator_detail(
        self,
        actor: CurrentUser,  # noqa: ARG002
        administrator_id: UUID,  # noqa: ARG002
    ) -> AdminAdministratorDetailResponse:
        return _administrator_detail()

    async def change_administrator_role(
        self,
        actor: CurrentUser,  # noqa: ARG002
        administrator_id: UUID,
        payload,  # noqa: ANN001
    ) -> AdminAdministratorDetailResponse:
        self.role_updates.append((administrator_id, payload))
        return _administrator_detail().model_copy(update={"role_key": payload.role_key})

    async def deactivate_administrator(
        self,
        actor: CurrentUser,  # noqa: ARG002
        administrator_id: UUID,
        payload,  # noqa: ANN001
    ) -> AdminAdministratorDetailResponse:
        self.deactivate_payloads.append((administrator_id, payload))
        return _administrator_detail().model_copy(update={"account_status": "suspended"})

    async def restore_administrator(
        self,
        actor: CurrentUser,  # noqa: ARG002
        administrator_id: UUID,
        payload,  # noqa: ANN001
    ) -> AdminAdministratorDetailResponse:
        self.restore_payloads.append((administrator_id, payload))
        return _administrator_detail()

    async def list_roles(self) -> list[AdminRoleResponse]:
        return [
            AdminRoleResponse(
                key="support",
                label="Support",
                description="Read-only internal operations access.",
                permissions=["admin_settings_read"],
                assignable=True,
            )
        ]

    async def list_audit_events(self, params) -> Page[AdminAccessAuditEventResponse]:  # noqa: ANN001
        self.list_params.append(params)
        return Page[AdminAccessAuditEventResponse].create(
            items=[_audit_event()],
            total=1,
            params=PageParams(page=params.page, page_size=params.page_size),
        )

    async def list_invitations(self, params) -> Page[AdminAccessInvitationResponse]:  # noqa: ANN001
        self.list_params.append(params)
        return Page[AdminAccessInvitationResponse].create(
            items=[_invitation_response()],
            total=1,
            params=PageParams(page=params.page, page_size=params.page_size),
        )

    async def create_invitation(
        self,
        actor: CurrentUser,  # noqa: ARG002
        payload,  # noqa: ANN001
    ) -> AdminAccessInvitationResponse:
        self.invitation_payloads.append(payload)
        return _invitation_response()

    async def revoke_invitation(
        self,
        actor: CurrentUser,  # noqa: ARG002
        invitation_public_id: UUID,
    ) -> AdminAccessInvitationResponse:
        self.revoked_invitation_ids.append(invitation_public_id)
        return _invitation_response(status="revoked")

    async def resend_invitation(
        self,
        actor: CurrentUser,  # noqa: ARG002
        invitation_public_id: UUID,
    ) -> AdminAccessInvitationResponse:
        self.resent_invitation_ids.append(invitation_public_id)
        return _invitation_response()

    async def accept_invitation(self, payload) -> TokenResponse:  # noqa: ANN001
        self.accept_payloads.append(payload)
        return TokenResponse(
            access_token="access-token",
            refresh_token="refresh-token",
            token_type="bearer",
            expires_in=3600,
        )


@pytest.mark.asyncio
async def test_admin_settings_routes_return_backend_truth_for_authorized_admin() -> None:
    fake = FakeAdminSettingsService()
    app.dependency_overrides[get_admin_settings_service] = lambda: fake
    app.dependency_overrides[get_current_user] = _admin_user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            me = await client.get("/api/v1/admin/settings/me")
            update_me = await client.patch(
                "/api/v1/admin/settings/me",
                json={"full_name": "Updated Admin"},
            )
            sessions = await client.get("/api/v1/admin/settings/sessions")
            revoke_session = await client.post(
                f"/api/v1/admin/settings/sessions/{SESSION_ID}/revoke"
            )
            revoke_others = await client.post("/api/v1/admin/settings/sessions/revoke-others")
            notifications = await client.get("/api/v1/admin/settings/notifications")
            update_notifications = await client.patch(
                "/api/v1/admin/settings/notifications",
                json={"categories": [{"key": "verification_operations", "enabled": False}]},
            )
    finally:
        app.dependency_overrides.clear()

    assert me.status_code == 200
    assert me.json()["email"] == "admin@example.com"
    assert update_me.status_code == 200
    assert update_me.json()["full_name"] == "Updated Admin"
    assert sessions.status_code == 200
    assert sessions.json()[0]["current"] is True
    assert revoke_session.status_code == 200
    assert revoke_others.status_code == 200
    assert notifications.status_code == 200
    assert notifications.json()["categories"][1]["required"] is True
    assert update_notifications.status_code == 200
    assert fake.updated_me_payloads[0].full_name == "Updated Admin"
    assert fake.revoked_session_ids == [SESSION_ID]
    assert fake.revoke_others_calls == 1
    assert fake.notification_updates[0].categories[0].key == "verification_operations"


@pytest.mark.asyncio
async def test_admin_access_routes_return_directory_roles_audit_and_invitations() -> None:
    fake = FakeAdminSettingsService()
    app.dependency_overrides[get_admin_settings_service] = lambda: fake
    app.dependency_overrides[get_current_user] = _admin_user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            directory = await client.get(
                "/api/v1/admin/administrators?page=2&page_size=5&search=other"
                "&role=support&status=active"
            )
            detail = await client.get(f"/api/v1/admin/administrators/{OTHER_ADMIN_ID}")
            change_role = await client.patch(
                f"/api/v1/admin/administrators/{OTHER_ADMIN_ID}/role",
                json={"role_key": "admin"},
            )
            deactivate = await client.post(
                f"/api/v1/admin/administrators/{OTHER_ADMIN_ID}/deactivate",
                json={"reason": "Staging deactivation"},
            )
            restore = await client.post(
                f"/api/v1/admin/administrators/{OTHER_ADMIN_ID}/restore",
                json={"reason": "Staging restoration"},
            )
            roles = await client.get("/api/v1/admin/roles")
            audit = await client.get("/api/v1/admin/administration/audit?page=1&page_size=10")
            invitations = await client.get(
                "/api/v1/admin/administrator-invitations?page=1&page_size=10"
            )
            create_invitation = await client.post(
                "/api/v1/admin/administrator-invitations",
                json={"email": "invitee@example.com", "role_key": "support"},
            )
            revoke_invitation = await client.post(
                f"/api/v1/admin/administrator-invitations/{INVITATION_ID}/revoke"
            )
            resend_invitation = await client.post(
                f"/api/v1/admin/administrator-invitations/{INVITATION_ID}/resend"
            )
    finally:
        app.dependency_overrides.clear()

    assert directory.status_code == 200
    assert directory.json()["page"] == 2
    assert directory.json()["items"][0]["email"] == "other-admin@example.com"
    assert fake.list_params[0].role == "support"
    assert fake.list_params[0].status == "active"
    assert detail.status_code == 200
    assert detail.json()["capabilities"]["can_change_role"] is True
    assert change_role.status_code == 200
    assert change_role.json()["role_key"] == "admin"
    assert deactivate.status_code == 200
    assert deactivate.json()["account_status"] == "suspended"
    assert restore.status_code == 200
    assert roles.status_code == 200
    assert roles.json()[0]["key"] == "support"
    assert audit.status_code == 200
    assert audit.json()["items"][0]["action"] == "admin_role_changed"
    assert invitations.status_code == 200
    assert "token" not in create_invitation.json()
    assert create_invitation.status_code == 201
    assert revoke_invitation.status_code == 200
    assert revoke_invitation.json()["status"] == "revoked"
    assert resend_invitation.status_code == 200
    assert fake.role_updates[0][1].role_key == "admin"
    assert fake.deactivate_payloads[0][1].reason == "Staging deactivation"
    assert fake.restore_payloads[0][1].reason == "Staging restoration"
    assert fake.invitation_payloads[0].email == "invitee@example.com"
    assert fake.revoked_invitation_ids == [INVITATION_ID]
    assert fake.resent_invitation_ids == [INVITATION_ID]


@pytest.mark.asyncio
async def test_administrator_directory_rejects_invalid_role_filter() -> None:
    fake = FakeAdminSettingsService()
    app.dependency_overrides[get_admin_settings_service] = lambda: fake
    app.dependency_overrides[get_current_user] = _admin_user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/admin/administrators?role=user")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert fake.list_params == []


@pytest.mark.asyncio
async def test_admin_invitation_accept_route_returns_tokens_without_auth() -> None:
    fake = FakeAdminSettingsService()
    app.dependency_overrides[get_admin_settings_service] = lambda: fake
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/auth/admin-invitations/accept",
                json={
                    "token": "this-is-a-valid-admin-invitation-token-12345",
                    "full_name": "Invited Admin",
                    "password": "StrongPassword123!",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["access_token"] == "access-token"
    assert len(fake.accept_payloads) == 1


@pytest.mark.asyncio
async def test_admin_settings_routes_fail_closed_for_non_admin_actor() -> None:
    fake = FakeAdminSettingsService()
    app.dependency_overrides[get_admin_settings_service] = lambda: fake
    app.dependency_overrides[get_current_user] = _candidate_user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            me = await client.get("/api/v1/admin/settings/me")
            directory = await client.get("/api/v1/admin/administrators")
            mutate = await client.patch(
                f"/api/v1/admin/administrators/{OTHER_ADMIN_ID}/role",
                json={"role_key": "admin"},
            )
    finally:
        app.dependency_overrides.clear()

    assert me.status_code == 403
    assert directory.status_code == 403
    assert mutate.status_code == 403


@pytest.mark.asyncio
async def test_admin_settings_routes_reject_unauthenticated_actor() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/admin/settings/me")

    assert response.status_code == 401


class _DummySession:
    async def scalar(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return 1


@pytest.mark.asyncio
async def test_final_superadmin_cannot_be_demoted_or_deactivated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.admin_settings_service.get_email_sender",
        lambda *args, **kwargs: SimpleNamespace(),
    )
    service = AdminSettingsService(_DummySession(), get_settings())
    actor = await _superadmin_user()
    target = User(
        email="superadmin-target@example.com",
        password_hash="hashed-password",
        full_name="Target Superadmin",
        role="superadmin",
        profile_slug="target-superadmin",
        is_active=True,
    )

    monkeypatch.setattr(
        service,
        "_count_active_highest_privilege_admins",
        lambda: _async_value(1),
    )

    with pytest.raises(ConflictError):
        await service._assert_role_change_allowed(actor, target, "admin")  # noqa: SLF001

    with pytest.raises(ConflictError):
        await service._assert_deactivation_allowed(actor, target)  # noqa: SLF001


@pytest.mark.asyncio
async def test_superadmin_safety_allows_changes_when_another_superadmin_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.admin_settings_service.get_email_sender",
        lambda *args, **kwargs: SimpleNamespace(),
    )
    service = AdminSettingsService(_DummySession(), get_settings())
    actor = await _superadmin_user()
    target = User(
        email="superadmin-target@example.com",
        password_hash="hashed-password",
        full_name="Target Superadmin",
        role="superadmin",
        profile_slug="target-superadmin",
        is_active=True,
    )

    monkeypatch.setattr(
        service,
        "_count_active_highest_privilege_admins",
        lambda: _async_value(2),
    )

    await service._assert_role_change_allowed(actor, target, "admin")  # noqa: SLF001
    await service._assert_deactivation_allowed(actor, target)  # noqa: SLF001


async def _async_value(value: int) -> int:
    return value
