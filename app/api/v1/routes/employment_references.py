"""Candidate nomination, authorized HR operations, and scoped manager capabilities."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.reference_capability import employer_capability, manager_capability
from app.api.dependencies.services import get_employer_verification_service
from app.api.dependencies.verification_admin import require_dispatch, require_view_cases
from app.db.session import get_session
from app.exceptions import AppException
from app.exceptions.handlers import app_exception_handler
from app.integrations.email.manager_reference_page import render_manager_page, render_manager_result
from app.schemas.employment_reference import (
    CandidateReferences,
    ManagerNomination,
    ManagerResponse,
    ManagerValidation,
    SendReference,
)
from app.services.employer_verification_service import EmployerVerificationService
from app.services.employment_reference_service import EmploymentReferenceService

router = APIRouter(tags=["employment-references"])


def service(session: Annotated[AsyncSession, Depends(get_session)]):
    return EmploymentReferenceService(session)


Service = Annotated[EmploymentReferenceService, Depends(service)]
Candidate = Annotated[CurrentUser, Depends(get_current_user)]
Employer = Annotated[EmployerVerificationService, Depends(get_employer_verification_service)]


@router.get("/employments/{employment_id}/references", response_model=CandidateReferences)
async def candidate_references(employment_id: UUID, current: Candidate, svc: Service):
    return await svc.summary(current.id, employment_id)


@router.put(
    "/employments/{employment_id}/references/reporting-manager", response_model=CandidateReferences
)
async def nominate_manager(
    employment_id: UUID, payload: ManagerNomination, current: Candidate, svc: Service
):
    return await svc.nominate(current.id, employment_id, payload)


@router.post(
    "/employments/{employment_id}/references/reporting-manager/change",
    response_model=CandidateReferences,
)
async def change_manager(
    employment_id: UUID, payload: ManagerNomination, current: Candidate, svc: Service
):
    return await svc.nominate(current.id, employment_id, payload, replace=True)


@router.post(
    "/public/employer-verifications/{token}/references/manager-validation",
    dependencies=[Depends(employer_capability)],
)
async def validate_manager(
    token: str, payload: ManagerValidation, employer: Employer, svc: Service
):
    req = await employer._load_portal_token_for_update(token)
    await svc.validate_manager(req, payload)
    await svc.db.commit()
    return await svc.hr_context(req.employment_id)


@router.post(
    "/public/employer-verifications/{token}/references/reporting-manager/invite",
    dependencies=[Depends(employer_capability)],
)
async def hr_invite(token: str, payload: SendReference, employer: Employer, svc: Service):
    req = await employer._load_portal_token_for_update(token)
    return await svc.send(req.employment_id, payload)


@router.get("/admin/employments/{employment_id}/references")
async def reference_report(
    employment_id: UUID, svc: Service, _: Annotated[CurrentUser, Depends(require_view_cases)]
):
    return await svc.report(employment_id)


@router.post("/admin/employments/{employment_id}/references/reporting-manager/invite")
async def admin_invite(
    employment_id: UUID,
    payload: SendReference,
    svc: Service,
    _: Annotated[CurrentUser, Depends(require_dispatch)],
):
    return await svc.send(employment_id, payload)


@router.post("/admin/employments/{employment_id}/references/{nomination_id}/revoke")
async def admin_revoke(
    employment_id: UUID,
    nomination_id: UUID,
    svc: Service,
    _: Annotated[CurrentUser, Depends(require_dispatch)],
):
    return await svc.revoke(employment_id, nomination_id)


@router.post("/admin/employments/{employment_id}/references/hr-link/renew")
async def renew_hr_link(
    employment_id: UUID,
    payload: SendReference,
    svc: Service,
    _: Annotated[CurrentUser, Depends(require_dispatch)],
):
    return await svc.renew_hr_link(employment_id, payload)


@router.get("/public/manager-references/{token}", dependencies=[Depends(manager_capability)])
async def manager_context(token: str, svc: Service):
    return await svc.context(token)


@router.post(
    "/public/manager-references/{token}/response", dependencies=[Depends(manager_capability)]
)
async def manager_response(token: str, payload: ManagerResponse, svc: Service):
    return await svc.respond(token, payload)


@router.post(
    "/public/manager-references/{token}/decline", dependencies=[Depends(manager_capability)]
)
async def manager_decline(token: str, svc: Service):
    return await svc.respond(token, decline=True)


PAGE_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; "
    "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
}


async def manager_link_error(request: Request, exc: AppException):
    # Keep the API's status/retry policy, but never render its error details.
    error = await app_exception_handler(request, exc)
    headers = dict(PAGE_HEADERS)
    if "retry-after" in error.headers:
        headers["Retry-After"] = error.headers["retry-after"]
    return HTMLResponse(
        render_manager_result(
            "This reference link is no longer available. "
            "The link may be invalid, expired, revoked, or already completed."
        ),
        status_code=error.status_code,
        headers=headers,
    )


@router.get(
    "/public/manager-references/{token}/page",
    response_class=HTMLResponse,
)
async def manager_page(token: str, request: Request, svc: Service):
    try:
        manager_capability(request)
        context = await svc.context(token)
    except AppException as exc:
        return await manager_link_error(request, exc)
    return HTMLResponse(render_manager_page(context), headers=PAGE_HEADERS)


@router.post(
    "/public/manager-references/{token}/respond-form",
    response_class=HTMLResponse,
)
async def manager_form(token: str, request: Request, svc: Service):
    try:
        manager_capability(request)
        form = dict(await request.form())
        action = form.pop("action", "submit")
        if action == "decline":
            result = await svc.respond(token, decline=True)
        else:
            for field in (
                "overall_performance",
                "reliability_ownership",
                "communication",
                "teamwork_collaboration",
            ):
                if form.get(field):
                    form[field] = int(form[field])
                else:
                    form.pop(field, None)
            for field in ("period_start", "period_end"):
                if not form.get(field):
                    form.pop(field, None)
            form["attested"] = form.get("attested") == "yes"
            result = await svc.respond(token, ManagerResponse.model_validate(form))
    except (ValidationError, ValueError):
        return HTMLResponse(
            render_manager_result(
                "Please check the dates, ratings and confirmation. "
                "Use your browser's Back button to correct the form."
            ),
            status_code=422,
            headers=PAGE_HEADERS,
        )
    except AppException as exc:
        return await manager_link_error(request, exc)
    return HTMLResponse(
        render_manager_result(
            "Thank you. Your response has been recorded."
            if result["status"] != "needs_review"
            else "Thank you. Your relationship clarification has been recorded for review."
        ),
        headers=PAGE_HEADERS,
    )
