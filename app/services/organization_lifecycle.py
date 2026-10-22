"""Shared capability guard for permanently closed organizations."""

from sqlalchemy import select

from app.exceptions import NotFoundError
from app.models import Organization, VerificationRequest


async def require_organization_open(session, organization_id):
    if organization_id is None:
        return
    row = (
        await session.execute(
            select(Organization.id, Organization.closed_at)
            .where(Organization.id == organization_id)
            .with_for_update()
        )
    ).one_or_none()
    if row is None or row.closed_at is not None:
        raise NotFoundError("Organization unavailable")


async def require_verification_organization_open(session, request_id):
    if request_id is None:
        return
    row = (
        await session.execute(
            select(VerificationRequest.organization_id).where(VerificationRequest.id == request_id)
        )
    ).one_or_none()
    if row is not None:
        await require_organization_open(session, row.organization_id)
