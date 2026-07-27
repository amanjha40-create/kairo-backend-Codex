"""Admin overview endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.dependencies.services import get_admin_overview_service
from app.auth.deps import CurrentUser, require_permission
from app.core.permissions import Permission
from app.schemas.admin_overview import AdminOverviewResponse
from app.services.admin_overview_service import AdminOverviewService

router = APIRouter(prefix="/admin", tags=["admin-overview"])


@router.get("/overview", response_model=AdminOverviewResponse)
async def read_admin_overview(
    _: Annotated[CurrentUser, Depends(require_permission(Permission.ACCESS_ADMIN_PORTAL))],
    __: Annotated[CurrentUser, Depends(require_permission(Permission.VIEW_ALL_CASES))],
    service: Annotated[AdminOverviewService, Depends(get_admin_overview_service)],
    recent_window_days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> AdminOverviewResponse:
    return await service.get_overview(recent_window_days=recent_window_days)
