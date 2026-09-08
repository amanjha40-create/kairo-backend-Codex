"""Owner/Admin APIs for roster upload, preview, and mapping."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_organization_roster_import_service
from app.organization_roster_import.constants import MAX_UPLOAD_BYTES
from app.organization_roster_import.enums import OrganizationRosterType
from app.schemas.organization_roster_import import (
    OrganizationRosterPreviewResponse,
    RosterMappingUpdateRequest,
)
from app.services.organization_roster_import_service import OrganizationRosterImportService

router = APIRouter(
    prefix="/organizations/{org_public_id}/roster-imports",
    tags=["organization-roster-imports"],
)


@router.post(
    "", response_model=OrganizationRosterPreviewResponse, status_code=status.HTTP_201_CREATED
)
async def upload_roster_preview(
    org_public_id: UUID,
    roster_type: Annotated[OrganizationRosterType, Form()],
    file: Annotated[UploadFile, File()],
    current: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[
        OrganizationRosterImportService,
        Depends(get_organization_roster_import_service),
    ],
) -> OrganizationRosterPreviewResponse:
    await service.authorize_upload(
        actor_user_id=current.id,
        org_public_id=org_public_id,
    )
    try:
        content = await file.read(MAX_UPLOAD_BYTES + 1)
    finally:
        await file.close()
    return await service.upload_preview(
        actor_user_id=current.id,
        org_public_id=org_public_id,
        roster_type=roster_type,
        filename=file.filename or "",
        content_type=file.content_type,
        content=content,
    )


@router.get("/{import_public_id}", response_model=OrganizationRosterPreviewResponse)
async def get_roster_preview(
    org_public_id: UUID,
    import_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[
        OrganizationRosterImportService,
        Depends(get_organization_roster_import_service),
    ],
) -> OrganizationRosterPreviewResponse:
    return await service.get_preview(
        actor_user_id=current.id,
        org_public_id=org_public_id,
        import_public_id=import_public_id,
    )


@router.patch("/{import_public_id}/mapping", response_model=OrganizationRosterPreviewResponse)
async def update_roster_mapping(
    org_public_id: UUID,
    import_public_id: UUID,
    payload: RosterMappingUpdateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[
        OrganizationRosterImportService,
        Depends(get_organization_roster_import_service),
    ],
) -> OrganizationRosterPreviewResponse:
    return await service.update_mapping(
        actor_user_id=current.id,
        org_public_id=org_public_id,
        import_public_id=import_public_id,
        payload=payload,
    )
