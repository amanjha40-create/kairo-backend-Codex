"""Focused regressions for workspace organization to Registry synchronization."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.exceptions import ConflictError
from app.models.trust_registry_domain import TrustRegistryDomain
from app.services.organization_registry_sync_service import (
    OrganizationRegistrySyncService,
)
from app.trust_registry.enums import TrustRegistryResolutionMethod, TrustRegistryResolutionState


def _organization():
    return SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        created_by_user_id=uuid4(),
        name="Platform QA Employer 0804",
        domain="example.com",
        website="https://example.com",
        organization_type="employer",
        verification_state="setup_incomplete",
        registry_record_id=None,
        registry_record=None,
        registry_resolution_method=None,
        registry_resolution_confidence=None,
        registry_resolution_metadata={},
        registry_resolved_at=None,
        registry_resolved_by_user_id=None,
    )


def _record():
    return SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        deleted_at=None,
        legal_name="Platform QA Employer 0804",
        display_name="Platform QA Employer 0804",
        aliases=[],
        trust_metadata={},
    )


def _service() -> OrganizationRegistrySyncService:
    service = OrganizationRegistrySyncService.__new__(OrganizationRegistrySyncService)
    service._session = SimpleNamespace(
        add=Mock(),
        flush=AsyncMock(),
        commit=AsyncMock(),
        scalar=AsyncMock(return_value=0),
    )
    service._records = SimpleNamespace(
        get_by_id=AsyncMock(return_value=None),
        get_by_public_id=AsyncMock(),
    )
    service._registry = SimpleNamespace(create_record=AsyncMock())
    service._find_domain_matches = AsyncMock(return_value=[])
    service._find_name_matches = AsyncMock(return_value=[])
    service._sync_related_requests = AsyncMock(return_value=0)
    return service


@pytest.mark.asyncio
async def test_sync_links_existing_registry_record_by_exact_domain_without_creating_duplicate(
) -> None:
    organization = _organization()
    record = _record()
    service = _service()
    service._find_domain_matches = AsyncMock(return_value=[record])

    result = await service.sync_organization(
        organization,
        actor_user_id=uuid4(),
    )

    assert result.action == "linked_existing_domain"
    assert organization.registry_record_id == record.id
    service._registry.create_record.assert_not_awaited()
    service._sync_related_requests.assert_awaited_once()


@pytest.mark.asyncio
async def test_sync_creates_new_draft_registry_record_and_primary_domain() -> None:
    organization = _organization()
    record = _record()
    service = _service()
    service._registry.create_record = AsyncMock(
        return_value=SimpleNamespace(public_id=record.public_id)
    )
    service._records.get_by_public_id = AsyncMock(return_value=record)
    service._sync_related_requests = AsyncMock(return_value=1)

    result = await service.sync_organization(
        organization,
        actor_user_id=uuid4(),
    )

    assert result.action == "created_new_record"
    assert result.request_links_synced == 1
    assert organization.registry_record_id == record.id
    service._registry.create_record.assert_awaited_once()
    added = service._session.add.call_args.args[0]
    assert isinstance(added, TrustRegistryDomain)
    assert added.domain == "example.com"


@pytest.mark.asyncio
async def test_sync_fails_closed_when_workspace_org_matches_multiple_registry_records() -> None:
    organization = _organization()
    service = _service()
    service._find_domain_matches = AsyncMock(return_value=[_record(), _record()])

    with pytest.raises(ConflictError, match="multiple Trust Registry records"):
        await service.sync_organization(
            organization,
            actor_user_id=uuid4(),
        )

    service._registry.create_record.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_reuses_existing_org_link_and_repairs_request_registry_links() -> None:
    organization = _organization()
    organization.registry_record_id = uuid4()
    record = _record()
    record.id = organization.registry_record_id
    service = _service()
    service._records.get_by_id = AsyncMock(return_value=record)
    service._sync_related_requests = AsyncMock(return_value=2)

    result = await service.sync_organization(
        organization,
        actor_user_id=uuid4(),
    )

    assert result.action == "already_linked"
    assert result.request_links_synced == 2
    service._registry.create_record.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_does_not_domain_link_unrelated_organization_sharing_same_domain() -> None:
    organization = _organization()
    service = _service()
    delattr(service, "_find_domain_matches")
    unrelated = _record()
    unrelated.legal_name = "Aman"
    unrelated.display_name = "Aman"
    unrelated.trust_metadata = {"workspace_organization_public_id": str(uuid4())}
    matching = _record()
    matching.legal_name = organization.name
    matching.display_name = organization.name

    service._domains = SimpleNamespace(
        get_by_domain=AsyncMock(
            return_value=[
                SimpleNamespace(
                    deleted_at=None,
                    registry_record=unrelated,
                ),
                SimpleNamespace(
                    deleted_at=None,
                    registry_record=matching,
                ),
            ]
        )
    )

    matches = await service._find_domain_matches(organization)

    assert matches == [matching]


@pytest.mark.asyncio
async def test_sync_repairs_existing_mislinked_registry_record() -> None:
    organization = _organization()
    organization.registry_record_id = uuid4()
    stale_record = _record()
    stale_record.id = organization.registry_record_id
    stale_record.legal_name = "Aman"
    stale_record.display_name = "Aman"
    stale_record.trust_metadata = {"workspace_organization_public_id": str(uuid4())}
    correct_record = _record()
    correct_record.legal_name = organization.name
    correct_record.display_name = organization.name

    service = _service()
    service._records.get_by_id = AsyncMock(return_value=stale_record)
    service._find_name_matches = AsyncMock(return_value=[correct_record])

    result = await service.sync_organization(
        organization,
        actor_user_id=uuid4(),
    )

    assert result.action == "linked_existing_name"
    assert organization.registry_record_id == correct_record.id
    service._registry.create_record.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_updates_existing_request_links_when_registry_identity_changes() -> None:
    organization = _organization()
    record = _record()
    request = SimpleNamespace(
        registry_record_id=uuid4(),
        registry_record=None,
        registry_resolution_state=None,
        registry_resolution_method=None,
        registry_resolution_confidence=None,
        registry_resolution_metadata={},
        registry_resolved_at=None,
        registry_resolved_by_user_id=None,
    )
    service = _service()
    delattr(service, "_sync_related_requests")
    service._session.execute = AsyncMock(
        return_value=SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: [request]),
        )
    )

    synced = await service._sync_related_requests(
        organization,
        record,
        actor_user_id=uuid4(),
        method=TrustRegistryResolutionMethod.EXACT_NAME,
    )

    assert synced == 1
    assert request.registry_record_id == record.id
    assert request.registry_record is record
    assert request.registry_resolution_state == TrustRegistryResolutionState.RESOLVED.value
    assert request.registry_resolution_method == TrustRegistryResolutionMethod.EXACT_NAME.value
