"""Candidate project routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_project_service
from app.schemas.project import ProjectCreateRequest, ProjectResponse, ProjectUpdateRequest
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectResponse])
async def list_projects(current: Annotated[CurrentUser, Depends(get_current_user)], svc: Annotated[ProjectService, Depends(get_project_service)]) -> list[ProjectResponse]:
    return [ProjectResponse.model_validate(item) for item in await svc.list_for_user(current.id)]


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(payload: ProjectCreateRequest, current: Annotated[CurrentUser, Depends(get_current_user)], svc: Annotated[ProjectService, Depends(get_project_service)]) -> ProjectResponse:
    return ProjectResponse.model_validate(await svc.create(current.id, payload))


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: UUID, current: Annotated[CurrentUser, Depends(get_current_user)], svc: Annotated[ProjectService, Depends(get_project_service)]) -> ProjectResponse:
    return ProjectResponse.model_validate(await svc.get_owned(current.id, project_id))


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: UUID, payload: ProjectUpdateRequest, current: Annotated[CurrentUser, Depends(get_current_user)], svc: Annotated[ProjectService, Depends(get_project_service)]) -> ProjectResponse:
    return ProjectResponse.model_validate(await svc.update(current.id, project_id, payload))


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: UUID, current: Annotated[CurrentUser, Depends(get_current_user)], svc: Annotated[ProjectService, Depends(get_project_service)]) -> None:
    await svc.delete(current.id, project_id)
