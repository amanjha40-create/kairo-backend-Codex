"""Profile view tracking — records visits and aggregates analytics."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.profile_view import ProfileView

_DEDUP_WINDOW_HOURS = 24


def _hash_ip(ip: str) -> str:
    return hashlib.sha256(ip.encode()).hexdigest()


class ShareAnalyticsResponse(BaseModel):
    views: int
    unique_visitors: int
    # Placeholder fields kept for UI compatibility — will be populated as
    # viewer-identity features are added.
    recruiters: int = 0
    companies: int = 0


class ProfileViewService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_view(
        self,
        profile_user_id: UUID,
        viewer_ip: str,
        viewer_user_id: UUID | None = None,
    ) -> None:
        """Insert a view only if the same IP hasn't viewed this profile within 24 h."""
        ip_hash = _hash_ip(viewer_ip)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=_DEDUP_WINDOW_HOURS)

        already_viewed = (
            await self._session.execute(
                select(ProfileView.id).where(
                    ProfileView.profile_user_id == profile_user_id,
                    ProfileView.viewer_ip_hash == ip_hash,
                    ProfileView.created_at >= cutoff,
                )
            )
        ).scalar_one_or_none()

        if already_viewed:
            # Update viewer_user_id if they just logged in.
            if viewer_user_id:
                row = (
                    await self._session.execute(
                        select(ProfileView).where(ProfileView.id == already_viewed)
                    )
                ).scalar_one()
                if not row.viewer_user_id:
                    row.viewer_user_id = viewer_user_id
                    await self._session.commit()
            return

        self._session.add(
            ProfileView(
                id=uuid.uuid4(),
                profile_user_id=profile_user_id,
                viewer_ip_hash=ip_hash,
                viewer_user_id=viewer_user_id,
            )
        )
        await self._session.commit()

    async def get_analytics(self, profile_user_id: UUID) -> ShareAnalyticsResponse:
        """Return total views and unique visitor count for a profile."""
        total_views = (
            await self._session.execute(
                select(func.count()).where(
                    ProfileView.profile_user_id == profile_user_id,
                )
            )
        ).scalar_one()

        unique_visitors = (
            await self._session.execute(
                select(func.count(func.distinct(ProfileView.viewer_ip_hash))).where(
                    ProfileView.profile_user_id == profile_user_id,
                )
            )
        ).scalar_one()

        # Logged-in Kairo users who viewed the profile act as a proxy for
        # "known recruiter/employer" count until proper viewer roles are added.
        known_viewers = (
            await self._session.execute(
                select(func.count(func.distinct(ProfileView.viewer_user_id))).where(
                    ProfileView.profile_user_id == profile_user_id,
                    ProfileView.viewer_user_id.isnot(None),
                )
            )
        ).scalar_one()

        return ShareAnalyticsResponse(
            views=total_views,
            unique_visitors=unique_visitors,
            recruiters=known_viewers,
            companies=0,
        )
