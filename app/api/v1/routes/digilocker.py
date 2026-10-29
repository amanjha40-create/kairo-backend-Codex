"""Requester OAuth lifecycle, with only safe connection metadata exposed to clients."""

from datetime import date, datetime
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
from app.integrations.digilocker.browser_return import browser_redirect, completion_page
from app.schemas.digilocker_discovery import (
    AvailableRecordsResponse,
    ImportRecordsRequest,
    ImportRecordsResponse,
)
from app.schemas.trust_score import IdentityTrustResponse
from app.services.digilocker_discovery_service import DigiLockerDiscoveryService
from app.services.digilocker_document_service import DigiLockerDocumentService
from app.services.digilocker_eaadhaar_service import DigiLockerEAadhaarService
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


def get_discovery_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[Redis, Depends(get_redis)],
):
    return DigiLockerDiscoveryService(session, settings, redis)


DiscoveryService = Annotated[DigiLockerDiscoveryService, Depends(get_discovery_service)]


def get_eaadhaar_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[Redis, Depends(get_redis)],
):
    return DigiLockerEAadhaarService(session, settings, redis)


EAadhaarService = Annotated[DigiLockerEAadhaarService, Depends(get_eaadhaar_service)]


class EAadhaarVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consent: StrictBool
    consent_version: Literal["v1"]


class EAadhaarAvailabilityResponse(BaseModel):
    available: bool
    entitlement_confirmed: Literal[False]


class EAadhaarVerificationResponse(BaseModel):
    id: str
    source: Literal["digilocker"]
    source_type: Literal["eaadhaar"]
    document_type: Literal["EAADHAAR"]
    integrity_result: Literal["verified"]
    match_result: Literal["VERIFIED_MATCH", "PARTIAL_MATCH", "MISMATCH", "UNABLE_TO_VERIFY"]
    match_reason: (
        Literal[
            "NAME_MISMATCH",
            "DOB_MISMATCH",
            "NAME_AND_DOB_MISMATCH",
            "REQUIRED_FIELD_MISSING",
            "OTHER",
        ]
        | None
    )
    verified_at: datetime | None
    document_valid_until: date | None
    consent_purpose: Literal["identity_verification"]
    consent_version: Literal["v1"]
    consented_at: datetime
    current: bool


@router.get("/eaadhaar/availability", response_model=EAadhaarAvailabilityResponse)
async def eaadhaar_availability(response: Response, user: Principal, service: EAadhaarService):
    response.headers.update(PRIVATE_HEADERS)
    return await service.availability(user.id)


@router.post("/eaadhaar/verify", response_model=EAadhaarVerificationResponse)
async def verify_eaadhaar(
    body: EAadhaarVerificationRequest, response: Response, user: Principal, service: EAadhaarService
):
    response.headers.update(PRIVATE_HEADERS)
    return await service.verify_aadhaar(
        user.id, consent=body.consent, consent_version=body.consent_version
    )


class IdentityVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_types: list[Literal["PANCR", "DRVLC"]] = Field(min_length=1, max_length=2)
    consent: StrictBool
    consent_version: Literal["v1"]


@router.get("/identity/verifications")
async def identity_history(response: Response, user: Principal, service: IdentityService):
    response.headers.update(PRIVATE_HEADERS)
    return await service.history(user.id)


@router.get("/identity/trust", response_model=IdentityTrustResponse)
async def identity_trust(response: Response, user: Principal, service: IdentityService):
    response.headers.update(PRIVATE_HEADERS)
    return await service.trust(user.id)


@router.post("/identity/verify")
async def verify_identity(
    body: IdentityVerificationRequest, response: Response, user: Principal, service: IdentityService
):
    response.headers.update(PRIVATE_HEADERS)
    return await service.verify(
        user.id, body.document_types, consent=body.consent, consent_version=body.consent_version
    )


@router.get("/available-records", response_model=AvailableRecordsResponse)
async def available_records(
    response: Response,
    user: Principal,
    service: DiscoveryService,
):
    response.headers.update(PRIVATE_HEADERS)
    return await service.available_records(user.id)


@router.post("/records/import", response_model=ImportRecordsResponse)
async def import_records(
    body: ImportRecordsRequest,
    response: Response,
    user: Principal,
    service: DiscoveryService,
):
    response.headers.update(PRIVATE_HEADERS)
    return await service.import_records(
        user.id,
        body.candidate_ids,
        education_targets=body.education_targets,
        consent=body.consent,
        consent_version=body.consent_version,
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
        if "text/html" in request.headers.get("accept", "").lower():
            return browser_redirect("failed")
        status_code = 503 if isinstance(exc, ServiceUnavailableError) else 400
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message}},
            status_code=status_code,
            headers=PRIVATE_HEADERS,
        )
    if "text/html" in request.headers.get("accept", "").lower():
        return browser_redirect("connected")
    destination = service.settings.digilocker_connection_return_url
    if destination:
        return RedirectResponse(
            destination + "?digilocker_result=connected", status_code=303, headers=PRIVATE_HEADERS
        )
    return JSONResponse(result, headers=PRIVATE_HEADERS)


@router.get("/complete", include_in_schema=False)
async def complete(request: Request, settings: Annotated[Settings, Depends(get_settings)]):
    params = request.query_params
    outcome = (
        "connected"
        if set(params) == {"digilocker_result"}
        and params.getlist("digilocker_result") == ["connected"]
        else "failed"
    )
    return completion_page(settings, outcome, user_agent=request.headers.get("user-agent", ""))
