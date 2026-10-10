"""Candidate-owned permanent-address operations and explicit reviewer decision."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser, get_current_user, require_permission
from app.config import Settings, get_settings
from app.core.permissions import Permission
from app.db.session import get_session
from app.exceptions import ForbiddenError
from app.schemas.permanent_address import (
    AddressEvidenceInput,
    AddressReviewInput,
    LocationCancelInput,
    LocationChallenge,
    LocationCompleteInput,
    LocationStartInput,
    PermanentAddressInput,
    PermanentAddressState,
)
from app.services.permanent_address_service import PermanentAddressService


def private_response(response: Response):
    response.headers["Cache-Control"] = "no-store, private, max-age=0"


router = APIRouter(
    prefix="/permanent-address",
    tags=["permanent-address"],
    dependencies=[Depends(private_response)],
)


def service(
    db: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return PermanentAddressService(db, settings)


def candidate(current: Annotated[CurrentUser, Depends(get_current_user)]):
    if current.role != "user":
        raise ForbiddenError("Candidate access required")
    return current


Candidate = Annotated[CurrentUser, Depends(candidate)]
Service = Annotated[PermanentAddressService, Depends(service)]
Reviewer = Annotated[CurrentUser, Depends(require_permission(Permission.REVIEW_VERIFICATION))]


@router.get("", response_model=PermanentAddressState)
async def state(current: Candidate, svc: Service):
    return await svc.state(current.id)


@router.put("", response_model=PermanentAddressState)
async def address(payload: PermanentAddressInput, current: Candidate, svc: Service):
    return await svc.save_address(current.id, payload)


@router.post("/evidence", response_model=PermanentAddressState)
async def evidence(payload: AddressEvidenceInput, current: Candidate, svc: Service):
    return await svc.attach_evidence(current.id, payload)


@router.get("/evidence")
async def available_evidence(current: Candidate, svc: Service):
    return await svc.available_evidence(current.id)


@router.get("/reviews")
async def review_queue(reviewer: Reviewer, svc: Service):
    return await svc.review_queue(reviewer.id)


@router.get("/reviews/{version_id}")
async def review_detail(version_id: UUID, reviewer: Reviewer, svc: Service):
    return await svc.review_detail(reviewer.id, version_id)


@router.get("/reviews/{version_id}/content")
async def review_content(version_id: UUID, reviewer: Reviewer, svc: Service):
    chunks, headers, content_type = await svc.review_detail(reviewer.id, version_id, content=True)
    return StreamingResponse(chunks, media_type=content_type, headers=headers)


@router.post("/sessions", response_model=LocationChallenge)
async def start(payload: LocationStartInput, current: Candidate, svc: Service):
    return await svc.start(current.id, payload.address_version_id)


@router.post("/sessions/{session_id}/complete", response_model=PermanentAddressState)
async def complete(
    session_id: UUID, payload: LocationCompleteInput, current: Candidate, svc: Service
):
    return await svc.finish(current.id, session_id, payload)


@router.post("/sessions/{session_id}/cancel", response_model=PermanentAddressState)
async def cancel(session_id: UUID, payload: LocationCancelInput, current: Candidate, svc: Service):
    return await svc.finish(current.id, session_id, payload, cancel=True)


@router.post("/{version_id}/review")
async def review(version_id: UUID, payload: AddressReviewInput, svc: Service, reviewer: Reviewer):
    return await svc.review(reviewer.id, version_id, payload)
