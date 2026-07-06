"""Internship routes — CRUD for internship records."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_internship_service, get_secondary_doc_service
from app.schemas.internship import (
    InternshipCreateRequest,
    InternshipResponse,
    InternshipUpdateRequest,
)
from app.schemas.pagination import Page, PageParams
from app.services.internship_service import InternshipService
from app.services.secondary_doc_service import (
    DocCompleteRequest,
    DocResponse,
    DocUploadIntentRequest,
    DocUploadIntentResponse,
    SecondaryDocService,
)

router = APIRouter(prefix="/internships", tags=["internships"])


@router.get("", response_model=Page[InternshipResponse])
async def list_internships(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    page: Annotated[PageParams, Depends()],
    svc: Annotated[InternshipService, Depends(get_internship_service)],
) -> Page[InternshipResponse]:
    items, total = await svc.list_for_user(current.id, offset=page.offset, limit=page.limit)
    return Page[InternshipResponse].create(
        items=[InternshipResponse.model_validate(i) for i in items],
        total=total,
        params=page,
    )


@router.post("", response_model=InternshipResponse, status_code=status.HTTP_201_CREATED)
async def create_internship(
    payload: InternshipCreateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[InternshipService, Depends(get_internship_service)],
) -> InternshipResponse:
    item = await svc.create(current.id, payload)
    return InternshipResponse.model_validate(item)


@router.get("/{item_id}", response_model=InternshipResponse)
async def get_internship(
    item_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[InternshipService, Depends(get_internship_service)],
) -> InternshipResponse:
    item = await svc.get_owned(current.id, item_id)
    return InternshipResponse.model_validate(item)


@router.patch("/{item_id}", response_model=InternshipResponse)
async def update_internship(
    item_id: UUID,
    payload: InternshipUpdateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[InternshipService, Depends(get_internship_service)],
) -> InternshipResponse:
    item = await svc.update(current.id, item_id, payload)
    return InternshipResponse.model_validate(item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_internship(
    item_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[InternshipService, Depends(get_internship_service)],
) -> None:
    await svc.delete(current.id, item_id)


# ---- Document sub-resources ----

@router.post(
    "/{item_id}/documents/upload-intent",
    response_model=DocUploadIntentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_internship_doc_upload_intent(
    item_id: UUID,
    payload: DocUploadIntentRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    doc_svc: Annotated[SecondaryDocService, Depends(get_secondary_doc_service)],
) -> DocUploadIntentResponse:
    return await doc_svc.create_internship_upload_intent(current.id, item_id, payload)


@router.post(
    "/{item_id}/documents/{doc_id}/complete-upload",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def complete_internship_doc_upload(
    item_id: UUID,
    doc_id: UUID,
    payload: DocCompleteRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    doc_svc: Annotated[SecondaryDocService, Depends(get_secondary_doc_service)],
) -> None:
    await doc_svc.complete_internship_upload(current.id, item_id, doc_id, payload)


@router.get("/{item_id}/documents", response_model=list[DocResponse])
async def list_internship_documents(
    item_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    doc_svc: Annotated[SecondaryDocService, Depends(get_secondary_doc_service)],
) -> list[DocResponse]:
    return await doc_svc.list_internship_documents(current.id, item_id)


@router.delete("/{item_id}/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_internship_document(
    item_id: UUID,
    doc_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    doc_svc: Annotated[SecondaryDocService, Depends(get_secondary_doc_service)],
) -> None:
    await doc_svc.delete_internship_document(current.id, item_id, doc_id)
