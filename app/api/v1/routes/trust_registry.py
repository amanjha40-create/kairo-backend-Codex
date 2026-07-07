"""Admin and internal Trust Registry routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies.services import (
    get_trust_registry_resolution_service,
    get_trust_registry_search_service,
    get_trust_registry_service,
)
from app.api.dependencies.verification_admin import CurrentUser, require_reviewer, require_view_cases
from app.schemas.pagination import ListQueryParams, Page
from app.schemas.trust_registry import (
    TrustRegistryAliasCreateRequest,
    TrustRegistryAliasResponse,
    TrustRegistryCapabilityCreateRequest,
    TrustRegistryCapabilityResponse,
    TrustRegistryCreateAndResolveRequest,
    TrustRegistryDeferResolutionRequest,
    TrustRegistryDetailResponse,
    TrustRegistryDomainCreateRequest,
    TrustRegistryDomainResponse,
    TrustRegistryIdentifierCreateRequest,
    TrustRegistryIdentifierResponse,
    TrustRegistryLookupResponse,
    TrustRegistryMergeRequest,
    TrustRegistryMergeResponse,
    TrustRegistryOrganizationResolutionResponse,
    TrustRegistryRecordCapabilityCreateRequest,
    TrustRegistryRecordCapabilityResponse,
    TrustRegistryRecordCreateRequest,
    TrustRegistryRecordResponse,
    TrustRegistryRecordUpdateRequest,
    TrustRegistryRelationshipCreateRequest,
    TrustRegistryRelationshipResponse,
    TrustRegistryResolutionRequest,
    TrustRegistryVerificationRequestResolutionResponse,
)
from app.services.trust_registry_resolution_service import TrustRegistryResolutionService
from app.services.trust_registry_search_service import TrustRegistrySearchService
from app.services.trust_registry_service import TrustRegistryService

admin_router = APIRouter(prefix="/admin/trust-registry", tags=["trust-registry"])
internal_router = APIRouter(prefix="/internal/trust-registry", tags=["trust-registry"])


@admin_router.post("", response_model=TrustRegistryDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_trust_registry_record(
    payload: TrustRegistryRecordCreateRequest,
    reviewer: Annotated[CurrentUser, Depends(require_reviewer)],
    svc: Annotated[TrustRegistryService, Depends(get_trust_registry_service)],
) -> TrustRegistryDetailResponse:
    return await svc.create_record(reviewer.id, payload)


@admin_router.get("", response_model=Page[TrustRegistryRecordResponse])
async def list_trust_registry_records(
    params: Annotated[ListQueryParams, Depends()],
    _: Annotated[CurrentUser, Depends(require_view_cases)],
    svc: Annotated[TrustRegistryService, Depends(get_trust_registry_service)],
) -> Page[TrustRegistryRecordResponse]:
    result = await svc.list_records(params)
    if isinstance(result, list):
        raise RuntimeError("Trust Registry list must return a page envelope")
    return result


@admin_router.get("/{registry_public_id}", response_model=TrustRegistryDetailResponse)
async def get_trust_registry_record(
    registry_public_id: UUID,
    _: Annotated[CurrentUser, Depends(require_view_cases)],
    svc: Annotated[TrustRegistryService, Depends(get_trust_registry_service)],
) -> TrustRegistryDetailResponse:
    return await svc.get_detail(registry_public_id)


@admin_router.patch("/{registry_public_id}", response_model=TrustRegistryDetailResponse)
async def update_trust_registry_record(
    registry_public_id: UUID,
    payload: TrustRegistryRecordUpdateRequest,
    reviewer: Annotated[CurrentUser, Depends(require_reviewer)],
    svc: Annotated[TrustRegistryService, Depends(get_trust_registry_service)],
) -> TrustRegistryDetailResponse:
    return await svc.update_record(reviewer.id, registry_public_id, payload)


@admin_router.post("/capabilities", response_model=TrustRegistryCapabilityResponse, status_code=status.HTTP_201_CREATED)
async def create_trust_registry_capability(
    payload: TrustRegistryCapabilityCreateRequest,
    reviewer: Annotated[CurrentUser, Depends(require_reviewer)],
    svc: Annotated[TrustRegistryService, Depends(get_trust_registry_service)],
) -> TrustRegistryCapabilityResponse:
    _ = reviewer
    return await svc.create_capability(payload)


@admin_router.post(
    "/{registry_public_id}/capabilities",
    response_model=TrustRegistryRecordCapabilityResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_trust_registry_capability(
    registry_public_id: UUID,
    payload: TrustRegistryRecordCapabilityCreateRequest,
    reviewer: Annotated[CurrentUser, Depends(require_reviewer)],
    svc: Annotated[TrustRegistryService, Depends(get_trust_registry_service)],
) -> TrustRegistryRecordCapabilityResponse:
    _ = reviewer
    return await svc.add_capability_assignment(registry_public_id, payload)


@admin_router.post("/{registry_public_id}/domains", response_model=TrustRegistryDomainResponse, status_code=status.HTTP_201_CREATED)
async def add_trust_registry_domain(
    registry_public_id: UUID,
    payload: TrustRegistryDomainCreateRequest,
    reviewer: Annotated[CurrentUser, Depends(require_reviewer)],
    svc: Annotated[TrustRegistryService, Depends(get_trust_registry_service)],
) -> TrustRegistryDomainResponse:
    _ = reviewer
    return await svc.add_domain(registry_public_id, payload)


@admin_router.post("/{registry_public_id}/aliases", response_model=TrustRegistryAliasResponse, status_code=status.HTTP_201_CREATED)
async def add_trust_registry_alias(
    registry_public_id: UUID,
    payload: TrustRegistryAliasCreateRequest,
    reviewer: Annotated[CurrentUser, Depends(require_reviewer)],
    svc: Annotated[TrustRegistryService, Depends(get_trust_registry_service)],
) -> TrustRegistryAliasResponse:
    _ = reviewer
    return await svc.add_alias(registry_public_id, payload)


@admin_router.post(
    "/{registry_public_id}/identifiers",
    response_model=TrustRegistryIdentifierResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_trust_registry_identifier(
    registry_public_id: UUID,
    payload: TrustRegistryIdentifierCreateRequest,
    reviewer: Annotated[CurrentUser, Depends(require_reviewer)],
    svc: Annotated[TrustRegistryService, Depends(get_trust_registry_service)],
) -> TrustRegistryIdentifierResponse:
    _ = reviewer
    return await svc.add_identifier(registry_public_id, payload)


@admin_router.post(
    "/{registry_public_id}/relationships",
    response_model=TrustRegistryRelationshipResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_trust_registry_relationship(
    registry_public_id: UUID,
    payload: TrustRegistryRelationshipCreateRequest,
    reviewer: Annotated[CurrentUser, Depends(require_reviewer)],
    svc: Annotated[TrustRegistryService, Depends(get_trust_registry_service)],
) -> TrustRegistryRelationshipResponse:
    _ = reviewer
    return await svc.add_relationship(registry_public_id, payload)


@admin_router.post("/{registry_public_id}/merge", response_model=TrustRegistryMergeResponse)
async def merge_trust_registry_record(
    registry_public_id: UUID,
    payload: TrustRegistryMergeRequest,
    reviewer: Annotated[CurrentUser, Depends(require_reviewer)],
    svc: Annotated[TrustRegistryResolutionService, Depends(get_trust_registry_resolution_service)],
) -> TrustRegistryMergeResponse:
    return await svc.merge_records(reviewer.id, registry_public_id, payload)


@internal_router.get("/search", response_model=Page[TrustRegistryRecordResponse])
async def search_trust_registry(
    params: Annotated[ListQueryParams, Depends()],
    _: Annotated[CurrentUser, Depends(require_view_cases)],
    svc: Annotated[TrustRegistrySearchService, Depends(get_trust_registry_search_service)],
) -> Page[TrustRegistryRecordResponse]:
    result = await svc.search(params)
    if isinstance(result, list):
        raise RuntimeError("Trust Registry search must return a page envelope")
    return result


@internal_router.get("/lookup-by-domain", response_model=TrustRegistryLookupResponse)
async def lookup_trust_registry_by_domain(
    domain: Annotated[str, Query(min_length=1)],
    _: Annotated[CurrentUser, Depends(require_view_cases)],
    svc: Annotated[TrustRegistrySearchService, Depends(get_trust_registry_search_service)],
) -> TrustRegistryLookupResponse:
    return await svc.lookup_by_domain(domain)


@internal_router.get("/lookup-by-identifier", response_model=TrustRegistryLookupResponse)
async def lookup_trust_registry_by_identifier(
    identifier_type: Annotated[str, Query(min_length=1)],
    identifier_value: Annotated[str, Query(min_length=1)],
    _: Annotated[CurrentUser, Depends(require_view_cases)],
    svc: Annotated[TrustRegistrySearchService, Depends(get_trust_registry_search_service)],
) -> TrustRegistryLookupResponse:
    return await svc.lookup_by_identifier(identifier_type.strip().lower(), identifier_value.strip())


@internal_router.get("/lookup-by-name", response_model=TrustRegistryLookupResponse)
async def lookup_trust_registry_by_name(
    name: Annotated[str, Query(min_length=1)],
    _: Annotated[CurrentUser, Depends(require_view_cases)],
    svc: Annotated[TrustRegistrySearchService, Depends(get_trust_registry_search_service)],
) -> TrustRegistryLookupResponse:
    return await svc.lookup_by_name(name)


@internal_router.post(
    "/organizations/{org_public_id}/resolve-registry",
    response_model=TrustRegistryOrganizationResolutionResponse,
)
async def resolve_organization_to_trust_registry(
    org_public_id: UUID,
    payload: TrustRegistryResolutionRequest,
    reviewer: Annotated[CurrentUser, Depends(require_reviewer)],
    svc: Annotated[TrustRegistryResolutionService, Depends(get_trust_registry_resolution_service)],
) -> TrustRegistryOrganizationResolutionResponse:
    return await svc.resolve_organization(reviewer.id, org_public_id, payload)


@internal_router.post(
    "/verification-requests/{verification_request_public_id}/resolve-registry",
    response_model=TrustRegistryVerificationRequestResolutionResponse,
)
async def resolve_verification_request_to_trust_registry(
    verification_request_public_id: UUID,
    payload: TrustRegistryResolutionRequest,
    reviewer: Annotated[CurrentUser, Depends(require_reviewer)],
    svc: Annotated[TrustRegistryResolutionService, Depends(get_trust_registry_resolution_service)],
) -> TrustRegistryVerificationRequestResolutionResponse:
    return await svc.resolve_verification_request(reviewer.id, verification_request_public_id, payload)


@internal_router.post(
    "/verification-requests/{verification_request_public_id}/create-registry-record",
    response_model=TrustRegistryVerificationRequestResolutionResponse,
)
async def create_trust_registry_record_and_resolve_verification_request(
    verification_request_public_id: UUID,
    payload: TrustRegistryCreateAndResolveRequest,
    reviewer: Annotated[CurrentUser, Depends(require_reviewer)],
    svc: Annotated[TrustRegistryResolutionService, Depends(get_trust_registry_resolution_service)],
) -> TrustRegistryVerificationRequestResolutionResponse:
    return await svc.create_record_and_resolve_verification_request(reviewer.id, verification_request_public_id, payload)


@internal_router.post(
    "/verification-requests/{verification_request_public_id}/defer-registry-resolution",
    response_model=TrustRegistryVerificationRequestResolutionResponse,
)
async def defer_verification_request_registry_resolution(
    verification_request_public_id: UUID,
    payload: TrustRegistryDeferResolutionRequest,
    reviewer: Annotated[CurrentUser, Depends(require_reviewer)],
    svc: Annotated[TrustRegistryResolutionService, Depends(get_trust_registry_resolution_service)],
) -> TrustRegistryVerificationRequestResolutionResponse:
    return await svc.defer_verification_request_resolution(reviewer.id, verification_request_public_id, payload)

