"""Candidate-owned permanent-address operations and explicit reviewer decision."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser, get_current_user, require_permission
from app.config import Settings, get_settings
from app.core.permissions import Permission
from app.db.session import engine, get_session
from app.exceptions import ForbiddenError
from app.schemas.permanent_address import (
    AddressDocumentCompleteInput,
    AddressDocumentReviewInput,
    AddressDocumentState,
    AddressDocumentSubmitInput,
    AddressDocumentUploadInput,
    AddressDocumentUploadResponse,
    AddressEvidenceInput,
    AddressReviewInput,
    LocationCancelInput,
    LocationChallenge,
    LocationCompleteInput,
    LocationReviewResolution,
    LocationReviewResolutionInput,
    LocationStartInput,
    ManualLocationDetail,
    ManualLocationQueue,
    ManualLocationResolution,
    ManualLocationReviewInput,
    PermanentAddressInput,
    PermanentAddressState,
)
from app.schemas.permanent_address_admin import AdminAddressDetail, AdminAddressDiscovery
from app.services.permanent_address_admin import PermanentAddressAdminRead
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


async def admin_read_service(settings: Annotated[Settings, Depends(get_settings)]):
    # One consistent, database-enforced read-only snapshot, separate from auth.
    async with engine.connect() as connection:
        await connection.execution_options(
            isolation_level="REPEATABLE READ", postgresql_readonly=True
        )
        async with AsyncSession(bind=connection, autoflush=False) as db:
            yield PermanentAddressService(db, settings)


AdminReadService = Annotated[PermanentAddressService, Depends(admin_read_service)]


@router.get("/admin/reviews", response_model=AdminAddressDiscovery)
async def admin_address_discovery(
    reviewer: Reviewer,
    svc: AdminReadService,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    candidate_id: UUID | None = None,
):
    return await PermanentAddressAdminRead(svc).discover(
        reviewer.id, limit=limit, offset=offset, candidate_id=candidate_id
    )


@router.get("/admin/candidates/{candidate_id}", response_model=AdminAddressDetail)
async def admin_address_detail(
    candidate_id: UUID,
    reviewer: Reviewer,
    svc: AdminReadService,
    address_version_id: UUID | None = None,
):
    return await PermanentAddressAdminRead(svc).detail(
        reviewer.id, candidate_id, address_version_id=address_version_id
    )


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


@router.get("/document-types")
async def document_types(current: Candidate, svc: Service):
    return svc.document_types()


@router.get("/{version_id}/document", response_model=AddressDocumentState)
async def document_state(version_id: UUID, current: Candidate, svc: Service):
    return await svc.document_state(current.id, version_id)


@router.post("/documents/upload-intent", response_model=AddressDocumentUploadResponse)
async def document_upload(payload: AddressDocumentUploadInput, current: Candidate, svc: Service):
    return await svc.upload_address_document(current.id, payload)


@router.post("/documents/{document_id}/complete-upload", response_model=AddressDocumentState)
async def document_complete(document_id: UUID, payload: AddressDocumentCompleteInput, current: Candidate, svc: Service):
    return await svc.complete_address_document(current.id, document_id, payload)


@router.post("/documents/submit", response_model=PermanentAddressState)
async def document_submit(payload: AddressDocumentSubmitInput, current: Candidate, svc: Service):
    return await svc.submit_address_document(current.id, payload)


@router.get("/document-reviews/{version_id}")
async def document_review_detail(version_id: UUID, reviewer: Reviewer, svc: Service):
    return await svc.document_review_projection(reviewer.id, version_id)


@router.post("/document-reviews/{version_id}/decision")
async def document_decision(version_id: UUID, payload: AddressDocumentReviewInput, reviewer: Reviewer, svc: Service):
    return await svc.decide_address_document(reviewer.id, version_id, payload)


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


@router.post(
    "/reviews/{version_id}/sessions/{session_id}/resolution",
    response_model=LocationReviewResolution,
)
async def resolve_location_review(
    version_id: UUID,
    session_id: UUID,
    payload: LocationReviewResolutionInput,
    reviewer: Reviewer,
    svc: Service,
):
    return await svc.resolve_location_review(reviewer.id, version_id, session_id, payload)


@router.get("/location-reviews", response_model=ManualLocationQueue)
async def manual_location_queue(reviewer: Reviewer, svc: Service):
    return await svc.manual_location_queue(reviewer.id)


@router.get(
    "/location-reviews/{version_id}/sessions/{session_id}", response_model=ManualLocationDetail
)
async def manual_location_detail(
    version_id: UUID, session_id: UUID, reviewer: Reviewer, svc: Service
):
    return await svc.manual_location_detail(reviewer.id, version_id, session_id)


@router.post(
    "/location-reviews/{version_id}/sessions/{session_id}/resolution",
    response_model=ManualLocationResolution,
)
async def resolve_manual_location(
    version_id: UUID,
    session_id: UUID,
    payload: ManualLocationReviewInput,
    reviewer: Reviewer,
    svc: Service,
):
    return await svc.resolve_manual_location(reviewer.id, version_id, session_id, payload)
