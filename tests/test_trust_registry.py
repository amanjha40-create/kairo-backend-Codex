"""Route-contract tests for Trust Registry admin and lookup APIs."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import (
    get_trust_registry_resolution_service,
    get_trust_registry_search_service,
    get_trust_registry_service,
)
from app.main import app
from app.schemas.pagination import Page
from app.schemas.trust_registry import (
    TrustRegistryAliasResponse,
    TrustRegistryCapabilityResponse,
    TrustRegistryDetailResponse,
    TrustRegistryDomainResponse,
    TrustRegistryIdentifierResponse,
    TrustRegistryLookupResponse,
    TrustRegistryMergeResponse,
    TrustRegistryOrganizationResolutionResponse,
    TrustRegistryRecordCapabilityResponse,
    TrustRegistryRecordResponse,
    TrustRegistryVerificationRequestResolutionResponse,
)
from app.trust_registry.enums import TrustRegistryResolutionState


class FakeTrustRegistryService:
    def __init__(self) -> None:
        self._record_public_id = uuid4()
        self._child_public_id = uuid4()
        self._capability_public_id = uuid4()
        self._assignment_public_id = uuid4()
        self._domain_public_id = uuid4()
        self._alias_public_id = uuid4()
        self._identifier_public_id = uuid4()
        self._relationship_public_id = uuid4()
        self._now = datetime.now(tz=UTC)

    def _record(self) -> TrustRegistryRecordResponse:
        return TrustRegistryRecordResponse(
            public_id=self._record_public_id,
            registry_code="KR-EMP-ABC12345",
            legal_name="Kairo Labs Pvt Ltd",
            display_name="Kairo Labs",
            organization_type="employer",
            country="IN",
            state_province="DL",
            website="https://kairo.example.com",
            lifecycle_status="active",
            trust_status="trusted",
            registry_confidence_score=Decimal("91.5"),
            trust_metadata={"tier": "gold"},
            created_at=self._now,
            updated_at=self._now,
        )

    async def create_record(self, actor_user_id, payload):  # noqa: ANN001
        return TrustRegistryDetailResponse(
            **self._record().model_dump(),
            domains=[],
            aliases=[],
            identifiers=[],
            capabilities=[],
        )

    async def list_records(self, params):  # noqa: ANN001
        return Page[TrustRegistryRecordResponse](
            items=[self._record()],
            total=1,
            page=1,
            page_size=10,
            total_pages=1,
            offset=0,
            limit=10,
        )

    async def get_detail(self, registry_public_id):  # noqa: ANN001
        return TrustRegistryDetailResponse(
            **self._record().model_dump(),
            domains=[
                TrustRegistryDomainResponse(
                    public_id=self._domain_public_id,
                    domain="kairo.example.com",
                    is_primary=True,
                    is_verified=True,
                    source_type="manual",
                    source_metadata={},
                    created_at=self._now,
                    updated_at=self._now,
                )
            ],
            aliases=[
                TrustRegistryAliasResponse(
                    public_id=self._alias_public_id,
                    alias_name="Kairo Labs",
                    alias_type="brand_name",
                    source_type="manual",
                    source_metadata={},
                    created_at=self._now,
                    updated_at=self._now,
                )
            ],
            identifiers=[
                TrustRegistryIdentifierResponse(
                    public_id=self._identifier_public_id,
                    identifier_type="gst",
                    identifier_value="29ABCDE1234F2Z5",
                    issuing_country="IN",
                    issuing_authority="GSTN",
                    is_primary=True,
                    is_verified=True,
                    status="active",
                    source_type="government_import",
                    source_metadata={},
                    metadata={},
                    created_at=self._now,
                    updated_at=self._now,
                )
            ],
            capabilities=[
                TrustRegistryRecordCapabilityResponse(
                    public_id=self._assignment_public_id,
                    capability=TrustRegistryCapabilityResponse(
                        public_id=self._capability_public_id,
                        capability_key="employment",
                        display_name="Employment",
                        description=None,
                        created_at=self._now,
                        updated_at=self._now,
                    ),
                    status="active",
                    source_type="manual",
                    source_metadata={},
                    created_at=self._now,
                    updated_at=self._now,
                )
            ],
        )

    async def update_record(self, actor_user_id, registry_public_id, payload):  # noqa: ANN001
        return await self.get_detail(registry_public_id)

    async def create_capability(self, payload):  # noqa: ANN001
        return TrustRegistryCapabilityResponse(
            public_id=self._capability_public_id,
            capability_key=payload.capability_key,
            display_name=payload.display_name,
            description=payload.description,
            created_at=self._now,
            updated_at=self._now,
        )

    async def add_capability_assignment(self, registry_public_id, payload):  # noqa: ANN001
        return TrustRegistryRecordCapabilityResponse(
            public_id=self._assignment_public_id,
            capability=TrustRegistryCapabilityResponse(
                public_id=self._capability_public_id,
                capability_key=payload.capability_key,
                display_name=payload.display_name or "Employment",
                description=payload.description,
                created_at=self._now,
                updated_at=self._now,
            ),
            status=payload.status.value,
            source_type=payload.source_type.value,
            source_metadata=payload.source_metadata,
            created_at=self._now,
            updated_at=self._now,
        )

    async def add_domain(self, registry_public_id, payload):  # noqa: ANN001
        return TrustRegistryDomainResponse(
            public_id=self._domain_public_id,
            domain=payload.domain,
            is_primary=payload.is_primary,
            is_verified=payload.is_verified,
            source_type=payload.source_type.value,
            source_metadata=payload.source_metadata,
            created_at=self._now,
            updated_at=self._now,
        )

    async def add_alias(self, registry_public_id, payload):  # noqa: ANN001
        return TrustRegistryAliasResponse(
            public_id=self._alias_public_id,
            alias_name=payload.alias_name,
            alias_type=payload.alias_type.value,
            source_type=payload.source_type.value,
            source_metadata=payload.source_metadata,
            created_at=self._now,
            updated_at=self._now,
        )

    async def add_identifier(self, registry_public_id, payload):  # noqa: ANN001
        return TrustRegistryIdentifierResponse(
            public_id=self._identifier_public_id,
            identifier_type=payload.identifier_type,
            identifier_value=payload.identifier_value,
            issuing_country=payload.issuing_country,
            issuing_authority=payload.issuing_authority,
            is_primary=payload.is_primary,
            is_verified=payload.is_verified,
            status=payload.status.value,
            source_type=payload.source_type.value,
            source_metadata=payload.source_metadata,
            metadata=payload.metadata,
            created_at=self._now,
            updated_at=self._now,
        )

    async def add_relationship(self, registry_public_id, payload):  # noqa: ANN001
        from app.schemas.trust_registry import TrustRegistryRelationshipResponse

        return TrustRegistryRelationshipResponse(
            public_id=self._relationship_public_id,
            parent_registry_record_public_id=self._record_public_id,
            child_registry_record_public_id=payload.child_registry_record_public_id,
            relationship_type=payload.relationship_type.value,
            status=payload.status.value,
            metadata=payload.metadata,
            created_at=self._now,
            updated_at=self._now,
        )


class FakeTrustRegistrySearchService:
    def __init__(self) -> None:
        self._now = datetime.now(tz=UTC)
        self._record = TrustRegistryRecordResponse(
            public_id=uuid4(),
            registry_code="KR-EMP-ABC12345",
            legal_name="Kairo Labs Pvt Ltd",
            display_name="Kairo Labs",
            organization_type="employer",
            country="IN",
            state_province="DL",
            website=None,
            lifecycle_status="active",
            trust_status="trusted",
            registry_confidence_score=Decimal("90"),
            trust_metadata={},
            created_at=self._now,
            updated_at=self._now,
        )

    async def search(self, params):  # noqa: ANN001
        return Page[TrustRegistryRecordResponse](
            items=[self._record],
            total=1,
            page=1,
            page_size=10,
            total_pages=1,
            offset=0,
            limit=10,
        )

    async def lookup_by_domain(self, domain):  # noqa: ANN001
        return TrustRegistryLookupResponse(
            resolution_state=TrustRegistryResolutionState.RESOLVED,
            matches=[self._record],
            match_reason="exact_domain",
        )

    async def lookup_by_identifier(self, identifier_type, identifier_value):  # noqa: ANN001
        return TrustRegistryLookupResponse(
            resolution_state=TrustRegistryResolutionState.RESOLVED,
            matches=[self._record],
            match_reason="exact_identifier",
        )

    async def lookup_by_name(self, name):  # noqa: ANN001
        return TrustRegistryLookupResponse(
            resolution_state=TrustRegistryResolutionState.DEFERRED,
            matches=[self._record, self._record.model_copy(update={"public_id": uuid4()})],
            match_reason="exact_name",
        )


class FakeTrustRegistryResolutionService:
    def __init__(self) -> None:
        self._org_public_id = uuid4()
        self._request_public_id = uuid4()
        self._record_public_id = uuid4()
        self._merge_public_id = uuid4()
        self._now = datetime.now(tz=UTC)

    async def resolve_organization(self, actor_user_id, org_public_id, payload):  # noqa: ANN001
        return TrustRegistryOrganizationResolutionResponse(
            organization_public_id=org_public_id,
            registry_record_public_id=payload.registry_record_public_id,
            resolution_state=TrustRegistryResolutionState.RESOLVED,
            resolution_method=payload.resolution_method.value,
            resolution_confidence=float(payload.resolution_confidence) if payload.resolution_confidence is not None else None,
            resolution_metadata=payload.resolution_metadata,
        )

    async def resolve_verification_request(self, actor_user_id, verification_request_public_id, payload):  # noqa: ANN001
        return TrustRegistryVerificationRequestResolutionResponse(
            verification_request_public_id=verification_request_public_id,
            registry_record_public_id=payload.registry_record_public_id,
            resolution_state=TrustRegistryResolutionState.RESOLVED,
            resolution_method=payload.resolution_method.value,
            resolution_confidence=float(payload.resolution_confidence) if payload.resolution_confidence is not None else None,
            resolution_metadata=payload.resolution_metadata,
        )

    async def create_record_and_resolve_verification_request(self, actor_user_id, verification_request_public_id, payload):  # noqa: ANN001
        return TrustRegistryVerificationRequestResolutionResponse(
            verification_request_public_id=verification_request_public_id,
            registry_record_public_id=uuid4(),
            resolution_state=TrustRegistryResolutionState.RESOLVED,
            resolution_method=payload.resolution_method.value,
            resolution_confidence=float(payload.resolution_confidence) if payload.resolution_confidence is not None else None,
            resolution_metadata=payload.resolution_metadata,
        )

    async def defer_verification_request_resolution(self, actor_user_id, verification_request_public_id, payload):  # noqa: ANN001
        return TrustRegistryVerificationRequestResolutionResponse(
            verification_request_public_id=verification_request_public_id,
            registry_record_public_id=None,
            resolution_state=TrustRegistryResolutionState.DEFERRED,
            resolution_method=None,
            resolution_confidence=None,
            resolution_metadata=payload.resolution_metadata,
        )

    async def merge_records(self, actor_user_id, source_registry_public_id, payload):  # noqa: ANN001
        return TrustRegistryMergeResponse(
            public_id=self._merge_public_id,
            source_registry_record_public_id=source_registry_public_id,
            target_registry_record_public_id=payload.target_registry_record_public_id,
            merge_reason=payload.merge_reason,
            metadata=payload.metadata,
            created_at=self._now,
        )


async def _override_admin_user() -> CurrentUser:
    return CurrentUser(
        id=UUID("00000000-0000-0000-0000-000000000999"),
        email="admin@kairo.test",
        role="admin",
    )


@pytest.mark.asyncio
async def test_create_trust_registry_record_returns_created_payload() -> None:
    app.dependency_overrides[get_current_user] = _override_admin_user
    app.dependency_overrides[get_trust_registry_service] = lambda: FakeTrustRegistryService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/admin/trust-registry",
            json={
                "legal_name": "Kairo Labs Pvt Ltd",
                "display_name": "Kairo Labs",
                "organization_type": "employer",
                "country": "IN",
                "state_province": "DL",
                "website": "https://kairo.example.com",
                "lifecycle_status": "active",
                "trust_status": "trusted",
                "registry_confidence_score": 91.5,
                "trust_metadata": {"tier": "gold"},
            },
        )

    app.dependency_overrides.clear()
    assert response.status_code == 201
    assert response.json()["registry_code"] == "KR-EMP-ABC12345"


@pytest.mark.asyncio
async def test_add_registry_metadata_endpoints_return_created_resources() -> None:
    app.dependency_overrides[get_current_user] = _override_admin_user
    app.dependency_overrides[get_trust_registry_service] = lambda: FakeTrustRegistryService()

    transport = ASGITransport(app=app)
    registry_public_id = uuid4()
    child_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        domain_response = await client.post(
            f"/api/v1/admin/trust-registry/{registry_public_id}/domains",
            json={
                "domain": "kairo.example.com",
                "is_primary": True,
                "is_verified": True,
                "source_type": "manual",
                "source_metadata": {},
            },
        )
        alias_response = await client.post(
            f"/api/v1/admin/trust-registry/{registry_public_id}/aliases",
            json={
                "alias_name": "Kairo Labs",
                "alias_type": "brand_name",
                "source_type": "manual",
                "source_metadata": {},
            },
        )
        identifier_response = await client.post(
            f"/api/v1/admin/trust-registry/{registry_public_id}/identifiers",
            json={
                "identifier_type": "gst",
                "identifier_value": "29ABCDE1234F2Z5",
                "issuing_country": "IN",
                "issuing_authority": "GSTN",
                "is_primary": True,
                "is_verified": True,
                "status": "active",
                "source_type": "government_import",
                "source_metadata": {},
                "metadata": {},
            },
        )
        capability_response = await client.post(
            f"/api/v1/admin/trust-registry/{registry_public_id}/capabilities",
            json={
                "capability_key": "employment",
                "display_name": "Employment",
                "description": None,
                "status": "active",
                "source_type": "manual",
                "source_metadata": {},
            },
        )
        relationship_response = await client.post(
            f"/api/v1/admin/trust-registry/{registry_public_id}/relationships",
            json={
                "child_registry_record_public_id": str(child_public_id),
                "relationship_type": "subsidiary_of",
                "status": "active",
                "metadata": {},
            },
        )

    app.dependency_overrides.clear()
    assert domain_response.status_code == 201
    assert alias_response.status_code == 201
    assert identifier_response.status_code == 201
    assert capability_response.status_code == 201
    assert relationship_response.status_code == 201


@pytest.mark.asyncio
async def test_search_and_lookup_routes_return_expected_shapes() -> None:
    app.dependency_overrides[get_current_user] = _override_admin_user
    app.dependency_overrides[get_trust_registry_search_service] = lambda: FakeTrustRegistrySearchService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        search_response = await client.get("/api/v1/internal/trust-registry/search?search=kairo")
        domain_response = await client.get("/api/v1/internal/trust-registry/lookup-by-domain?domain=kairo.example.com")
        identifier_response = await client.get(
            "/api/v1/internal/trust-registry/lookup-by-identifier?identifier_type=gst&identifier_value=29ABCDE1234F2Z5"
        )
        name_response = await client.get("/api/v1/internal/trust-registry/lookup-by-name?name=Kairo Labs")

    app.dependency_overrides.clear()
    assert search_response.status_code == 200
    assert search_response.json()["total"] == 1
    assert domain_response.status_code == 200
    assert domain_response.json()["resolution_state"] == "resolved"
    assert identifier_response.status_code == 200
    assert identifier_response.json()["match_reason"] == "exact_identifier"
    assert name_response.status_code == 200
    assert name_response.json()["resolution_state"] == "deferred"


@pytest.mark.asyncio
async def test_resolution_and_merge_routes_return_expected_payloads() -> None:
    app.dependency_overrides[get_current_user] = _override_admin_user
    app.dependency_overrides[get_trust_registry_resolution_service] = lambda: FakeTrustRegistryResolutionService()

    transport = ASGITransport(app=app)
    org_public_id = uuid4()
    request_public_id = uuid4()
    registry_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        org_response = await client.post(
            f"/api/v1/internal/trust-registry/organizations/{org_public_id}/resolve-registry",
            json={
                "registry_record_public_id": str(registry_public_id),
                "resolution_method": "manual",
                "resolution_confidence": 97,
                "resolution_metadata": {"reason": "exact gst match"},
            },
        )
        request_response = await client.post(
            f"/api/v1/internal/trust-registry/verification-requests/{request_public_id}/resolve-registry",
            json={
                "registry_record_public_id": str(registry_public_id),
                "resolution_method": "manual",
                "resolution_confidence": 88,
                "resolution_metadata": {"reason": "reviewer resolved"},
            },
        )
        defer_response = await client.post(
            f"/api/v1/internal/trust-registry/verification-requests/{request_public_id}/defer-registry-resolution",
            json={"resolution_metadata": {"reason": "manual research required"}},
        )
        merge_response = await client.post(
            f"/api/v1/admin/trust-registry/{registry_public_id}/merge",
            json={
                "target_registry_record_public_id": str(uuid4()),
                "merge_reason": "duplicate import",
                "metadata": {"source": "ops"},
            },
        )

    app.dependency_overrides.clear()
    assert org_response.status_code == 200
    assert org_response.json()["resolution_state"] == "resolved"
    assert request_response.status_code == 200
    assert request_response.json()["registry_record_public_id"] == str(registry_public_id)
    assert defer_response.status_code == 200
    assert defer_response.json()["resolution_state"] == "deferred"
    assert merge_response.status_code == 200
    assert merge_response.json()["merge_reason"] == "duplicate import"
