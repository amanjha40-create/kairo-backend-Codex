"""Freelance contract routes — CRUD for freelance/contract work records."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_freelance_contract_service, get_secondary_doc_service
from app.schemas.freelance_contract import (
    FreelanceContractCreateRequest,
    FreelanceContractResponse,
    FreelanceContractUpdateRequest,
)
from app.schemas.pagination import Page, PageParams
from app.services.freelance_contract_service import FreelanceContractService
from app.services.secondary_doc_service import (
    DocCompleteRequest,
    DocResponse,
    DocUploadIntentRequest,
    DocUploadIntentResponse,
    SecondaryDocService,
)

router = APIRouter(prefix="/freelance-contracts", tags=["freelance-contracts"])


@router.get("", response_model=Page[FreelanceContractResponse])
async def list_freelance_contracts(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    page: Annotated[PageParams, Depends()],
    svc: Annotated[FreelanceContractService, Depends(get_freelance_contract_service)],
) -> Page[FreelanceContractResponse]:
    items, total = await svc.list_for_user(current.id, offset=page.offset, limit=page.limit)
    return Page[FreelanceContractResponse].create(
        items=[FreelanceContractResponse.model_validate(i) for i in items],
        total=total,
        params=page,
    )


@router.post("", response_model=FreelanceContractResponse, status_code=status.HTTP_201_CREATED)
async def create_freelance_contract(
    payload: FreelanceContractCreateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[FreelanceContractService, Depends(get_freelance_contract_service)],
) -> FreelanceContractResponse:
    item = await svc.create(current.id, payload)
    return FreelanceContractResponse.model_validate(item)


@router.get("/{item_id}", response_model=FreelanceContractResponse)
async def get_freelance_contract(
    item_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[FreelanceContractService, Depends(get_freelance_contract_service)],
) -> FreelanceContractResponse:
    item = await svc.get_owned(current.id, item_id)
    return FreelanceContractResponse.model_validate(item)


@router.patch("/{item_id}", response_model=FreelanceContractResponse)
async def update_freelance_contract(
    item_id: UUID,
    payload: FreelanceContractUpdateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[FreelanceContractService, Depends(get_freelance_contract_service)],
) -> FreelanceContractResponse:
    item = await svc.update(current.id, item_id, payload)
    return FreelanceContractResponse.model_validate(item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_freelance_contract(
    item_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[FreelanceContractService, Depends(get_freelance_contract_service)],
) -> None:
    await svc.delete(current.id, item_id)


# ---- Document sub-resources ----

@router.post(
    "/{item_id}/documents/upload-intent",
    response_model=DocUploadIntentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_freelance_doc_upload_intent(
    item_id: UUID,
    payload: DocUploadIntentRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    doc_svc: Annotated[SecondaryDocService, Depends(get_secondary_doc_service)],
) -> DocUploadIntentResponse:
    return await doc_svc.create_freelance_upload_intent(current.id, item_id, payload)


@router.post(
    "/{item_id}/documents/{doc_id}/complete-upload",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def complete_freelance_doc_upload(
    item_id: UUID,
    doc_id: UUID,
    payload: DocCompleteRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    doc_svc: Annotated[SecondaryDocService, Depends(get_secondary_doc_service)],
) -> None:
    await doc_svc.complete_freelance_upload(current.id, item_id, doc_id, payload)


@router.get("/{item_id}/documents", response_model=list[DocResponse])
async def list_freelance_documents(
    item_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    doc_svc: Annotated[SecondaryDocService, Depends(get_secondary_doc_service)],
) -> list[DocResponse]:
    return await doc_svc.list_freelance_documents(current.id, item_id)


@router.delete("/{item_id}/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_freelance_document(
    item_id: UUID,
    doc_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    doc_svc: Annotated[SecondaryDocService, Depends(get_secondary_doc_service)],
) -> None:
    await doc_svc.delete_freelance_document(current.id, item_id, doc_id)
