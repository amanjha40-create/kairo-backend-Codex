"""Admin settings and administration routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.api.dependencies.services import get_admin_settings_service
from app.api.dependencies.verification_admin import (
    CurrentUser,
    require_admin_access_audit_read,
    require_admin_access_change_role,
    require_admin_access_deactivate,
    require_admin_access_invite,
    require_admin_access_read,
    require_admin_access_restore,
    require_admin_settings_read,
    require_admin_settings_update_self,
)
from app.schemas.admin_settings import (
    AdminAccessAuditEventResponse,
    AdminAccessInvitationCreateRequest,
    AdminAccessInvitationResponse,
    AdminAdministratorDeactivateRequest,
    AdminAdministratorDetailResponse,
    AdminAdministratorListItemResponse,
    AdminAdministratorListParams,
    AdminAdministratorRestoreRequest,
    AdminAdministratorRoleUpdateRequest,
    AdminInvitationAcceptRequest,
    AdminRoleResponse,
    AdminSettingsMeResponse,
    AdminSettingsMeUpdateRequest,
    AdminSettingsNotificationPreferencesResponse,
    AdminSettingsNotificationPreferencesUpdateRequest,
    AdminSettingsSessionResponse,
)
from app.schemas.auth import TokenResponse
from app.schemas.pagination import ListQueryParams, Page
from app.services.admin_settings_service import AdminSettingsService

router = APIRouter(tags=["admin-settings"])


def administrator_list_params(
    params: Annotated[ListQueryParams, Depends()],
    role: Annotated[str | None, Query()] = None,
) -> AdminAdministratorListParams:
    try:
        return AdminAdministratorListParams(**params.model_dump(), role=role)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc


@router.get("/admin/settings/me", response_model=AdminSettingsMeResponse)
async def get_admin_settings_me(
    actor: Annotated[CurrentUser, Depends(require_admin_settings_read)],
    svc: Annotated[AdminSettingsService, Depends(get_admin_settings_service)],
) -> AdminSettingsMeResponse:
    return await svc.get_me(actor)


@router.patch("/admin/settings/me", response_model=AdminSettingsMeResponse)
async def patch_admin_settings_me(
    payload: AdminSettingsMeUpdateRequest,
    actor: Annotated[CurrentUser, Depends(require_admin_settings_update_self)],
    svc: Annotated[AdminSettingsService, Depends(get_admin_settings_service)],
) -> AdminSettingsMeResponse:
    return await svc.update_me(actor, payload)


@router.get("/admin/settings/sessions", response_model=list[AdminSettingsSessionResponse])
async def list_admin_settings_sessions(
    actor: Annotated[CurrentUser, Depends(require_admin_settings_read)],
    svc: Annotated[AdminSettingsService, Depends(get_admin_settings_service)],
) -> list[AdminSettingsSessionResponse]:
    return await svc.list_my_sessions(actor)


@router.post(
    "/admin/settings/sessions/{session_id}/revoke",
    response_model=list[AdminSettingsSessionResponse],
)
async def revoke_admin_settings_session(
    session_id: UUID,
    actor: Annotated[CurrentUser, Depends(require_admin_settings_read)],
    svc: Annotated[AdminSettingsService, Depends(get_admin_settings_service)],
) -> list[AdminSettingsSessionResponse]:
    return await svc.revoke_my_session(actor, session_id)


@router.post(
    "/admin/settings/sessions/revoke-others",
    response_model=list[AdminSettingsSessionResponse],
)
async def revoke_other_admin_settings_sessions(
    actor: Annotated[CurrentUser, Depends(require_admin_settings_read)],
    svc: Annotated[AdminSettingsService, Depends(get_admin_settings_service)],
) -> list[AdminSettingsSessionResponse]:
    return await svc.revoke_other_sessions(actor)


@router.get(
    "/admin/settings/notifications",
    response_model=AdminSettingsNotificationPreferencesResponse,
)
async def get_admin_settings_notifications(
    actor: Annotated[CurrentUser, Depends(require_admin_settings_read)],
    svc: Annotated[AdminSettingsService, Depends(get_admin_settings_service)],
) -> AdminSettingsNotificationPreferencesResponse:
    return await svc.get_notification_preferences(actor)


@router.patch(
    "/admin/settings/notifications",
    response_model=AdminSettingsNotificationPreferencesResponse,
)
async def patch_admin_settings_notifications(
    payload: AdminSettingsNotificationPreferencesUpdateRequest,
    actor: Annotated[CurrentUser, Depends(require_admin_settings_update_self)],
    svc: Annotated[AdminSettingsService, Depends(get_admin_settings_service)],
) -> AdminSettingsNotificationPreferencesResponse:
    return await svc.update_notification_preferences(actor, payload)


@router.get("/admin/administrators", response_model=Page[AdminAdministratorListItemResponse])
async def list_administrators(
    params: Annotated[AdminAdministratorListParams, Depends(administrator_list_params)],
    _: Annotated[CurrentUser, Depends(require_admin_access_read)],
    svc: Annotated[AdminSettingsService, Depends(get_admin_settings_service)],
) -> Page[AdminAdministratorListItemResponse]:
    return await svc.list_administrators(params)


@router.get(
    "/admin/administrators/{administrator_id}",
    response_model=AdminAdministratorDetailResponse,
)
async def get_administrator(
    administrator_id: UUID,
    actor: Annotated[CurrentUser, Depends(require_admin_access_read)],
    svc: Annotated[AdminSettingsService, Depends(get_admin_settings_service)],
) -> AdminAdministratorDetailResponse:
    return await svc.get_administrator_detail(actor, administrator_id)


@router.patch(
    "/admin/administrators/{administrator_id}/role",
    response_model=AdminAdministratorDetailResponse,
)
async def patch_administrator_role(
    administrator_id: UUID,
    payload: AdminAdministratorRoleUpdateRequest,
    actor: Annotated[CurrentUser, Depends(require_admin_access_change_role)],
    svc: Annotated[AdminSettingsService, Depends(get_admin_settings_service)],
) -> AdminAdministratorDetailResponse:
    return await svc.change_administrator_role(actor, administrator_id, payload)


@router.post(
    "/admin/administrators/{administrator_id}/deactivate",
    response_model=AdminAdministratorDetailResponse,
)
async def deactivate_administrator(
    administrator_id: UUID,
    payload: AdminAdministratorDeactivateRequest,
    actor: Annotated[CurrentUser, Depends(require_admin_access_deactivate)],
    svc: Annotated[AdminSettingsService, Depends(get_admin_settings_service)],
) -> AdminAdministratorDetailResponse:
    return await svc.deactivate_administrator(actor, administrator_id, payload)


@router.post(
    "/admin/administrators/{administrator_id}/restore",
    response_model=AdminAdministratorDetailResponse,
)
async def restore_administrator(
    administrator_id: UUID,
    payload: AdminAdministratorRestoreRequest,
    actor: Annotated[CurrentUser, Depends(require_admin_access_restore)],
    svc: Annotated[AdminSettingsService, Depends(get_admin_settings_service)],
) -> AdminAdministratorDetailResponse:
    return await svc.restore_administrator(actor, administrator_id, payload)


@router.get("/admin/roles", response_model=list[AdminRoleResponse])
async def list_admin_roles(
    _: Annotated[CurrentUser, Depends(require_admin_access_read)],
    svc: Annotated[AdminSettingsService, Depends(get_admin_settings_service)],
) -> list[AdminRoleResponse]:
    return await svc.list_roles()


@router.get("/admin/administration/audit", response_model=Page[AdminAccessAuditEventResponse])
async def list_admin_audit(
    params: Annotated[ListQueryParams, Depends()],
    _: Annotated[CurrentUser, Depends(require_admin_access_audit_read)],
    svc: Annotated[AdminSettingsService, Depends(get_admin_settings_service)],
) -> Page[AdminAccessAuditEventResponse]:
    return await svc.list_audit_events(params)


@router.get("/admin/administrator-invitations", response_model=Page[AdminAccessInvitationResponse])
async def list_admin_invitations(
    params: Annotated[ListQueryParams, Depends()],
    _: Annotated[CurrentUser, Depends(require_admin_access_read)],
    svc: Annotated[AdminSettingsService, Depends(get_admin_settings_service)],
) -> Page[AdminAccessInvitationResponse]:
    return await svc.list_invitations(params)


@router.post(
    "/admin/administrator-invitations",
    response_model=AdminAccessInvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_admin_invitation(
    payload: AdminAccessInvitationCreateRequest,
    actor: Annotated[CurrentUser, Depends(require_admin_access_invite)],
    svc: Annotated[AdminSettingsService, Depends(get_admin_settings_service)],
) -> AdminAccessInvitationResponse:
    return await svc.create_invitation(actor, payload)


@router.post(
    "/admin/administrator-invitations/{invitation_id}/revoke",
    response_model=AdminAccessInvitationResponse,
)
async def revoke_admin_invitation(
    invitation_id: UUID,
    actor: Annotated[CurrentUser, Depends(require_admin_access_invite)],
    svc: Annotated[AdminSettingsService, Depends(get_admin_settings_service)],
) -> AdminAccessInvitationResponse:
    return await svc.revoke_invitation(actor, invitation_id)


@router.post(
    "/admin/administrator-invitations/{invitation_id}/resend",
    response_model=AdminAccessInvitationResponse,
)
async def resend_admin_invitation(
    invitation_id: UUID,
    actor: Annotated[CurrentUser, Depends(require_admin_access_invite)],
    svc: Annotated[AdminSettingsService, Depends(get_admin_settings_service)],
) -> AdminAccessInvitationResponse:
    return await svc.resend_invitation(actor, invitation_id)


@router.post("/auth/admin-invitations/accept", response_model=TokenResponse)
async def accept_admin_invitation(
    payload: AdminInvitationAcceptRequest,
    svc: Annotated[AdminSettingsService, Depends(get_admin_settings_service)],
) -> TokenResponse:
    return await svc.accept_invitation(payload)
