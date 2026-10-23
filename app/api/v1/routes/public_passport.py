"""Public Trust Passport access by share token."""

from __future__ import annotations

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.api.dependencies.rate_limit import _check_rate
from app.api.dependencies.services import (
    get_passport_share_view_service,
    get_public_passport_service,
)
from app.exceptions import ServiceUnavailableError
from app.infrastructure.redis.deps import get_redis
from app.schemas.public_passport import PublicPassportResponse
from app.services.passport_share_view_service import PassportShareViewService
from app.services.public_passport_service import PublicPassportService

router = APIRouter(prefix="/public/passport", tags=["public"])


async def public_passport_pdf_limit(
    token: str,
    request: Request,
    redis: Annotated[Redis, Depends(get_redis)],
) -> None:
    """Bound rendering per caller and share; never retain a raw bearer token."""
    caller = request.client.host if request.client else "unknown"
    try:
        for kind, value, maximum in (("ip", caller, 10), ("share", token, 5)):
            digest = hashlib.sha256(value.encode()).hexdigest()
            await _check_rate(
                redis,
                f"rate:public_passport_pdf:{kind}:{digest}",
                window_seconds=60,
                max_requests=maximum,
            )
    except RedisError:
        raise ServiceUnavailableError("Passport download is temporarily unavailable") from None


@router.get(
    "/{token}/pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
    dependencies=[Depends(public_passport_pdf_limit)],
)
async def download_public_passport(
    token: str,
    svc: Annotated[PublicPassportService, Depends(get_public_passport_service)],
) -> Response:
    content = await svc.get_pdf_by_token(token)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="KairoID-Shared-Passport.pdf"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )


@router.get("/{token}", response_model=PublicPassportResponse)
async def get_public_passport(
    token: str,
    request: Request,
    http_response: Response,
    svc: Annotated[PublicPassportService, Depends(get_public_passport_service)],
    views: Annotated[PassportShareViewService, Depends(get_passport_share_view_service)],
) -> PublicPassportResponse:
    response = await svc.get_by_token(token)
    http_response.headers["Cache-Control"] = "private, no-store"
    http_response.headers["Referrer-Policy"] = "no-referrer"
    if response.profile.avatar_url and response.profile.avatar_url.startswith(
        "/api/v1/public/passport/"
    ):
        response.profile.avatar_url = str(request.url_for("get_public_passport_photo", token=token))
    viewer_ip = request.client.host if request.client else "unknown"
    await views.record_successful_view(
        share_id=response.share.id,
        viewer_ip=viewer_ip,
        user_agent=request.headers.get("user-agent"),
        referrer=request.headers.get("referer"),
    )
    return response


@router.get("/{token}/photo", name="get_public_passport_photo")
async def get_public_passport_photo(
    token: str,
    svc: Annotated[PublicPassportService, Depends(get_public_passport_service)],
) -> Response:
    content, content_type = await svc.get_photo_by_token(token)
    return Response(
        content=content,
        media_type=content_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )
