"""Admin communications operational-center routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.dependencies.services import get_admin_communication_service
from app.api.dependencies.verification_admin import require_view_cases
from app.schemas.admin_communication import (
    AdminCommunicationDetailResponse,
    AdminCommunicationListItemResponse,
    AdminCommunicationListParams,
)
from app.schemas.pagination import Page
from app.services.admin_communication_service import AdminCommunicationService

router = APIRouter(prefix="/admin/communications", tags=["admin-communications"])


@router.get("", response_model=Page[AdminCommunicationListItemResponse])
async def list_admin_communications(
    params: Annotated[AdminCommunicationListParams, Depends()],
    _: Annotated[object, Depends(require_view_cases)],
    svc: Annotated[AdminCommunicationService, Depends(get_admin_communication_service)],
) -> Page[AdminCommunicationListItemResponse]:
    return await svc.list_communications(params)


@router.get("/{communication_public_id}", response_model=AdminCommunicationDetailResponse)
async def get_admin_communication(
    communication_public_id: UUID,
    _: Annotated[object, Depends(require_view_cases)],
    svc: Annotated[AdminCommunicationService, Depends(get_admin_communication_service)],
) -> AdminCommunicationDetailResponse:
    return await svc.get_detail(communication_public_id)
