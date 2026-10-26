"""One-time promotion of an existing Admin to the first Superadmin."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Role
from app.core.permissions import ADMIN_PORTAL_ROLES
from app.models import AdminAccessAuditEvent, RefreshToken, User
from app.repositories.refresh_token import RefreshTokenRepository

BOOTSTRAP_AUDIT_ACTION = "FIRST_SUPERADMIN_BOOTSTRAPPED"
BOOTSTRAP_EXECUTION_CONTEXT = "bootstrap_first_superadmin_cli"


class FirstSuperadminBootstrapRefused(RuntimeError):
    """Safe, stable refusal from a first-Superadmin bootstrap guard."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class FirstSuperadminBootstrapResult:
    target_user_id: UUID
    administrator_id: UUID
    prior_role: str
    new_role: str
    sessions_revoked: int
    audit_event_id: UUID


class FirstSuperadminBootstrapService:
    """Promote one exact existing Admin while preserving its canonical user row."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._refresh_tokens = RefreshTokenRepository(session)

    async def promote(
        self,
        *,
        target_user_id: UUID,
        target_email: str,
        expected_current_role: str,
        environment: str,
        source_sha: str,
    ) -> FirstSuperadminBootstrapResult:
        await self._validate_state(
            target_user_id=target_user_id,
            target_email=target_email,
            expected_current_role=expected_current_role,
            require_locked_target=False,
        )

        # Every current staff row is locked in UUID order. Competing bootstrap
        # commands therefore serialize before the authoritative re-check.
        await self._lock_staff_rows()
        target = await self._validate_state(
            target_user_id=target_user_id,
            target_email=target_email,
            expected_current_role=expected_current_role,
            require_locked_target=True,
        )

        active_sessions = await self._session.scalar(
            select(func.count())
            .select_from(RefreshToken)
            .where(
                RefreshToken.user_id == target.id,
                RefreshToken.revoked_at.is_(None),
            )
        )
        sessions_revoked = int(active_sessions or 0)

        prior_role = target.role
        target.role = Role.SUPERADMIN.value
        await self._refresh_tokens.revoke_all_for_user(target.id)

        occurred_at = datetime.now(tz=UTC)
        audit_event = AdminAccessAuditEvent(
            actor_user_id=None,
            subject_user_id=target.id,
            actor_role="system",
            actor_display_name="First Superadmin Bootstrap",
            subject_email=target.email,
            action=BOOTSTRAP_AUDIT_ACTION,
            summary="Existing Admin promoted to first Superadmin",
            metadata_payload={
                "target_user_id": str(target.id),
                "administrator_id": str(target.id),
                "prior_role": prior_role,
                "new_role": Role.SUPERADMIN.value,
                "environment": environment,
                "timestamp": occurred_at.isoformat(),
                "source_sha": source_sha,
                "execution_context": BOOTSTRAP_EXECUTION_CONTEXT,
                "sessions_revoked": sessions_revoked,
            },
            created_at=occurred_at,
        )
        self._session.add(audit_event)
        await self._session.flush()

        return FirstSuperadminBootstrapResult(
            target_user_id=target.id,
            administrator_id=target.id,
            prior_role=prior_role,
            new_role=target.role,
            sessions_revoked=sessions_revoked,
            audit_event_id=audit_event.public_id,
        )

    async def _lock_staff_rows(self) -> None:
        await self._session.execute(
            select(User)
            .where(User.role.in_(ADMIN_PORTAL_ROLES))
            .order_by(User.id)
            .with_for_update(of=User)
            .execution_options(populate_existing=True)
        )

    async def _validate_state(
        self,
        *,
        target_user_id: UUID,
        target_email: str,
        expected_current_role: str,
        require_locked_target: bool,
    ) -> User:
        if expected_current_role != Role.ADMIN.value:
            raise FirstSuperadminBootstrapRefused("expected_role_must_be_admin")

        existing_audit = await self._session.scalar(
            select(func.count())
            .select_from(AdminAccessAuditEvent)
            .where(AdminAccessAuditEvent.action == BOOTSTRAP_AUDIT_ACTION)
        )
        if int(existing_audit or 0) != 0:
            raise FirstSuperadminBootstrapRefused("bootstrap_already_completed")

        active_superadmins = await self._session.scalar(
            select(func.count())
            .select_from(User)
            .where(
                User.role == Role.SUPERADMIN.value,
                User.is_active.is_(True),
                User.deleted_at.is_(None),
            )
        )
        if int(active_superadmins or 0) != 0:
            raise FirstSuperadminBootstrapRefused("active_superadmin_exists")

        target_statement = (
            select(User)
            .where(
                or_(
                    User.id == target_user_id,
                    func.lower(User.email) == target_email,
                )
            )
            .order_by(User.id)
        )
        if require_locked_target:
            target_statement = target_statement.with_for_update(of=User).execution_options(
                populate_existing=True
            )
        rows = list((await self._session.execute(target_statement)).scalars().all())
        if len(rows) != 1:
            raise FirstSuperadminBootstrapRefused("target_identity_not_unique")

        target = rows[0]
        if target.id != target_user_id or target.email != target_email:
            raise FirstSuperadminBootstrapRefused("target_identity_mismatch")
        if target.deleted_at is not None:
            raise FirstSuperadminBootstrapRefused("target_deleted")
        if not target.is_active:
            raise FirstSuperadminBootstrapRefused("target_inactive")
        if target.email_verified_at is None:
            raise FirstSuperadminBootstrapRefused("target_unverified")
        if target.role != expected_current_role:
            raise FirstSuperadminBootstrapRefused("target_role_changed")
        return target
