"""Public website contact-form endpoint."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.rate_limit import _check_rate
from app.config import Settings, get_settings
from app.db.session import get_session
from app.exceptions import RateLimitError
from app.infrastructure.redis.deps import get_redis
from app.schemas.public_contact import PublicContactAcceptedResponse, PublicContactRequest
from app.services.email_delivery_service import EmailDeliveryService
from app.services.public_contact_service import PublicContactService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public", tags=["public"])


async def get_public_contact_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PublicContactService:
    return PublicContactService(EmailDeliveryService(session, settings), settings)


async def public_contact_rate_limit(
    request: Request,
    redis: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    ip = request.client.host if request.client else "unknown"
    try:
        await _check_rate(
            redis,
            f"rate:public_contact:{ip}",
            window_seconds=settings.contact_rate_limit_window_seconds,
            max_requests=settings.contact_rate_limit_max_requests,
        )
    except RateLimitError:
        logger.warning(
            "public_contact_rate_limited",
            extra={
                "event": "public_contact_rate_limited",
                "client_ip_present": request.client is not None,
            },
        )
        raise


@router.post(
    "/contact",
    response_model=PublicContactAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(public_contact_rate_limit)],
)
async def submit_public_contact(
    payload: PublicContactRequest,
    request: Request,
    service: Annotated[PublicContactService, Depends(get_public_contact_service)],
) -> PublicContactAcceptedResponse:
    client_host = request.client.host if request.client else None
    return await service.submit(
        payload,
        request_id=getattr(request.state, "request_id", "unknown"),
        client_host=client_host,
    )
