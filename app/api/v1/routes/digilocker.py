"""Requester OAuth lifecycle, with only safe connection metadata exposed to clients."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse, RedirectResponse

from app.auth.deps import CurrentUser, get_current_user
from app.config import Settings, get_settings
from app.db.session import get_session
from app.exceptions import AppException, ServiceUnavailableError
from app.infrastructure.redis.deps import get_redis
from app.services.digilocker_document_service import DigiLockerDocumentService
from app.services.digilocker_identity_service import DigiLockerIdentityService
from app.services.digilocker_service import DigiLockerService, flow_error

router = APIRouter(prefix="/integrations/digilocker", tags=["digilocker"])
PRIVATE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


class ConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConnectResponse(BaseModel):
    authorization_url: str
    expires_at: datetime
    connection_state: Literal["pending"]


class StatusResponse(BaseModel):
    connected: bool
    status: Literal["pending", "active", "reconnect_required", "disconnected"]
    connected_at: datetime | None
    consent_valid_until: datetime | None
    scopes: list[str]


def get_digilocker_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[Redis, Depends(get_redis)],
):
    return DigiLockerService(session, settings, redis)


Service = Annotated[DigiLockerService, Depends(get_digilocker_service)]
Principal = Annotated[CurrentUser, Depends(get_current_user)]


def get_document_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[Redis, Depends(get_redis)],
):
    return DigiLockerDocumentService(session, settings, redis)


DocumentService = Annotated[DigiLockerDocumentService, Depends(get_document_service)]


def get_identity_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[Redis, Depends(get_redis)],
):
    return DigiLockerIdentityService(session, settings, redis)


IdentityService = Annotated[DigiLockerIdentityService, Depends(get_identity_service)]


class IdentityVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_types: list[Literal["PANCR", "DRVLC"]] = Field(min_length=1, max_length=2)
    consent: StrictBool
    consent_version: Literal["v1"]


@router.get("/identity/verifications")
async def identity_history(response: Response, user: Principal, service: IdentityService):
    response.headers.update(PRIVATE_HEADERS)
    return await service.history(user.id)


@router.post("/identity/verify")
async def verify_identity(
    body: IdentityVerificationRequest, response: Response, user: Principal, service: IdentityService
):
    response.headers.update(PRIVATE_HEADERS)
    return await service.verify(
        user.id, body.document_types, consent=body.consent, consent_version=body.consent_version
    )


class RetrievalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference: str = Field(min_length=1, max_length=16384, repr=False)


@router.get("/documents/issued")
async def issued_documents(response: Response, user: Principal, service: DocumentService):
    response.headers.update(PRIVATE_HEADERS)
    return await service.issued(user.id)


@router.post("/documents/retrieve")
async def retrieve_document(
    body: RetrievalRequest,
    response: Response,
    user: Principal,
    service: DocumentService,
):
    response.headers.update(PRIVATE_HEADERS)
    return await service.retrieve(user.id, body.reference)


@router.post("/connect", response_model=ConnectResponse)
async def connect(
    request: Request,
    response: Response,
    user: Principal,
    service: Service,
    body: ConnectRequest | None = None,
):
    if request.query_params:
        raise flow_error("callback_invalid")
    response.headers.update(PRIVATE_HEADERS)
    return await service.connect(user.id)


@router.get("/status", response_model=StatusResponse)
async def status(response: Response, user: Principal, service: Service):
    response.headers.update(PRIVATE_HEADERS)
    return await service.status(user.id)


@router.delete("/connection", status_code=204)
async def disconnect(user: Principal, service: Service):
    await service.disconnect(user.id)
    return Response(status_code=204, headers=PRIVATE_HEADERS)


@router.get("/callback")
async def callback(request: Request, service: Service):
    try:
        params = request.query_params
        if any(len(params.getlist(key)) != 1 for key in params) or set(params) - {
            "state",
            "code",
            "error",
            "error_description",
        }:
            raise flow_error("callback_invalid")
        result = await service.callback(
            state=params.get("state"), code=params.get("code"), error=params.get("error")
        )
    except AppException as exc:
        status_code = 503 if isinstance(exc, ServiceUnavailableError) else 400
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message}},
            status_code=status_code,
            headers=PRIVATE_HEADERS,
        )
    destination = service.settings.digilocker_connection_return_url
    if destination:
        return RedirectResponse(
            destination + "?digilocker_result=connected", status_code=303, headers=PRIVATE_HEADERS
        )
    return JSONResponse(result, headers=PRIVATE_HEADERS)
