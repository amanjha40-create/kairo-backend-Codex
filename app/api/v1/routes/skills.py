"""Candidate-declared skill routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_skill_service
from app.schemas.skill import SkillCreateRequest, SkillResponse
from app.services.skill_service import SkillService

router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("", response_model=list[SkillResponse])
async def list_skills(current: Annotated[CurrentUser, Depends(get_current_user)], svc: Annotated[SkillService, Depends(get_skill_service)]) -> list[SkillResponse]:
    return [SkillResponse.model_validate(item) for item in await svc.list_for_user(current.id)]


@router.post("", response_model=SkillResponse, status_code=status.HTTP_201_CREATED)
async def create_skill(payload: SkillCreateRequest, current: Annotated[CurrentUser, Depends(get_current_user)], svc: Annotated[SkillService, Depends(get_skill_service)]) -> SkillResponse:
    return SkillResponse.model_validate(await svc.create(current.id, payload))


@router.delete("/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(skill_id: UUID, current: Annotated[CurrentUser, Depends(get_current_user)], svc: Annotated[SkillService, Depends(get_skill_service)]) -> None:
    await svc.delete(current.id, skill_id)
