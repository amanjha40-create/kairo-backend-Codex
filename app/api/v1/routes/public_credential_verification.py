"""Public credential magic-link handlers — no JWT (token in URL)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, status
from starlette.responses import HTMLResponse

from app.api.dependencies.services import get_credential_verification_service
from app.exceptions import AppException, ConflictError, NotFoundError
from app.integrations.email.employer_verification_pages import render_result_page
from app.services.credential_verification_service import CredentialVerificationService

router = APIRouter(prefix="/public/credential-verification", tags=["public"])


@router.get("/{token}", response_class=HTMLResponse)
async def credential_verification_review_page(
    token: str,
    service: Annotated[CredentialVerificationService, Depends(get_credential_verification_service)],
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
async def credential_verification_respond(
    token: str,
    action: Annotated[str, Form()],
    service: Annotated[CredentialVerificationService, Depends(get_credential_verification_service)],
    remarks: Annotated[str | None, Form()] = None,
) -> HTMLResponse:
    try:
        html = await service.respond_with_action(token, action, remarks)
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
        if isinstance(exc, ConflictError):
            code = status.HTTP_409_CONFLICT
        html = render_result_page(title="Unable to process", message=exc.message, success=False)
        return HTMLResponse(content=html, status_code=code)
