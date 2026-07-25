"""Organization People Registry routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_organization_person_service
from app.schemas.organization_person import (
    OrganizationPeopleListQueryParams,
    OrganizationPeopleListResponse,
    OrganizationPersonDetailResponse,
    OrganizationPersonNoteRequest,
    OrganizationPersonNoteResponse,
)
from app.services.organization_person_service import OrganizationPersonService

router = APIRouter(prefix="/organizations/{org_public_id}/people", tags=["organization-people"])


@router.get("", response_model=OrganizationPeopleListResponse)
async def list_organization_people(
    org_public_id: UUID,
    params: Annotated[OrganizationPeopleListQueryParams, Depends()],
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[OrganizationPersonService, Depends(get_organization_person_service)],
) -> OrganizationPeopleListResponse:
    return await svc.list_for_organization(current.id, org_public_id, params)


@router.get("/{person_public_id}", response_model=OrganizationPersonDetailResponse)
async def get_organization_person(
    org_public_id: UUID,
    person_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[OrganizationPersonService, Depends(get_organization_person_service)],
) -> OrganizationPersonDetailResponse:
    return await svc.get_detail(current.id, org_public_id, person_public_id)


@router.post("/{person_public_id}/notes", response_model=OrganizationPersonNoteResponse, status_code=status.HTTP_201_CREATED)
async def add_organization_person_note(
    org_public_id: UUID,
    person_public_id: UUID,
    payload: OrganizationPersonNoteRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[OrganizationPersonService, Depends(get_organization_person_service)],
) -> OrganizationPersonNoteResponse:
    return await svc.add_note(current.id, org_public_id, person_public_id, payload)


@router.patch("/{person_public_id}/notes/{note_public_id}", response_model=OrganizationPersonNoteResponse)
async def update_organization_person_note(
    org_public_id: UUID,
    person_public_id: UUID,
    note_public_id: UUID,
    payload: OrganizationPersonNoteRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[OrganizationPersonService, Depends(get_organization_person_service)],
) -> OrganizationPersonNoteResponse:
    return await svc.update_note(current.id, org_public_id, person_public_id, note_public_id, payload)


@router.delete("/{person_public_id}/notes/{note_public_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization_person_note(
    org_public_id: UUID,
    person_public_id: UUID,
    note_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[OrganizationPersonService, Depends(get_organization_person_service)],
) -> Response:
    await svc.delete_note(current.id, org_public_id, person_public_id, note_public_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
