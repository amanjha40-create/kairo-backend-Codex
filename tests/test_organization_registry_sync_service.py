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
