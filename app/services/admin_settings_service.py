"""Admin settings and administration service."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Iterable
from urllib.parse import urlencode
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser
from app.auth.email_utils import normalize_email
from app.auth.passwords import hash_password
from app.auth.tokens import create_access_token, generate_opaque_refresh_raw, hash_refresh_token
from app.config import Settings
from app.core.constants import Role
from app.core.permissions import ADMIN_PORTAL_ROLES, ROLE_PERMISSIONS
from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.integrations.email import get_email_sender
from app.models import (
    AdminAccessAuditEvent,
    AdminAccessInvitation,
    RefreshToken,
    User,
)
from app.repositories.notification import NotificationPreferenceRepository
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import UserRepository
from app.schemas.admin_settings import (
    AdminAccessAuditEventResponse,
    AdminAccessInvitationCreateRequest,
    AdminAccessInvitationResponse,
    AdminAdministratorActionCapabilities,
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
    AdminSettingsNotificationCategoryResponse,
    AdminSettingsNotificationCategoryUpdate,
    AdminSettingsNotificationPreferencesResponse,
    AdminSettingsNotificationPreferencesUpdateRequest,
    AdminSettingsSessionResponse,
)
from app.schemas.auth import TokenResponse
from app.schemas.pagination import ListQueryParams, Page, PageParams
from app.services.notification_preference_service import NotificationPreferenceService

STAFF_ROLES = ADMIN_PORTAL_ROLES
ROLE_LABELS: dict[str, str] = {
    Role.SUPPORT.value: "Support",
    Role.MODERATOR.value: "Moderator",
    Role.HR.value: "HR",
    Role.ADMIN.value: "Admin",
    Role.SUPERADMIN.value: "Superadmin",
}
ROLE_DESCRIPTIONS: dict[str, str] = {
    Role.SUPPORT.value: "Read-only internal operations access.",
    Role.MODERATOR.value: "Case review support with remarks and Trust & Safety notes.",
    Role.HR.value: "Verification reviewer access for review operations.",
    Role.ADMIN.value: "Operational admin with access-management authority.",
    Role.SUPERADMIN.value: "Highest-privilege operator with sanctioned role assignment authority.",
}
HIGHEST_PRIVILEGE_ROLE = Role.SUPERADMIN.value
CRITICAL_ADMIN_NOTIFICATION_EVENTS = (
    "account_security",
    "password_reset_requested",
    "security_alert",
)
ADMIN_NOTIFICATION_CATEGORIES = (
    {
        "key": "verification_operations",
        "label": "Verification operations",
        "description": "Queue, dispatch, and final-review operational notices.",
        "event_types": (
            "verification_queue",
            "verification_final_review",
            "verification_assignment",
        ),
        "required": False,
    },
    {
        "key": "trust_safety",
        "label": "Trust & Safety",
        "description": "Risk investigation and escalation notices.",
        "event_types": ("trust_safety_investigation", "trust_safety_assignment"),
        "required": False,
    },
    {
        "key": "system_operations",
        "label": "System operations",
        "description": "System incident and operational runtime notices.",
        "event_types": ("system_incident", "system_runtime"),
        "required": False,
    },
    {
        "key": "communications_failures",
        "label": "Communications failures",
        "description": "Failed deliveries and retryable communication incidents.",
        "event_types": ("communication_failure",),
        "required": False,
    },
    {
        "key": "account_security",
        "label": "Account security",
        "description": "Security-critical notices for your Admin account.",
        "event_types": CRITICAL_ADMIN_NOTIFICATION_EVENTS,
        "required": True,
    },
)


@dataclass(slots=True)
class _GroupedSession:
    id: UUID
    created_at: datetime
    expires_at: datetime
    last_active_at: datetime
    status: str
    revoked_at: datetime | None


class AdminSettingsService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._users = UserRepository(session)
        self._refresh = RefreshTokenRepository(session)
        self._preferences = NotificationPreferenceService(session)
        self._preference_repo = NotificationPreferenceRepository(session)
        self._email = get_email_sender(settings, session=session)

    async def get_me(self, actor: CurrentUser) -> AdminSettingsMeResponse:
        user = await self._require_user(actor.id)
        last_sign_in_at, last_activity_at = await self._session_activity(user.id)
        return AdminSettingsMeResponse(
            id=user.id,
            full_name=user.full_name,
            email=user.email,
            role_key=user.role,
            role_label=self._role_label(user.role),
            account_status=self._account_status(user),
            permissions=self._permission_values(user.role),
            email_verified=user.email_verified_at is not None,
            joined_at=user.created_at,
            last_sign_in_at=last_sign_in_at,
            last_activity_at=last_activity_at,
        )

    async def update_me(
        self,
        actor: CurrentUser,
        payload: AdminSettingsMeUpdateRequest,
    ) -> AdminSettingsMeResponse:
        user = await self._require_user(actor.id)
        previous_name = user.full_name
        user.full_name = payload.full_name.strip()
        await self._record_audit_event(
            actor=actor,
            subject_user=user,
            action="admin_profile_updated",
            summary="Admin profile updated",
            metadata={
                "before": {"full_name": previous_name},
                "after": {"full_name": user.full_name},
            },
        )
        await self._session.commit()
        return await self.get_me(actor)

    async def list_my_sessions(
        self,
        actor: CurrentUser,
    ) -> list[AdminSettingsSessionResponse]:
        return await self._list_grouped_sessions(actor.id, actor.session_family_id)

    async def revoke_my_session(
        self,
        actor: CurrentUser,
        session_family_id: UUID,
    ) -> list[AdminSettingsSessionResponse]:
        if actor.session_family_id is not None and session_family_id == actor.session_family_id:
            raise ConflictError("Current session cannot be revoked from this action")
        await self._revoke_session_family(actor.id, session_family_id)
        await self._record_audit_event(
            actor=actor,
            subject_user=await self._require_user(actor.id),
            action="admin_session_revoked",
            summary="Admin session revoked",
            metadata={"session_family_id": str(session_family_id)},
        )
        await self._session.commit()
        return await self.list_my_sessions(actor)

    async def revoke_other_sessions(
        self,
        actor: CurrentUser,
    ) -> list[AdminSettingsSessionResponse]:
        if actor.session_family_id is None:
            raise ConflictError("Current session could not be identified")
        await self._refresh.revoke_all_for_user_except_family(actor.id, actor.session_family_id)
        await self._record_audit_event(
            actor=actor,
            subject_user=await self._require_user(actor.id),
            action="admin_other_sessions_revoked",
            summary="Other admin sessions revoked",
        )
        await self._session.commit()
        return await self.list_my_sessions(actor)

    async def get_notification_preferences(
        self,
        actor: CurrentUser,
    ) -> AdminSettingsNotificationPreferencesResponse:
        preferences = await self._preference_repo.list_for_user(actor.id)
        by_event_type = {item.event_type: item for item in preferences}
        categories: list[AdminSettingsNotificationCategoryResponse] = []
        for definition in ADMIN_NOTIFICATION_CATEGORIES:
            required = bool(definition["required"])
            enabled = True
            for event_type in definition["event_types"]:
                preference = by_event_type.get(event_type)
                if preference is not None and not preference.enabled:
                    enabled = False
                    break
            categories.append(
                AdminSettingsNotificationCategoryResponse(
                    key=str(definition["key"]),
                    label=str(definition["label"]),
                    description=str(definition["description"]),
                    enabled=enabled if not required else True,
                    required=required,
                    event_types=list(definition["event_types"]),
                )
            )
        return AdminSettingsNotificationPreferencesResponse(categories=categories)

    async def update_notification_preferences(
        self,
        actor: CurrentUser,
        payload: AdminSettingsNotificationPreferencesUpdateRequest,
    ) -> AdminSettingsNotificationPreferencesResponse:
        categories = {item.key: item for item in payload.categories}
        for definition in ADMIN_NOTIFICATION_CATEGORIES:
            update = categories.get(str(definition["key"]))
            if update is None:
                continue
            if definition["required"] and not update.enabled:
                raise ConflictError("Critical security notifications cannot be disabled")
            for event_type in definition["event_types"]:
                await self._preferences.upsert_for_user(
                    user_id=actor.id,
                    payload=self._build_preference_update(event_type, update),
                )
        await self._record_audit_event(
            actor=actor,
            subject_user=await self._require_user(actor.id),
            action="admin_notification_preferences_updated",
            summary="Admin notification preferences updated",
            metadata={"categories": [item.model_dump() for item in payload.categories]},
        )
        await self._session.commit()
        return await self.get_notification_preferences(actor)

    async def list_administrators(
        self,
        params: AdminAdministratorListParams,
    ) -> Page[AdminAdministratorListItemResponse]:
        filters = [User.deleted_at.is_(None), User.role.in_(STAFF_ROLES)]
        if params.search:
            pattern = f"%{params.search.strip()}%"
            filters.append(or_(User.full_name.ilike(pattern), User.email.ilike(pattern)))
        if params.role:
            filters.append(User.role == params.role)
        if params.status and params.status != "all":
            normalized_statuses = {
                item.strip().lower() for item in params.status.split(",") if item.strip()
            }
            filters.append(self._status_filter(normalized_statuses))

        total = await self._session.scalar(select(func.count()).select_from(User).where(*filters))
        rows = (
            (
                await self._session.execute(
                    select(User)
                    .where(*filters)
                    .order_by(User.full_name.asc().nulls_last(), User.email.asc())
                    .offset(params.offset or 0)
                    .limit(params.limit or 20)
                )
            )
            .scalars()
            .all()
        )
        items = [await self._to_administrator_list_item(user) for user in rows]
        return Page[AdminAdministratorListItemResponse].create(
            items=items,
            total=int(total or 0),
            params=PageParams(page=params.page, page_size=params.page_size),
        )

    async def get_administrator_detail(
        self,
        actor: CurrentUser,
        administrator_id: UUID,
    ) -> AdminAdministratorDetailResponse:
        user = await self._require_administrator(administrator_id)
        last_sign_in_at, last_activity_at = await self._session_activity(user.id)
        sessions = await self._list_grouped_sessions(
            user.id,
            actor.session_family_id if actor.id == user.id else None,
        )
        history = await self._list_access_history(subject_user_id=user.id, limit=25)
        return AdminAdministratorDetailResponse(
            id=user.id,
            full_name=user.full_name,
            email=user.email,
            role_key=user.role,
            role_label=self._role_label(user.role),
            account_status=self._account_status(user),
            email_verified=user.email_verified_at is not None,
            joined_at=user.created_at,
            last_sign_in_at=last_sign_in_at,
            last_activity_at=last_activity_at,
            permissions=self._permission_values(user.role),
            sessions=sessions,
            access_history=history,
            capabilities=self._administrator_capabilities(actor, user),
            is_current_actor=actor.id == user.id,
        )

    async def change_administrator_role(
        self,
        actor: CurrentUser,
        administrator_id: UUID,
        payload: AdminAdministratorRoleUpdateRequest,
    ) -> AdminAdministratorDetailResponse:
        target = await self._require_administrator(administrator_id)
        self._assert_assignable_role(payload.role_key)
        await self._assert_role_change_allowed(actor, target, payload.role_key)
        before_role = target.role
        if before_role == payload.role_key:
            return await self.get_administrator_detail(actor, administrator_id)
        target.role = payload.role_key
        await self._refresh.revoke_all_for_user(target.id)
        await self._record_audit_event(
            actor=actor,
            subject_user=target,
            action="admin_role_changed",
            summary="Admin role changed",
            metadata={
                "before": {"role_key": before_role},
                "after": {"role_key": payload.role_key},
            },
        )
        await self._session.commit()
        return await self.get_administrator_detail(actor, administrator_id)

    async def deactivate_administrator(
        self,
        actor: CurrentUser,
        administrator_id: UUID,
        payload: AdminAdministratorDeactivateRequest,
    ) -> AdminAdministratorDetailResponse:
        target = await self._require_administrator(administrator_id)
        await self._assert_deactivation_allowed(actor, target)
        target.is_active = False
        target.suspended_at = datetime.now(tz=UTC)
        target.suspension_reason = payload.reason.strip()
        target.suspended_by_user_id = actor.id
        await self._refresh.revoke_all_for_user(target.id)
        await self._record_audit_event(
            actor=actor,
            subject_user=target,
            action="admin_access_deactivated",
            summary="Admin access deactivated",
            metadata={"reason": target.suspension_reason},
        )
        await self._session.commit()
        return await self.get_administrator_detail(actor, administrator_id)

    async def restore_administrator(
        self,
        actor: CurrentUser,
        administrator_id: UUID,
        payload: AdminAdministratorRestoreRequest,
    ) -> AdminAdministratorDetailResponse:
        target = await self._require_administrator(administrator_id)
        if target.is_active and target.suspended_at is None:
            return await self.get_administrator_detail(actor, administrator_id)
        target.is_active = True
        target.suspended_at = None
        target.suspension_reason = None
        target.suspended_by_user_id = None
        await self._record_audit_event(
            actor=actor,
            subject_user=target,
            action="admin_access_restored",
            summary="Admin access restored",
            metadata={"reason": payload.reason},
        )
        await self._session.commit()
        return await self.get_administrator_detail(actor, administrator_id)

    async def list_roles(self) -> list[AdminRoleResponse]:
        items: list[AdminRoleResponse] = []
        for role_key in STAFF_ROLES:
            items.append(
                AdminRoleResponse(
                    key=role_key,
                    label=self._role_label(role_key),
                    description=ROLE_DESCRIPTIONS.get(role_key, "Sanctioned internal Admin role."),
                    permissions=self._permission_values(role_key),
                    assignable=True,
                )
            )
        return items

    async def list_audit_events(
        self,
        params: ListQueryParams,
    ) -> Page[AdminAccessAuditEventResponse]:
        filters = []
        if params.search:
            pattern = f"%{params.search.strip()}%"
            filters.append(
                or_(
                    AdminAccessAuditEvent.actor_display_name.ilike(pattern),
                    AdminAccessAuditEvent.subject_email.ilike(pattern),
                    AdminAccessAuditEvent.summary.ilike(pattern),
                    AdminAccessAuditEvent.action.ilike(pattern),
                )
            )
        if params.status:
            actions = {item.strip().lower() for item in params.status.split(",") if item.strip()}
            filters.append(AdminAccessAuditEvent.action.in_(actions))

        total = await self._session.scalar(
            select(func.count()).select_from(AdminAccessAuditEvent).where(*filters)
        )
        rows = (
            (
                await self._session.execute(
                    select(AdminAccessAuditEvent)
                    .where(*filters)
                    .order_by(AdminAccessAuditEvent.created_at.desc())
                    .offset(params.offset or 0)
                    .limit(params.limit or 20)
                )
            )
            .scalars()
            .all()
        )
        items = [self._to_audit_response(item) for item in rows]
        return Page[AdminAccessAuditEventResponse].create(
            items=items,
            total=int(total or 0),
            params=PageParams(page=params.page, page_size=params.page_size),
        )

    async def list_invitations(
        self,
        params: ListQueryParams,
    ) -> Page[AdminAccessInvitationResponse]:
        await self._expire_invitations()
        filters = []
        if params.search:
            pattern = f"%{params.search.strip()}%"
            filters.append(AdminAccessInvitation.invitee_email.ilike(pattern))
        if params.status and params.status != "all":
            statuses = {item.strip().lower() for item in params.status.split(",") if item.strip()}
            filters.append(AdminAccessInvitation.status.in_(statuses))

        total = await self._session.scalar(
            select(func.count()).select_from(AdminAccessInvitation).where(*filters)
        )
        rows = (
            (
                await self._session.execute(
                    select(AdminAccessInvitation)
                    .where(*filters)
                    .order_by(AdminAccessInvitation.created_at.desc())
                    .offset(params.offset or 0)
                    .limit(params.limit or 20)
                )
            )
            .scalars()
            .all()
        )
        items = [await self._to_invitation_response(item) for item in rows]
        return Page[AdminAccessInvitationResponse].create(
            items=items,
            total=int(total or 0),
            params=PageParams(page=params.page, page_size=params.page_size),
        )

    async def create_invitation(
        self,
        actor: CurrentUser,
        payload: AdminAccessInvitationCreateRequest,
    ) -> AdminAccessInvitationResponse:
        self._assert_assignable_role(payload.role_key)
        if actor.role != Role.SUPERADMIN.value and payload.role_key == Role.SUPERADMIN.value:
            raise ForbiddenError("Only superadmins can invite another superadmin")
        email = normalize_email(str(payload.email))
        existing_user = await self._users.get_by_email(email)
        if (
            existing_user is not None
            and existing_user.role in STAFF_ROLES
            and existing_user.is_active
        ):
            raise ConflictError("This account already has active Admin access")
        pending = await self._session.scalar(
            select(AdminAccessInvitation).where(
                AdminAccessInvitation.invitee_email == email,
                AdminAccessInvitation.status == "pending",
            )
        )
        if pending is not None:
            raise ConflictError("A pending admin invitation already exists for this email")

        raw_token = generate_opaque_refresh_raw()
        invitation = AdminAccessInvitation(
            invited_by_user_id=actor.id,
            invitee_user_id=existing_user.id if existing_user is not None else None,
            invitee_email=email,
            role=payload.role_key,
            status="pending",
            token_hash=hash_refresh_token(raw_token),
            expires_at=datetime.now(tz=UTC) + timedelta(days=7),
            sent_at=datetime.now(tz=UTC),
        )
        self._session.add(invitation)
        await self._session.flush()
        await self._email.send_admin_invitation(
            to_email=email,
            invited_role_label=self._role_label(payload.role_key),
            invitation_url=self._admin_invitation_url(raw_token),
            expires_at=invitation.expires_at,
            audit_metadata={"admin_access_invitation_public_id": str(invitation.public_id)},
        )
        await self._record_audit_event(
            actor=actor,
            subject_user=existing_user,
            action="admin_invitation_created",
            summary="Admin invitation created",
            subject_email=email,
            invitation=invitation,
            metadata={"role_key": payload.role_key},
        )
        await self._session.commit()
        return await self._to_invitation_response(invitation)

    async def revoke_invitation(
        self,
        actor: CurrentUser,
        invitation_public_id: UUID,
    ) -> AdminAccessInvitationResponse:
        invitation = await self._require_invitation(invitation_public_id)
        if invitation.status != "pending":
            raise ConflictError("Only pending admin invitations can be revoked")
        invitation.status = "revoked"
        invitation.revoked_at = datetime.now(tz=UTC)
        await self._record_audit_event(
            actor=actor,
            subject_user=invitation.invitee_user,
            action="admin_invitation_revoked",
            summary="Admin invitation revoked",
            subject_email=invitation.invitee_email,
            invitation=invitation,
        )
        await self._session.commit()
        return await self._to_invitation_response(invitation)

    async def resend_invitation(
        self,
        actor: CurrentUser,
        invitation_public_id: UUID,
    ) -> AdminAccessInvitationResponse:
        invitation = await self._require_invitation(invitation_public_id)
        if invitation.status != "pending":
            raise ConflictError("Only pending admin invitations can be resent")
        raw_token = generate_opaque_refresh_raw()
        invitation.token_hash = hash_refresh_token(raw_token)
        invitation.sent_at = datetime.now(tz=UTC)
        invitation.expires_at = invitation.sent_at + timedelta(days=7)
        invitation.resend_count += 1
        await self._email.send_admin_invitation(
            to_email=invitation.invitee_email,
            invited_role_label=self._role_label(invitation.role),
            invitation_url=self._admin_invitation_url(raw_token),
            expires_at=invitation.expires_at,
            audit_metadata={"admin_access_invitation_public_id": str(invitation.public_id)},
        )
        await self._record_audit_event(
            actor=actor,
            subject_user=invitation.invitee_user,
            action="admin_invitation_resent",
            summary="Admin invitation resent",
            subject_email=invitation.invitee_email,
            invitation=invitation,
            metadata={"resend_count": invitation.resend_count},
        )
        await self._session.commit()
        return await self._to_invitation_response(invitation)

    async def accept_invitation(
        self,
        payload: AdminInvitationAcceptRequest,
    ) -> TokenResponse:
        invitation = await self._resolve_invitation_token(payload.token)
        if invitation.status != "pending":
            raise ConflictError("Admin invitation is no longer actionable")

        user = await self._users.get_by_email(invitation.invitee_email)
        now = datetime.now(tz=UTC)
        if user is None:
            if not payload.full_name or not payload.password:
                raise ConflictError("Full name and password are required to accept this invitation")
            user = User(
                email=invitation.invitee_email,
                password_hash=hash_password(payload.password),
                full_name=payload.full_name.strip(),
                role=invitation.role,
                email_verified_at=now,
                profile_slug=self._unique_slug(payload.full_name, invitation.invitee_email),
                is_active=True,
            )
            self._session.add(user)
            await self._session.flush()
        else:
            if user.deleted_at is not None:
                raise ConflictError("Deleted accounts cannot accept admin invitations")
            if not user.is_active:
                raise ConflictError("Inactive accounts cannot accept admin invitations")
            if payload.password:
                user.password_hash = hash_password(payload.password)
            if payload.full_name and not (user.full_name or "").strip():
                user.full_name = payload.full_name.strip()
            if user.email_verified_at is None:
                user.email_verified_at = now
            user.role = invitation.role

        invitation.status = "accepted"
        invitation.accepted_at = now
        invitation.accepted_by_user_id = user.id
        invitation.invitee_user_id = user.id

        await self._record_audit_event(
            actor=CurrentUser(
                id=user.id,
                email=user.email,
                role=user.role,
                full_name=user.full_name,
                is_active=user.is_active,
                session_family_id=None,
            ),
            subject_user=user,
            action="admin_invitation_accepted",
            summary="Admin invitation accepted",
            subject_email=user.email,
            invitation=invitation,
            metadata={"role_key": invitation.role},
        )
        tokens = await self._issue_tokens(user)
        await self._session.commit()
        return tokens

    async def _require_user(self, user_id: UUID) -> User:
        user = await self._users.get_by_id(user_id)
        if user is None or user.deleted_at is not None:
            raise NotFoundError("Admin account not found")
        return user

    async def _require_administrator(self, user_id: UUID) -> User:
        user = await self._require_user(user_id)
        if user.role not in STAFF_ROLES:
            raise NotFoundError("Administrator not found")
        return user

    async def _require_invitation(self, invitation_public_id: UUID) -> AdminAccessInvitation:
        invitation = await self._session.scalar(
            select(AdminAccessInvitation).where(
                AdminAccessInvitation.public_id == invitation_public_id
            )
        )
        if invitation is None:
            raise NotFoundError("Admin invitation not found")
        await self._expire_if_needed(invitation)
        return invitation

    async def _resolve_invitation_token(self, raw_token: str) -> AdminAccessInvitation:
        invitation = await self._session.scalar(
            select(AdminAccessInvitation).where(
                AdminAccessInvitation.token_hash == hash_refresh_token(raw_token.strip())
            )
        )
        if invitation is None:
            raise NotFoundError("Admin invitation not found")
        await self._expire_if_needed(invitation)
        if invitation.status != "pending":
            raise ConflictError("Admin invitation is no longer actionable")
        return invitation

    def _admin_invitation_url(self, raw_token: str) -> str:
        base_url = self._settings.admin_portal_base_url.rstrip("/")
        return f"{base_url}/admin/accept-invitation#{urlencode({'token': raw_token})}"

    async def _expire_invitations(self) -> None:
        rows = (
            (
                await self._session.execute(
                    select(AdminAccessInvitation).where(AdminAccessInvitation.status == "pending")
                )
            )
            .scalars()
            .all()
        )
        changed = False
        for row in rows:
            changed = await self._expire_if_needed(row) or changed
        if changed:
            await self._session.commit()

    async def _expire_if_needed(self, invitation: AdminAccessInvitation) -> bool:
        if invitation.status != "pending":
            return False
        if invitation.expires_at > datetime.now(tz=UTC):
            return False
        invitation.status = "expired"
        return True

    async def _session_activity(self, user_id: UUID) -> tuple[datetime | None, datetime | None]:
        row = (
            await self._session.execute(
                select(func.max(RefreshToken.created_at), func.max(RefreshToken.updated_at)).where(
                    RefreshToken.user_id == user_id
                )
            )
        ).one()
        return row[0], row[1]

    async def _list_grouped_sessions(
        self,
        user_id: UUID,
        current_session_family_id: UUID | None,
    ) -> list[AdminSettingsSessionResponse]:
        rows = (
            (
                await self._session.execute(
                    select(RefreshToken)
                    .where(RefreshToken.user_id == user_id)
                    .order_by(RefreshToken.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        grouped = self._group_sessions(rows)
        return [
            AdminSettingsSessionResponse(
                id=item.id,
                created_at=item.created_at,
                expires_at=item.expires_at,
                last_active_at=item.last_active_at,
                current=item.id == current_session_family_id,
                status=item.status,
                revoked_at=item.revoked_at,
            )
            for item in grouped
        ]

    def _group_sessions(self, rows: Iterable[RefreshToken]) -> list[_GroupedSession]:
        now = datetime.now(tz=UTC)
        grouped: dict[UUID, list[RefreshToken]] = {}
        for row in rows:
            grouped.setdefault(row.family_id, []).append(row)
        sessions: list[_GroupedSession] = []
        for family_id, family_rows in grouped.items():
            created_at = min(item.created_at for item in family_rows)
            last_active_at = max(item.updated_at for item in family_rows)
            expires_at = max(item.expires_at for item in family_rows)
            active_rows = [
                item for item in family_rows if item.revoked_at is None and item.expires_at > now
            ]
            revoked_rows = [item for item in family_rows if item.revoked_at is not None]
            if active_rows:
                status = "active"
                revoked_at = None
            elif revoked_rows:
                status = "revoked"
                revoked_at = max(
                    item.revoked_at for item in revoked_rows if item.revoked_at is not None
                )
            else:
                status = "expired"
                revoked_at = None
            sessions.append(
                _GroupedSession(
                    id=family_id,
                    created_at=created_at,
                    expires_at=expires_at,
                    last_active_at=last_active_at,
                    status=status,
                    revoked_at=revoked_at,
                )
            )
        sessions.sort(key=lambda item: item.last_active_at, reverse=True)
        return sessions

    async def _revoke_session_family(self, user_id: UUID, session_family_id: UUID) -> None:
        rows = (
            (
                await self._session.execute(
                    select(RefreshToken).where(
                        RefreshToken.user_id == user_id,
                        RefreshToken.family_id == session_family_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            raise NotFoundError("Session not found")
        await self._refresh.revoke_family(session_family_id)

    async def _list_access_history(
        self,
        *,
        subject_user_id: UUID,
        limit: int,
    ) -> list[AdminAccessAuditEventResponse]:
        rows = (
            (
                await self._session.execute(
                    select(AdminAccessAuditEvent)
                    .where(AdminAccessAuditEvent.subject_user_id == subject_user_id)
                    .order_by(AdminAccessAuditEvent.created_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return [self._to_audit_response(item) for item in rows]

    async def _record_audit_event(
        self,
        *,
        actor: CurrentUser,
        action: str,
        summary: str,
        subject_user: User | None = None,
        subject_email: str | None = None,
        invitation: AdminAccessInvitation | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self._session.add(
            AdminAccessAuditEvent(
                actor_user_id=actor.id,
                subject_user_id=subject_user.id if subject_user is not None else None,
                invitation_id=invitation.id if invitation is not None else None,
                actor_role=actor.role,
                actor_display_name=self._display_name(actor.full_name, actor.email),
                subject_email=subject_email
                or (subject_user.email if subject_user is not None else None),
                action=action,
                summary=summary,
                metadata_payload=metadata or {},
            )
        )
        await self._session.flush()

    def _to_audit_response(self, event: AdminAccessAuditEvent) -> AdminAccessAuditEventResponse:
        return AdminAccessAuditEventResponse(
            id=event.public_id,
            actor_user_id=event.actor_user_id,
            actor_display_name=event.actor_display_name,
            actor_role=event.actor_role,
            subject_user_id=event.subject_user_id,
            subject_email=event.subject_email,
            action=event.action,
            summary=event.summary,
            metadata=event.metadata_payload or {},
            created_at=event.created_at,
        )

    async def _to_administrator_list_item(self, user: User) -> AdminAdministratorListItemResponse:
        last_sign_in_at, last_activity_at = await self._session_activity(user.id)
        return AdminAdministratorListItemResponse(
            id=user.id,
            full_name=user.full_name,
            email=user.email,
            role_key=user.role,
            role_label=self._role_label(user.role),
            account_status=self._account_status(user),
            email_verified=user.email_verified_at is not None,
            joined_at=user.created_at,
            last_sign_in_at=last_sign_in_at,
            last_activity_at=last_activity_at,
        )

    async def _to_invitation_response(
        self,
        invitation: AdminAccessInvitation,
    ) -> AdminAccessInvitationResponse:
        invited_by = await self._users.get_by_id(invitation.invited_by_user_id)
        accepted_by = (
            await self._users.get_by_id(invitation.accepted_by_user_id)
            if invitation.accepted_by_user_id is not None
            else None
        )
        return AdminAccessInvitationResponse(
            id=invitation.public_id,
            email=invitation.invitee_email,
            role_key=invitation.role,
            role_label=self._role_label(invitation.role),
            status=invitation.status,
            invited_by_display_name=self._display_name(
                invited_by.full_name if invited_by is not None else None,
                invited_by.email if invited_by is not None else invitation.invitee_email,
            )
            if invited_by is not None
            else None,
            accepted_by_display_name=self._display_name(
                accepted_by.full_name if accepted_by is not None else None,
                accepted_by.email if accepted_by is not None else invitation.invitee_email,
            )
            if accepted_by is not None
            else None,
            created_at=invitation.created_at,
            expires_at=invitation.expires_at,
            sent_at=invitation.sent_at,
            accepted_at=invitation.accepted_at,
            revoked_at=invitation.revoked_at,
            resend_count=invitation.resend_count,
        )

    def _administrator_capabilities(
        self,
        actor: CurrentUser,
        subject: User,
    ) -> AdminAdministratorActionCapabilities:
        return AdminAdministratorActionCapabilities(
            can_change_role=self._can_change_role(actor, subject),
            can_deactivate=self._can_deactivate(actor, subject),
            can_restore=self._can_restore(actor, subject),
        )

    def _can_change_role(self, actor: CurrentUser, subject: User) -> bool:
        if actor.role not in {Role.ADMIN.value, Role.SUPERADMIN.value}:
            return False
        if actor.id == subject.id:
            return False
        if actor.role != Role.SUPERADMIN.value and subject.role == Role.SUPERADMIN.value:
            return False
        return True

    def _can_deactivate(self, actor: CurrentUser, subject: User) -> bool:
        if actor.role not in {Role.ADMIN.value, Role.SUPERADMIN.value}:
            return False
        if subject.is_active is False:
            return False
        if actor.id == subject.id:
            return False
        if actor.role != Role.SUPERADMIN.value and subject.role == Role.SUPERADMIN.value:
            return False
        return True

    def _can_restore(self, actor: CurrentUser, subject: User) -> bool:
        if actor.role not in {Role.ADMIN.value, Role.SUPERADMIN.value}:
            return False
        if subject.is_active is True and subject.suspended_at is None:
            return False
        if actor.role != Role.SUPERADMIN.value and subject.role == Role.SUPERADMIN.value:
            return False
        return True

    def _assert_assignable_role(self, role_key: str) -> None:
        if role_key not in STAFF_ROLES:
            raise ConflictError("Unsupported admin role")

    async def _assert_role_change_allowed(
        self, actor: CurrentUser, target: User, next_role: str
    ) -> None:
        if not self._can_change_role(actor, target):
            raise ForbiddenError("You do not have permission to change this administrator role")
        if actor.role != Role.SUPERADMIN.value and next_role == Role.SUPERADMIN.value:
            raise ForbiddenError("Only superadmins can grant superadmin access")
        if target.role == HIGHEST_PRIVILEGE_ROLE and next_role != HIGHEST_PRIVILEGE_ROLE:
            active_superadmins = await self._count_active_highest_privilege_admins()
            if active_superadmins <= 1:
                raise ConflictError("The final superadmin role cannot be removed")

    async def _assert_deactivation_allowed(self, actor: CurrentUser, target: User) -> None:
        if not self._can_deactivate(actor, target):
            raise ForbiddenError("You do not have permission to deactivate this administrator")
        if (
            target.role == HIGHEST_PRIVILEGE_ROLE
            and await self._count_active_highest_privilege_admins() <= 1
        ):
            raise ConflictError("The final superadmin cannot be deactivated")

    async def _count_active_highest_privilege_admins(self) -> int:
        total = await self._session.scalar(
            select(func.count())
            .select_from(User)
            .where(
                User.role == HIGHEST_PRIVILEGE_ROLE,
                User.deleted_at.is_(None),
                User.is_active.is_(True),
            )
        )
        return int(total or 0)

    def _role_label(self, role_key: str) -> str:
        return ROLE_LABELS.get(role_key, role_key.replace("_", " ").title())

    def _permission_values(self, role_key: str) -> list[str]:
        return sorted(
            permission.value for permission in ROLE_PERMISSIONS.get(role_key, frozenset())
        )

    def _account_status(self, user: User) -> str:
        if user.deleted_at is not None:
            return "deleted"
        if not user.is_active or user.suspended_at is not None:
            return "suspended"
        return "active"

    def _status_filter(self, statuses: set[str]):
        active_selected = "active" in statuses
        suspended_selected = "suspended" in statuses
        deleted_selected = "deleted" in statuses
        clauses = []
        if active_selected:
            clauses.append(
                User.deleted_at.is_(None) & User.is_active.is_(True) & User.suspended_at.is_(None)
            )
        if suspended_selected:
            clauses.append(
                User.deleted_at.is_(None)
                & ((User.is_active.is_(False)) | User.suspended_at.is_not(None))
            )
        if deleted_selected:
            clauses.append(User.deleted_at.is_not(None))
        if not clauses:
            return User.deleted_at.is_(None)
        return or_(*clauses)

    def _build_preference_update(
        self,
        event_type: str,
        update: AdminSettingsNotificationCategoryUpdate,
    ):
        from app.schemas.notification import NotificationPreferenceUpsertRequest

        return NotificationPreferenceUpsertRequest(
            event_type=event_type,
            enabled=update.enabled,
            preferred_channels=["in_app", "email"],
            quiet_hours={},
            metadata={"admin_settings_category": update.key},
        )

    def _display_name(self, full_name: str | None, email: str) -> str:
        if full_name and full_name.strip():
            return full_name.strip()
        return email

    def _unique_slug(self, full_name: str, email: str) -> str:
        base = (full_name or email.split("@")[0]).strip().lower().replace(" ", "-")
        base = base[:60].strip("-") or "admin"
        return f"{base}-{uuid.uuid4().hex[:4]}"

    async def _issue_tokens(self, user: User) -> TokenResponse:
        raw_refresh = generate_opaque_refresh_raw()
        token_hash = hash_refresh_token(raw_refresh)
        family_id = uuid.uuid4()
        expires_at = datetime.now(tz=UTC) + timedelta(days=self._settings.jwt_refresh_ttl_days)
        self._session.add(
            RefreshToken(
                user_id=user.id,
                token_hash=token_hash,
                expires_at=expires_at,
                family_id=family_id,
            )
        )
        await self._session.flush()
        access_token = create_access_token(
            self._settings,
            subject=user.id,
            role=user.role,
            extra_claims={"sid": str(family_id)},
        )
        return TokenResponse(
            access_token=access_token,
            refresh_token=raw_refresh,
            expires_in=self._settings.jwt_access_ttl_minutes * 60,
        )
