from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_resume_service
from app.schemas.pagination import Page, PageParams
from app.resumes.schemas import (
    ResumeCompleteUploadRequest, ResumeParsedResultResponse, ResumeProcessResponse,
    ResumeResponse, ResumeUploadIntentRequest, ResumeUploadIntentResponse,
)
from app.services.resume_service import ResumeService

router = APIRouter(prefix="/resumes", tags=["resumes"])


@router.post("/upload-intent", response_model=ResumeUploadIntentResponse, status_code=status.HTTP_201_CREATED)
async def create_resume_upload_intent(payload: ResumeUploadIntentRequest, current: Annotated[CurrentUser, Depends(get_current_user)], svc: Annotated[ResumeService, Depends(get_resume_service)]) -> ResumeUploadIntentResponse:
    return await svc.create_upload_intent(current.id, payload)


@router.get("", response_model=Page[ResumeResponse])
async def list_resumes(current: Annotated[CurrentUser, Depends(get_current_user)], page: Annotated[PageParams, Depends()], svc: Annotated[ResumeService, Depends(get_resume_service)]) -> Page[ResumeResponse]:
    return await svc.list(current.id, page.offset or 0, page.limit or 20)


@router.get("/{resume_id}", response_model=ResumeResponse)
async def get_resume(resume_id: UUID, current: Annotated[CurrentUser, Depends(get_current_user)], svc: Annotated[ResumeService, Depends(get_resume_service)]) -> ResumeResponse:
    return await svc.get(current.id, resume_id)


@router.post("/{resume_id}/complete-upload", response_model=ResumeResponse)
async def complete_resume_upload(resume_id: UUID, payload: ResumeCompleteUploadRequest, current: Annotated[CurrentUser, Depends(get_current_user)], svc: Annotated[ResumeService, Depends(get_resume_service)]) -> ResumeResponse:
    return await svc.complete_upload(current.id, resume_id, payload)


@router.post("/{resume_id}/process", response_model=ResumeProcessResponse)
async def process_resume(resume_id: UUID, current: Annotated[CurrentUser, Depends(get_current_user)], svc: Annotated[ResumeService, Depends(get_resume_service)]) -> ResumeProcessResponse:
    return await svc.process(current.id, resume_id)


@router.get("/{resume_id}/status", response_model=ResumeProcessResponse)
async def resume_status(resume_id: UUID, current: Annotated[CurrentUser, Depends(get_current_user)], svc: Annotated[ResumeService, Depends(get_resume_service)]) -> ResumeProcessResponse:
    return await svc.status(current.id, resume_id)


@router.get("/{resume_id}/parsed-result", response_model=ResumeParsedResultResponse)
async def parsed_resume_result(resume_id: UUID, current: Annotated[CurrentUser, Depends(get_current_user)], svc: Annotated[ResumeService, Depends(get_resume_service)]) -> ResumeParsedResultResponse:
    return await svc.parsed_result(current.id, resume_id)


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume(resume_id: UUID, current: Annotated[CurrentUser, Depends(get_current_user)], svc: Annotated[ResumeService, Depends(get_resume_service)]) -> None:
    await svc.delete(current.id, resume_id)
