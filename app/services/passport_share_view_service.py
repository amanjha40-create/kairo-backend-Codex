"""View tracking and analytics for public Trust Passport shares."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.models.passport_share_view import PassportShareView
from app.repositories.passport_share import PassportShareRepository
from app.repositories.passport_share_view import PassportShareViewRepository
from app.schemas.passport_share import PassportShareAnalyticsResponse, PassportShareRecentViewResponse

_DEDUP_WINDOW_MINUTES = 5
_RECENT_VIEWS_LIMIT = 20


def _hash_ip(ip: str) -> str:
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()

class PassportShareViewService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._shares = PassportShareRepository(session)
        self._views = PassportShareViewRepository(session)

    async def record_successful_view(
        self,
        *,
        share_id: UUID,
        viewer_ip: str,
        user_agent: str | None,
        referrer: str | None,
    ) -> None:
        share = await self._shares.get_by_id(share_id)
        if share is None:
            raise NotFoundError("Passport share link not found")

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=_DEDUP_WINDOW_MINUTES)
        normalized_user_agent = self._normalize_user_agent(user_agent)
        normalized_referrer = self._normalize_referrer(referrer)
        viewer_ip_hash = _hash_ip(viewer_ip)
        is_unique = not await self._views.has_recent_view(
            share_id=share_id,
            viewer_ip_hash=viewer_ip_hash,
            user_agent=normalized_user_agent,
            cutoff=cutoff,
        )

        await self._views.create(
            PassportShareView(
                share_id=share_id,
                viewer_ip_hash=viewer_ip_hash,
                user_agent=normalized_user_agent,
                referrer=normalized_referrer,
                is_unique_view=is_unique,
            )
        )
        share.last_viewed_at = now
        await self._session.commit()

    async def get_analytics(
        self,
        *,
        owner_user_id: UUID,
        share_id: UUID,
    ) -> PassportShareAnalyticsResponse:
        share = await self._shares.get_owned(share_id, owner_user_id)
        if share is None:
            raise NotFoundError("Passport share link not found")

        total_views = await self._views.count_total_for_share(share_id)
        unique_views = await self._views.count_unique_for_share(share_id)
        recent_rows = await self._views.list_recent_for_share(share_id, limit=_RECENT_VIEWS_LIMIT)

        return PassportShareAnalyticsResponse(
            share_id=share.id,
            total_views=total_views,
            unique_views=unique_views,
            last_viewed_at=share.last_viewed_at,
            recent_views=[
                PassportShareRecentViewResponse(
                    viewed_at=row.created_at,
                    user_agent=row.user_agent,
                    referrer=row.referrer,
                    is_unique_view=row.is_unique_view,
                )
                for row in recent_rows
            ],
        )

    def _normalize_user_agent(self, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        return cleaned[:1024]

    def _normalize_referrer(self, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        return cleaned[:2048]
