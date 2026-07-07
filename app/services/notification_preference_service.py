"""Preference evaluation for notification center."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.contracts import NotificationPreferenceDecision
from app.notifications.enums import NotificationChannel
from app.repositories.notification import NotificationPreferenceRepository
from app.schemas.notification import NotificationPreferenceUpsertRequest
from app.models.notification_preference import NotificationPreference


class NotificationPreferenceService:
    """Evaluates and manages per-user notification preferences."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._preferences = NotificationPreferenceRepository(session)

    async def evaluate(
        self,
        *,
        recipient_user_id: UUID | None,
        event_type: str,
        requested_channel: str,
    ) -> NotificationPreferenceDecision:
        normalized_event_type = event_type.strip().lower()
        normalized_channel = requested_channel.strip().lower()
        if recipient_user_id is None:
            return NotificationPreferenceDecision(enabled=True, selected_channel=normalized_channel)

        preference = await self._preferences.get_for_user_event(recipient_user_id, normalized_event_type)
        if preference is None:
            return NotificationPreferenceDecision(enabled=True, selected_channel=normalized_channel)

        selected_channel = normalized_channel
        if preference.preferred_channels:
            preferred = [item.strip().lower() for item in preference.preferred_channels if item]
            if normalized_channel not in preferred and NotificationChannel.EMAIL.value in preferred:
                selected_channel = NotificationChannel.EMAIL.value
        return NotificationPreferenceDecision(
            enabled=preference.enabled,
            selected_channel=selected_channel,
            matched_preference_public_id=preference.public_id,
        )

    async def upsert_for_user(
        self,
        *,
        user_id: UUID,
        payload: NotificationPreferenceUpsertRequest,
    ) -> NotificationPreference:
        preference = await self._preferences.get_for_user_event(user_id, payload.event_type)
        if preference is None:
            preference = NotificationPreference(
                user_id=user_id,
                event_type=payload.event_type,
                enabled=payload.enabled,
                preferred_channels=payload.preferred_channels,
                quiet_hours=payload.quiet_hours,
                metadata_payload=payload.metadata,
            )
            await self._preferences.create(preference)
            await self._session.commit()
            return preference

        preference.enabled = payload.enabled
        preference.preferred_channels = payload.preferred_channels
        preference.quiet_hours = payload.quiet_hours
        preference.metadata_payload = payload.metadata
        await self._session.commit()
        return preference
