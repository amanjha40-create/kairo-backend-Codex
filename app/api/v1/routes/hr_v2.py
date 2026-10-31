"""Additive HR Workspace V2 organization contracts."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_hr_v2_service
from app.schemas.hr_v2 import (
    EmployeeLifecycleResponse,
    EmployeeLifecycleUpdateRequest,
    FormerEmployeeCorrectionCreateRequest,
    FormerEmployeeCorrectionDecisionRequest,
    FormerEmployeeCorrectionListQuery,
    FormerEmployeeCorrectionPage,
    FormerEmployeeCorrectionResponse,
    HiringRoleDecisionRequest,
    OrganizationJobRoleCreateRequest,
    OrganizationJobRoleResponse,
    OrganizationJobRoleUpdateRequest,
    OrganizationLogoConfirmRequest,
    OrganizationLogoResponse,
    OrganizationLogoUploadIntentRequest,
    OrganizationLogoUploadIntentResponse,
    OrganizationRoleAssignmentRequest,
    OrganizationRoleAssignmentResponse,
    OrganizationVerificationPreferencesResponse,
    OrganizationVerificationPreferencesUpdateRequest,
    VerificationReportResponse,
)
from app.services.hr_v2_service import HRV2Service

router = APIRouter(prefix="/organizations/{org_public_id}", tags=["hr-v2"])


@router.patch("/people/{person_public_id}/lifecycle", response_model=EmployeeLifecycleResponse)
async def update_employee_lifecycle(
    org_public_id: UUID,
    person_public_id: UUID,
    payload: EmployeeLifecycleUpdateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[HRV2Service, Depends(get_hr_v2_service)],
) -> EmployeeLifecycleResponse:
    return await svc.update_employee_lifecycle(current.id, org_public_id, person_public_id, payload)


@router.patch(
    "/people/{person_public_id}/employment-profile",
    response_model=OrganizationRoleAssignmentResponse,
)
async def assign_employee_role(
    org_public_id: UUID,
    person_public_id: UUID,
    payload: OrganizationRoleAssignmentRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[HRV2Service, Depends(get_hr_v2_service)],
) -> OrganizationRoleAssignmentResponse:
    return await svc.assign_role(current.id, org_public_id, person_public_id, payload)


@router.get("/job-roles", response_model=list[OrganizationJobRoleResponse])
async def list_job_roles(
    org_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[HRV2Service, Depends(get_hr_v2_service)],
) -> list[OrganizationJobRoleResponse]:
    return await svc.list_roles(current.id, org_public_id)


@router.post(
    "/job-roles",
    response_model=OrganizationJobRoleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_job_role(
    org_public_id: UUID,
    payload: OrganizationJobRoleCreateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[HRV2Service, Depends(get_hr_v2_service)],
) -> OrganizationJobRoleResponse:
    return await svc.create_role(current.id, org_public_id, payload)


@router.patch("/job-roles/{role_public_id}", response_model=OrganizationJobRoleResponse)
async def update_job_role(
    org_public_id: UUID,
    role_public_id: UUID,
    payload: OrganizationJobRoleUpdateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[HRV2Service, Depends(get_hr_v2_service)],
) -> OrganizationJobRoleResponse:
    return await svc.update_role(current.id, org_public_id, role_public_id, payload)


@router.post("/job-roles/{role_public_id}/approve", response_model=OrganizationJobRoleResponse)
async def approve_job_role(
    org_public_id: UUID,
    role_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[HRV2Service, Depends(get_hr_v2_service)],
) -> OrganizationJobRoleResponse:
    return await svc.approve_role(current.id, org_public_id, role_public_id)


@router.post("/job-roles/{role_public_id}/reject", response_model=OrganizationJobRoleResponse)
async def reject_job_role(
    org_public_id: UUID,
    role_public_id: UUID,
    payload: HiringRoleDecisionRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[HRV2Service, Depends(get_hr_v2_service)],
) -> OrganizationJobRoleResponse:
    return await svc.reject_role(current.id, org_public_id, role_public_id, payload)


@router.delete("/job-roles/{role_public_id}", response_model=OrganizationJobRoleResponse)
async def deactivate_job_role(
    org_public_id: UUID,
    role_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[HRV2Service, Depends(get_hr_v2_service)],
) -> OrganizationJobRoleResponse:
    return await svc.deactivate_role(current.id, org_public_id, role_public_id)


@router.post(
    "/people/{person_public_id}/corrections",
    response_model=FormerEmployeeCorrectionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_former_employee_correction(
    org_public_id: UUID,
    person_public_id: UUID,
    payload: FormerEmployeeCorrectionCreateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[HRV2Service, Depends(get_hr_v2_service)],
) -> FormerEmployeeCorrectionResponse:
    return await svc.create_former_employee_correction(
        current.id, org_public_id, person_public_id, payload
    )


@router.get("/people/corrections", response_model=FormerEmployeeCorrectionPage)
async def list_former_employee_corrections(
    org_public_id: UUID,
    params: Annotated[FormerEmployeeCorrectionListQuery, Depends()],
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[HRV2Service, Depends(get_hr_v2_service)],
) -> FormerEmployeeCorrectionPage:
    return await svc.list_former_employee_corrections(current.id, org_public_id, params)


@router.post(
    "/people/corrections/{correction_public_id}/approve",
    response_model=FormerEmployeeCorrectionResponse,
)
async def approve_former_employee_correction(
    org_public_id: UUID,
    correction_public_id: UUID,
    payload: FormerEmployeeCorrectionDecisionRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[HRV2Service, Depends(get_hr_v2_service)],
) -> FormerEmployeeCorrectionResponse:
    return await svc.approve_former_employee_correction(
        current.id, org_public_id, correction_public_id, payload
    )


@router.post(
    "/people/corrections/{correction_public_id}/reject",
    response_model=FormerEmployeeCorrectionResponse,
)
async def reject_former_employee_correction(
    org_public_id: UUID,
    correction_public_id: UUID,
    payload: FormerEmployeeCorrectionDecisionRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[HRV2Service, Depends(get_hr_v2_service)],
) -> FormerEmployeeCorrectionResponse:
    return await svc.reject_former_employee_correction(
        current.id, org_public_id, correction_public_id, payload
    )


@router.post(
    "/logo/upload-intents",
    response_model=OrganizationLogoUploadIntentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_logo_upload_intent(
    org_public_id: UUID,
    payload: OrganizationLogoUploadIntentRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[HRV2Service, Depends(get_hr_v2_service)],
) -> OrganizationLogoUploadIntentResponse:
    return await svc.create_logo_upload_intent(current.id, org_public_id, payload)


@router.post("/logo/confirm", response_model=OrganizationLogoResponse)
async def confirm_logo(
    org_public_id: UUID,
    payload: OrganizationLogoConfirmRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[HRV2Service, Depends(get_hr_v2_service)],
) -> OrganizationLogoResponse:
    return await svc.confirm_logo(current.id, org_public_id, payload)


@router.get("/logo", response_model=OrganizationLogoResponse)
async def get_logo(
    org_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[HRV2Service, Depends(get_hr_v2_service)],
) -> OrganizationLogoResponse:
    return await svc.get_logo(current.id, org_public_id)


@router.delete("/logo", response_model=OrganizationLogoResponse)
async def remove_logo(
    org_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[HRV2Service, Depends(get_hr_v2_service)],
) -> OrganizationLogoResponse:
    return await svc.remove_logo(current.id, org_public_id)


@router.get(
    "/verification-preferences",
    response_model=OrganizationVerificationPreferencesResponse,
)
async def get_verification_preferences(
    org_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[HRV2Service, Depends(get_hr_v2_service)],
) -> OrganizationVerificationPreferencesResponse:
    return await svc.get_preferences(current.id, org_public_id)


@router.put(
    "/verification-preferences",
    response_model=OrganizationVerificationPreferencesResponse,
)
async def update_verification_preferences(
    org_public_id: UUID,
    payload: OrganizationVerificationPreferencesUpdateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[HRV2Service, Depends(get_hr_v2_service)],
) -> OrganizationVerificationPreferencesResponse:
    return await svc.update_preferences(current.id, org_public_id, payload)


@router.get(
    "/people/{person_public_id}/verification-report",
    response_model=VerificationReportResponse,
)
async def get_verification_report(
    org_public_id: UUID,
    person_public_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[HRV2Service, Depends(get_hr_v2_service)],
) -> VerificationReportResponse:
    return await svc.get_verification_report(current.id, org_public_id, person_public_id)
