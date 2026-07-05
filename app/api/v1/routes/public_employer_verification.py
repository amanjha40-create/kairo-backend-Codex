"""Public employer magic-link handlers — no JWT (token in URL)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, status
from starlette.responses import HTMLResponse

from app.api.dependencies.services import get_employer_verification_service
from app.exceptions import AppException, ConflictError, NotFoundError
from app.integrations.email.employer_verification_pages import render_result_page
from app.services.employer_verification_service import EmployerVerificationService

router = APIRouter(prefix="/public/employer-verification", tags=["public"])


@router.get("/{token}", response_class=HTMLResponse)
async def employer_verification_review_page(
    token: str,
    service: Annotated[EmployerVerificationService, Depends(get_employer_verification_service)],
) -> HTMLResponse:
    try:
        html = await service.render_review_page(token)
        return HTMLResponse(content=html, status_code=200)
    except NotFoundError:
        html = render_result_page(
            title="Link invalid or expired",
            message="This verification link is invalid or has expired. Ask the applicant to send a new request.",
            success=False,
        )
        return HTMLResponse(content=html, status_code=404)


@router.post("/{token}/respond", response_class=HTMLResponse)
async def employer_verification_respond(
    token: str,
    action: Annotated[str, Form()],
    service: Annotated[EmployerVerificationService, Depends(get_employer_verification_service)],
    remarks: Annotated[str | None, Form()] = None,
) -> HTMLResponse:
    return await _respond_html(service.respond_with_action, token, action, remarks)


# Legacy single-click confirm/decline kept for any outstanding emails
@router.get("/{token}/confirm", response_class=HTMLResponse)
async def employer_verification_confirm(
    token: str,
    service: Annotated[EmployerVerificationService, Depends(get_employer_verification_service)],
) -> HTMLResponse:
    return await _respond_html(service.respond_confirm, token, None, None)


@router.get("/{token}/decline", response_class=HTMLResponse)
async def employer_verification_decline(
    token: str,
    service: Annotated[EmployerVerificationService, Depends(get_employer_verification_service)],
) -> HTMLResponse:
    return await _respond_html(service.respond_decline, token, None, None)


async def _respond_html(handler, token: str, action, remarks) -> HTMLResponse:
    try:
        if action is not None:
            html = await handler(token, action, remarks)
        else:
            html = await handler(token)
        return HTMLResponse(content=html, status_code=200)
    except NotFoundError:
        html = render_result_page(
            title="Link invalid or expired",
            message="This verification link is invalid or has expired. Ask the applicant to send a new request.",
            success=False,
        )
        return HTMLResponse(content=html, status_code=404)
    except AppException as exc:
        code = status.HTTP_400_BAD_REQUEST
        if isinstance(exc, NotFoundError):
            code = status.HTTP_404_NOT_FOUND
        elif isinstance(exc, ConflictError):
            code = status.HTTP_409_CONFLICT
        html = render_result_page(title="Unable to process", message=exc.message, success=False)
        return HTMLResponse(content=html, status_code=code)
