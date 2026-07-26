"""Institution-only People and Alumni routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_institution_people_service
from app.schemas.institution_people import (
    InstitutionCredentialResponse,
    InstitutionPeopleListQuery,
    InstitutionPeopleListResponse,
    InstitutionPersonDetailResponse,
    InstitutionVerificationEvent,
)
from app.services.institution_people_service import InstitutionPeopleService

router = APIRouter(
    prefix="/organizations/{org_public_id}/institution/people", tags=["institution-people"]
)


@router.get("", response_model=InstitutionPeopleListResponse)
async def list_institution_people(
    org_public_id: UUID,
    params: Annotated[InstitutionPeopleListQuery, Depends()],
    current: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[InstitutionPeopleService, Depends(get_institution_people_service)],
) -> InstitutionPeopleListResponse:
    return await service.list_people(current.id, org_public_id, params)


@router.get("/{person_public_id}", response_model=InstitutionPersonDetailResponse)
async def get_institution_person(
    org_public_id: UUID,
    person_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[InstitutionPeopleService, Depends(get_institution_people_service)],
) -> InstitutionPersonDetailResponse:
    return await service.get_person(current.id, org_public_id, person_public_id)


@router.get(
    "/{person_public_id}/verification-history", response_model=list[InstitutionVerificationEvent]
)
async def get_institution_verification_history(
    org_public_id: UUID,
    person_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[InstitutionPeopleService, Depends(get_institution_people_service)],
) -> list[InstitutionVerificationEvent]:
    return await service.verification_history(current.id, org_public_id, person_public_id)


@router.get("/{person_public_id}/credentials", response_model=list[InstitutionCredentialResponse])
async def list_institution_credentials(
    org_public_id: UUID,
    person_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[InstitutionPeopleService, Depends(get_institution_people_service)],
) -> list[InstitutionCredentialResponse]:
    return await service.credentials(current.id, org_public_id, person_public_id)


@router.get(
    "/{person_public_id}/credentials/{credential_public_id}",
    response_model=InstitutionCredentialResponse,
)
async def get_institution_credential(
    org_public_id: UUID,
    person_public_id: UUID,
    credential_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[InstitutionPeopleService, Depends(get_institution_people_service)],
) -> InstitutionCredentialResponse:
    return await service.credential(
        current.id, org_public_id, person_public_id, credential_public_id
    )
