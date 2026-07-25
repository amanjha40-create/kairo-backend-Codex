"""Authenticated account and settings routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.config import Settings, get_settings
from app.schemas.account_settings import (
    AccountSessionResponse,
    AccountSettingsResponse,
    AccountSettingsUpdate,
)
from app.services.account_settings_service import AccountSettingsService
from app.db.session import get_session
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/account", tags=["account"])


def get_account_settings_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AccountSettingsService:
    return AccountSettingsService(session, settings)


@router.get("/settings", response_model=AccountSettingsResponse)
async def get_account_settings(
    current: CurrentUser = Depends(get_current_user),
    service: AccountSettingsService = Depends(get_account_settings_service),
) -> AccountSettingsResponse:
    return await service.get(current.id)


@router.patch("/settings", response_model=AccountSettingsResponse)
async def update_account_settings(
    payload: AccountSettingsUpdate,
    current: CurrentUser = Depends(get_current_user),
    service: AccountSettingsService = Depends(get_account_settings_service),
) -> AccountSettingsResponse:
    return await service.update(current.id, payload)


@router.get("/sessions", response_model=list[AccountSessionResponse])
async def list_account_sessions(
    current: CurrentUser = Depends(get_current_user),
    service: AccountSettingsService = Depends(get_account_settings_service),
) -> list[AccountSessionResponse]:
    return await service.list_sessions(current.id)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_account_session(
    session_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: AccountSettingsService = Depends(get_account_settings_service),
) -> None:
    await service.revoke_session(current.id, session_id)


@router.delete("/sessions", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_all_account_sessions(
    current: CurrentUser = Depends(get_current_user),
    service: AccountSettingsService = Depends(get_account_settings_service),
) -> None:
    await service.revoke_all_sessions(current.id)
