"""Authenticated account settings and refresh-session management."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.exceptions import NotFoundError
from app.models import RefreshToken, User
from app.repositories.notification import NotificationPreferenceRepository
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import UserRepository
from app.schemas.account_settings import (
    AccountSessionResponse,
    AccountSettingsResponse,
    AccountSettingsUpdate,
    TrustScoreConsentSummary,
)
from app.schemas.notification import NotificationPreferenceResponse
from app.services.notification_preference_service import NotificationPreferenceService
from app.services.user_service import UserService


class AccountSettingsService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._users = UserRepository(session)
        self._refresh = RefreshTokenRepository(session)
        self._preferences = NotificationPreferenceService(session)
        self._preference_repo = NotificationPreferenceRepository(session)

    async def get(self, user_id: UUID) -> AccountSettingsResponse:
        user = await self._require_user(user_id)
        profile = await UserService(self._session, self._settings).get_public_profile(user_id)
        preferences = await self._preference_repo.list_for_user(user_id)
        return AccountSettingsResponse(
            profile=profile,
            trust_score_consent=TrustScoreConsentSummary(
                status="consented" if user.trust_score_consent_at else "not_consented",
                version=user.trust_score_consent_version,
                consented_at=user.trust_score_consent_at,
            ),
            notification_preferences=[NotificationPreferenceResponse.model_validate(item, from_attributes=True) for item in preferences],
            app_version=self._settings.app_version,
            api_version=self._settings.api_v1_prefix,
            trust_score_version=self._settings.trust_score_version,
        )

    async def update(self, user_id: UUID, payload: AccountSettingsUpdate) -> AccountSettingsResponse:
        user = await self._require_user(user_id)
        if payload.notification_preferences is not None:
            for preference in payload.notification_preferences:
                await self._preferences.upsert_for_user(user_id=user_id, payload=preference)
        if payload.withdraw_trust_score_consent and user.trust_score_consent_at is not None:
            user.trust_score_consent_at = None
            user.trust_score_consent_version = None
            await self._session.commit()
        return await self.get(user_id)

    async def list_sessions(self, user_id: UUID) -> list[AccountSessionResponse]:
        await self._require_user(user_id)
        rows = list(
            (
                await self._session.execute(
                    select(RefreshToken)
                    .where(
                        RefreshToken.user_id == user_id,
                        RefreshToken.revoked_at.is_(None),
                        RefreshToken.expires_at > datetime.now(UTC),
                    )
                    .order_by(RefreshToken.created_at.desc())
                )
            )
        .scalars()
        .all())
        return [
            AccountSessionResponse(
                id=row.id,
                created_at=row.created_at,
                expires_at=row.expires_at,
                last_active_at=row.updated_at,
            )
            for row in rows
        ]

    async def revoke_session(self, user_id: UUID, session_public_id: UUID) -> None:
        await self._require_user(user_id)
        row = await self._session.scalar(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id,
                RefreshToken.id == session_public_id,
                RefreshToken.revoked_at.is_(None),
            )
        )
        if row is None:
            raise NotFoundError("Session not found")
        await self._refresh.revoke(row.id)
        await self._session.commit()

    async def revoke_all_sessions(self, user_id: UUID) -> None:
        await self._require_user(user_id)
        await self._refresh.revoke_all_for_user(user_id)
        await self._session.commit()

    async def _require_user(self, user_id: UUID) -> User:
        user = await self._users.get_by_id(user_id)
        if user is None or user.deleted_at is not None:
            raise NotFoundError("User not found")
        return user
