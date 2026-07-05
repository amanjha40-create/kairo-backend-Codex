"""Operational health endpoints — separate liveness from readiness."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.health import ping_database
from app.db.session import get_session
from app.infrastructure.redis import ping_redis

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.app_env,
        "version": settings.app_version,
        "timestamp": datetime.now(tz=UTC).isoformat(),
    }


@router.get("/ready")
async def ready(session: AsyncSession = Depends(get_session)) -> dict:
    settings = get_settings()
    try:
        await ping_database(session)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc

    redis_ok = await ping_redis()
    if settings.redis_required_for_ready and not redis_ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="redis unavailable",
        )

    return {
        "status": "ok",
        "database": "reachable",
        "redis": "reachable" if redis_ok else "unreachable",
        "timestamp": datetime.now(tz=UTC).isoformat(),
    }
