"""Admin-only organization search and Company 360 routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status

from app.api.dependencies.services import (
    get_admin_organization_service,
    get_hr_v2_service,
    get_organization_roster_import_service,
    get_organization_service,
)
from app.api.dependencies.verification_admin import (
    CurrentUser,
    require_user_manager,
    require_user_reader,
)
from app.organization_roster_import.constants import MAX_UPLOAD_BYTES
from app.organization_roster_import.enums import OrganizationRosterType
from app.organization_roster_import.templates import build_roster_template
from app.schemas.admin_organization import (
    AdminOrganizationActivityPage,
    AdminOrganizationCompanyRecordConnectRequest,
    AdminOrganizationCompanyRecordCreateRequest,
    AdminOrganizationCompanyRecordResponse,
    AdminOrganizationDetailResponse,
    AdminOrganizationListParams,
    AdminOrganizationOverviewResponse,
    AdminOrganizationPage,
    AdminOrganizationPeoplePage,
    AdminOrganizationTeamPage,
    AdminOrganizationVerificationListParams,
    AdminOrganizationVerificationPage,
)
from app.schemas.hr_v2 import (
    OrganizationJobRoleCreateRequest,
    OrganizationJobRoleResponse,
    OrganizationJobRoleUpdateRequest,
    VerificationReportResponse,
)
from app.schemas.organization import (
    OrganizationInvitationCreateRequest,
    OrganizationInvitationResponse,
)
from app.schemas.organization_roster_import import (
    OrganizationRosterPreviewResponse,
    RosterImportListQueryParams,
    RosterImportListResponse,
)
from app.schemas.pagination import ListQueryParams
from app.services.admin_organization_service import AdminOrganizationService
from app.services.hr_v2_service import HRV2Service
from app.services.organization_roster_import_service import OrganizationRosterImportService
from app.services.organization_service import OrganizationService

router = APIRouter(prefix="/admin/organizations", tags=["admin-organizations"])


def _csv_download(filename: str, content: str) -> Response:
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/{organization_public_id}/people/{person_public_id}/verification-report",
    response_model=VerificationReportResponse,
)
async def get_admin_verification_report(
    organization_public_id: UUID,
    person_public_id: UUID,
    actor: Annotated[CurrentUser, Depends(require_user_reader)],
    service: Annotated[HRV2Service, Depends(get_hr_v2_service)],
) -> VerificationReportResponse:
    return await service.get_admin_verification_report(
        actor.id, organization_public_id, person_public_id
    )


@router.get(
    "/{organization_public_id}/team-invitations",
    response_model=list[OrganizationInvitationResponse],
)
async def list_admin_team_invitations(
    organization_public_id: UUID,
    actor: Annotated[CurrentUser, Depends(require_user_reader)],
    service: Annotated[OrganizationService, Depends(get_organization_service)],
) -> list[OrganizationInvitationResponse]:
    result = await service.list_invitations(actor.id, organization_public_id, admin_override=True)
    if not isinstance(result, list):
        return result.items
    return result


@router.post(
    "/{organization_public_id}/team-invitations",
    response_model=OrganizationInvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_admin_team_invitation(
    organization_public_id: UUID,
    payload: OrganizationInvitationCreateRequest,
    actor: Annotated[CurrentUser, Depends(require_user_manager)],
    service: Annotated[OrganizationService, Depends(get_organization_service)],
) -> OrganizationInvitationResponse:
    return await service.create_invitation(
        actor.id, organization_public_id, payload, admin_override=True
    )


@router.post(
    "/{organization_public_id}/team-invitations/{invitation_public_id}/resend",
    response_model=OrganizationInvitationResponse,
)
async def resend_admin_team_invitation(
    organization_public_id: UUID,
    invitation_public_id: UUID,
    actor: Annotated[CurrentUser, Depends(require_user_manager)],
    service: Annotated[OrganizationService, Depends(get_organization_service)],
) -> OrganizationInvitationResponse:
    return await service.resend_invitation(
        actor.id,
        organization_public_id,
        invitation_public_id,
        admin_override=True,
    )


@router.post(
    "/{organization_public_id}/team-invitations/{invitation_public_id}/cancel",
    response_model=OrganizationInvitationResponse,
)
async def cancel_admin_team_invitation(
    organization_public_id: UUID,
    invitation_public_id: UUID,
    actor: Annotated[CurrentUser, Depends(require_user_manager)],
    service: Annotated[OrganizationService, Depends(get_organization_service)],
) -> OrganizationInvitationResponse:
    return await service.cancel_invitation(
        actor.id,
        organization_public_id,
        invitation_public_id,
        admin_override=True,
    )


@router.get(
    "/{organization_public_id}/job-roles",
    response_model=list[OrganizationJobRoleResponse],
)
async def list_admin_job_roles(
    organization_public_id: UUID,
    actor: Annotated[CurrentUser, Depends(require_user_reader)],
    service: Annotated[HRV2Service, Depends(get_hr_v2_service)],
) -> list[OrganizationJobRoleResponse]:
    return await service.list_roles(actor.id, organization_public_id, admin_override=True)


@router.post(
    "/{organization_public_id}/job-roles",
    response_model=OrganizationJobRoleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_admin_job_role(
    organization_public_id: UUID,
    payload: OrganizationJobRoleCreateRequest,
    actor: Annotated[CurrentUser, Depends(require_user_manager)],
    service: Annotated[HRV2Service, Depends(get_hr_v2_service)],
) -> OrganizationJobRoleResponse:
    return await service.create_role(actor.id, organization_public_id, payload, admin_override=True)


@router.patch(
    "/{organization_public_id}/job-roles/{role_public_id}",
    response_model=OrganizationJobRoleResponse,
)
async def update_admin_job_role(
    organization_public_id: UUID,
    role_public_id: UUID,
    payload: OrganizationJobRoleUpdateRequest,
    actor: Annotated[CurrentUser, Depends(require_user_manager)],
    service: Annotated[HRV2Service, Depends(get_hr_v2_service)],
) -> OrganizationJobRoleResponse:
    return await service.update_role(
        actor.id,
        organization_public_id,
        role_public_id,
        payload,
        admin_override=True,
    )


@router.delete(
    "/{organization_public_id}/job-roles/{role_public_id}",
    response_model=OrganizationJobRoleResponse,
)
async def deactivate_admin_job_role(
    organization_public_id: UUID,
    role_public_id: UUID,
    actor: Annotated[CurrentUser, Depends(require_user_manager)],
    service: Annotated[HRV2Service, Depends(get_hr_v2_service)],
) -> OrganizationJobRoleResponse:
    return await service.deactivate_role(
        actor.id,
        organization_public_id,
        role_public_id,
        admin_override=True,
    )


@router.get(
    "/{organization_public_id}/people-imports",
    response_model=RosterImportListResponse,
)
async def list_admin_people_imports(
    organization_public_id: UUID,
    params: Annotated[RosterImportListQueryParams, Depends()],
    actor: Annotated[CurrentUser, Depends(require_user_reader)],
    service: Annotated[
        OrganizationRosterImportService,
        Depends(get_organization_roster_import_service),
    ],
) -> RosterImportListResponse:
    return await service.list_imports(
        actor_user_id=actor.id,
        org_public_id=organization_public_id,
        params=params,
        admin_override=True,
    )


@router.post(
    "/{organization_public_id}/people-imports",
    response_model=OrganizationRosterPreviewResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_admin_people_import(
    organization_public_id: UUID,
    file: Annotated[UploadFile, File()],
    actor: Annotated[CurrentUser, Depends(require_user_manager)],
    service: Annotated[
        OrganizationRosterImportService,
        Depends(get_organization_roster_import_service),
    ],
    roster_type: Annotated[OrganizationRosterType, Form()] = OrganizationRosterType.EMPLOYEE,
) -> OrganizationRosterPreviewResponse:
    await service.authorize_upload(
        actor_user_id=actor.id,
        org_public_id=organization_public_id,
        admin_override=True,
    )
    try:
        content = await file.read(MAX_UPLOAD_BYTES + 1)
    finally:
        await file.close()
    return await service.upload_preview(
        actor_user_id=actor.id,
        org_public_id=organization_public_id,
        roster_type=roster_type,
        filename=file.filename or "",
        content_type=file.content_type,
        content=content,
        admin_override=True,
    )


@router.get(
    "/{organization_public_id}/people-imports/{import_public_id}",
    response_model=OrganizationRosterPreviewResponse,
)
async def get_admin_people_import(
    organization_public_id: UUID,
    import_public_id: UUID,
    actor: Annotated[CurrentUser, Depends(require_user_reader)],
    service: Annotated[
        OrganizationRosterImportService,
        Depends(get_organization_roster_import_service),
    ],
) -> OrganizationRosterPreviewResponse:
    return await service.get_preview(
        actor_user_id=actor.id,
        org_public_id=organization_public_id,
        import_public_id=import_public_id,
        admin_override=True,
    )


@router.post(
    "/{organization_public_id}/people-imports/{import_public_id}/confirm",
    response_model=OrganizationRosterPreviewResponse,
)
async def confirm_admin_people_import(
    organization_public_id: UUID,
    import_public_id: UUID,
    actor: Annotated[CurrentUser, Depends(require_user_manager)],
    service: Annotated[
        OrganizationRosterImportService,
        Depends(get_organization_roster_import_service),
    ],
) -> OrganizationRosterPreviewResponse:
    return await service.confirm_import(
        actor_user_id=actor.id,
        org_public_id=organization_public_id,
        import_public_id=import_public_id,
        admin_override=True,
    )


@router.get(
    "/{organization_public_id}/people-import-template.csv",
    response_class=Response,
)
async def download_admin_people_import_template(
    organization_public_id: UUID,
    actor: Annotated[CurrentUser, Depends(require_user_reader)],
    service: Annotated[
        OrganizationRosterImportService,
        Depends(get_organization_roster_import_service),
    ],
) -> Response:
    await service.authorize_template_download(
        actor_user_id=actor.id,
        org_public_id=organization_public_id,
        admin_override=True,
    )
    return _csv_download(*build_roster_template(OrganizationRosterType.EMPLOYEE))


@router.get("", response_model=AdminOrganizationPage)
async def list_admin_organizations(
    params: Annotated[AdminOrganizationListParams, Depends()],
    _: Annotated[CurrentUser, Depends(require_user_reader)],
    svc: Annotated[AdminOrganizationService, Depends(get_admin_organization_service)],
) -> AdminOrganizationPage:
    return await svc.list_organizations(params)


@router.post(
    "/{organization_public_id}/company-record/connect",
    response_model=AdminOrganizationCompanyRecordResponse,
)
async def connect_admin_organization_company_record(
    organization_public_id: UUID,
    payload: AdminOrganizationCompanyRecordConnectRequest,
    actor: Annotated[CurrentUser, Depends(require_user_manager)],
    svc: Annotated[AdminOrganizationService, Depends(get_admin_organization_service)],
) -> AdminOrganizationCompanyRecordResponse:
    return await svc.connect_company_record(actor.id, organization_public_id, payload)


@router.post(
    "/{organization_public_id}/company-record/create-and-connect",
    response_model=AdminOrganizationCompanyRecordResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_and_connect_admin_organization_company_record(
    organization_public_id: UUID,
    payload: AdminOrganizationCompanyRecordCreateRequest,
    actor: Annotated[CurrentUser, Depends(require_user_manager)],
    svc: Annotated[AdminOrganizationService, Depends(get_admin_organization_service)],
) -> AdminOrganizationCompanyRecordResponse:
    return await svc.create_and_connect_company_record(
        actor.id,
        organization_public_id,
        payload,
    )


@router.get("/{organization_public_id}", response_model=AdminOrganizationDetailResponse)
async def get_admin_organization(
    organization_public_id: UUID,
    _: Annotated[CurrentUser, Depends(require_user_reader)],
    svc: Annotated[AdminOrganizationService, Depends(get_admin_organization_service)],
) -> AdminOrganizationDetailResponse:
    return await svc.get_organization(organization_public_id)


@router.get(
    "/{organization_public_id}/overview",
    response_model=AdminOrganizationOverviewResponse,
)
async def get_admin_organization_overview(
    organization_public_id: UUID,
    _: Annotated[CurrentUser, Depends(require_user_reader)],
    svc: Annotated[AdminOrganizationService, Depends(get_admin_organization_service)],
) -> AdminOrganizationOverviewResponse:
    return await svc.get_overview(organization_public_id)


@router.get("/{organization_public_id}/people", response_model=AdminOrganizationPeoplePage)
async def list_admin_organization_people(
    organization_public_id: UUID,
    params: Annotated[ListQueryParams, Depends()],
    _: Annotated[CurrentUser, Depends(require_user_reader)],
    svc: Annotated[AdminOrganizationService, Depends(get_admin_organization_service)],
) -> AdminOrganizationPeoplePage:
    return await svc.list_people(organization_public_id, params)


@router.get(
    "/{organization_public_id}/verifications",
    response_model=AdminOrganizationVerificationPage,
)
async def list_admin_organization_verifications(
    organization_public_id: UUID,
    params: Annotated[AdminOrganizationVerificationListParams, Depends()],
    _: Annotated[CurrentUser, Depends(require_user_reader)],
    svc: Annotated[AdminOrganizationService, Depends(get_admin_organization_service)],
) -> AdminOrganizationVerificationPage:
    return await svc.list_verifications(organization_public_id, params)


@router.get("/{organization_public_id}/team", response_model=AdminOrganizationTeamPage)
async def list_admin_organization_team(
    organization_public_id: UUID,
    params: Annotated[ListQueryParams, Depends()],
    _: Annotated[CurrentUser, Depends(require_user_reader)],
    svc: Annotated[AdminOrganizationService, Depends(get_admin_organization_service)],
) -> AdminOrganizationTeamPage:
    return await svc.list_team(organization_public_id, params)


@router.get("/{organization_public_id}/activity", response_model=AdminOrganizationActivityPage)
async def list_admin_organization_activity(
    organization_public_id: UUID,
    params: Annotated[ListQueryParams, Depends()],
    _: Annotated[CurrentUser, Depends(require_user_reader)],
    svc: Annotated[AdminOrganizationService, Depends(get_admin_organization_service)],
) -> AdminOrganizationActivityPage:
    return await svc.list_activity(organization_public_id, params)
