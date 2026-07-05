"""Public profile endpoints — no authentication required."""

from __future__ import annotations

from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_optional_current_user
from app.api.dependencies.services import (
    get_profile_view_service,
    get_trust_score_service,
    get_user_service,
)
from app.db.session import get_session
from app.models import User
from app.schemas.trust_score import TrustScoreResponse
from app.services import TrustScoreService, UserService
from app.services.profile_view_service import ProfileViewService

router = APIRouter(prefix="/public/profile", tags=["public"])


class PublicProfileSummary(BaseModel):
    full_name: str | None
    headline: str | None
    location: str | None
    avatar_url: str | None
    profile_slug: str | None


async def _get_user_by_slug(slug: str, session: AsyncSession) -> User:
    stmt = select(User).where(
        User.profile_slug == slug,
        User.deleted_at.is_(None),
    )
    user = (await session.execute(stmt)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return user


@router.get("/{slug}", response_model=PublicProfileSummary)
async def get_public_profile_summary(
    slug: str,
    session: AsyncSession = Depends(get_session),
    users: UserService = Depends(get_user_service),
) -> PublicProfileSummary:
    """Return display fields for a public profile slug — no auth required."""
    user = await _get_user_by_slug(slug, session)
    pub = await users.get_public_profile(user.id)
    return PublicProfileSummary(
        full_name=pub.full_name,
        headline=pub.headline,
        location=pub.location,
        avatar_url=pub.avatar_url,
        profile_slug=pub.profile_slug,
    )


@router.post("/{slug}/view", status_code=status.HTTP_204_NO_CONTENT)
async def record_profile_view(
    slug: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    view_svc: ProfileViewService = Depends(get_profile_view_service),
    maybe_user: User | None = Depends(get_optional_current_user),
) -> None:
    """Record a profile view — called by the frontend when a public profile page loads."""
    profile_user = await _get_user_by_slug(slug, session)
    viewer_ip = request.client.host if request.client else "unknown"
    viewer_user_id = maybe_user.id if maybe_user and maybe_user.id != profile_user.id else None
    await view_svc.record_view(
        profile_user_id=profile_user.id,
        viewer_ip=viewer_ip,
        viewer_user_id=viewer_user_id,
    )


@router.get("/{slug}/trust-score", response_model=TrustScoreResponse)
async def get_public_trust_score(
    slug: str,
    session: AsyncSession = Depends(get_session),
    service: TrustScoreService = Depends(get_trust_score_service),
) -> TrustScoreResponse:
    """Return the trust score for a public profile slug — no auth required."""
    user = await _get_user_by_slug(slug, session)
    return await service.calculate_trust_score(user.id)
