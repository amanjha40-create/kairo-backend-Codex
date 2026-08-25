"""Focused regressions for Admin pre-dispatch organization resolution."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.exceptions import ConflictError
from app.schemas.admin_review_workflow import AdminReviewOrganizationResolutionRequest
from app.services.verification_request_admin_review_service import (
    VerificationRequestAdminReviewService,
)
from app.verification_requests.enums import (
    VerificationRequestEventSource,
    VerificationRequestStatus,
)


def _request(*, status: VerificationRequestStatus, organization_id=None) -> SimpleNamespace:  # noqa: ANN001
    employment = SimpleNamespace(verification_status="draft")
    return SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        status=status,
        organization_id=organization_id,
        target_organization_name=None,
        registry_record_id=None,
        registry_record=None,
        registry_resolution_state="unresolved",
        registry_resolution_method=None,
        registry_resolution_confidence=None,
        registry_resolution_metadata={},
        registry_resolved_at=None,
        registry_resolved_by_user_id=None,
        employment_id=uuid4(),
        education_id=None,
        employment=employment,
    )


def _service(
    request: SimpleNamespace,
    organization: SimpleNamespace,
) -> VerificationRequestAdminReviewService:
    service = VerificationRequestAdminReviewService.__new__(VerificationRequestAdminReviewService)
    service._get_required_request = AsyncMock(return_value=request)
    service._organizations = SimpleNamespace(get_by_public_id=AsyncMock(return_value=organization))
    service._workflow = SimpleNamespace(record_action=AsyncMock(), transition=AsyncMock())
    service._session = SimpleNamespace(commit=AsyncMock())
    service._requests = SimpleNamespace(get_by_public_id=AsyncMock(return_value=request))
    service._to_request_response = AsyncMock(return_value=SimpleNamespace(status=request.status))
    service._advance_to_organization_stage = AsyncMock()
    service._registry_sync = SimpleNamespace(
        sync_organization=AsyncMock(
            return_value=SimpleNamespace(resolution_method="exact_domain")
        )
    )
    return service


class _LazyRegistryOrganization:
    def __init__(self) -> None:
        self.id = uuid4()
        self.public_id = uuid4()
        self.name = "Verifier Organization"
        self.registry_record_id = uuid4()
        self.registry_resolution_confidence = 100.0
        self.registry_resolved_at = None

    @property
    def registry_record(self) -> SimpleNamespace:  # pragma: no cover - defensive trap
        raise AssertionError("resolve_organization should not touch lazy registry_record")


@pytest.mark.asyncio
async def test_admin_resolves_organization_during_pre_dispatch_without_dispatching() -> None:
    request = _request(status=VerificationRequestStatus.PENDING_ADMIN_REVIEW)
    organization = SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        name="Verifier Organization",
        registry_record_id=uuid4(),
        registry_record=SimpleNamespace(id=uuid4()),
        registry_resolution_confidence=100.0,
        registry_resolved_at=None,
    )
    organization.registry_record.id = organization.registry_record_id
    service = _service(request, organization)

    result = await service.resolve_organization(
        uuid4(),
        request.public_id,
        AdminReviewOrganizationResolutionRequest(organization_public_id=organization.public_id),
    )

    assert result.status == VerificationRequestStatus.PENDING_ADMIN_REVIEW
    assert request.organization_id == organization.id
    assert request.target_organization_name == organization.name
    assert request.registry_record_id == organization.registry_record_id
    assert request.registry_resolution_state == "resolved"
    assert request.registry_resolution_method == "exact_domain"
    assert request.employment.verification_status == "draft"


@pytest.mark.asyncio
async def test_admin_education_dispatch_issues_public_institution_link() -> None:
    request = SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        status=VerificationRequestStatus.APPROVED_FOR_ORGANIZATION_VERIFICATION,
        organization_id=uuid4(),
        target_organization_name="Institution Acceptance University",
        employment_id=None,
        education_id=uuid4(),
        organization_outreach_sent_at=None,
    )
    actor_user_id = uuid4()
    service = VerificationRequestAdminReviewService.__new__(VerificationRequestAdminReviewService)
    service._contacts = SimpleNamespace(get_current=AsyncMock(return_value=None))
    service._institution_outreach = SimpleNamespace(issue_public_link=AsyncMock())
    service._workflow = SimpleNamespace(
        transition=AsyncMock(),
        record_action=AsyncMock(),
    )

    await service._advance_to_organization_stage(request, actor_user_id=actor_user_id)

    service._institution_outreach.issue_public_link.assert_awaited_once_with(
        actor_user_id=actor_user_id,
        verification_request=request,
    )
    service._workflow.transition.assert_awaited_once()
    assert request.organization_outreach_sent_at is not None
    call = service._workflow.transition.await_args.kwargs
    assert call["event_type"] == "organization_resolved"
    assert call["event_source"] == VerificationRequestEventSource.SYSTEM


@pytest.mark.asyncio
async def test_pre_dispatch_resolution_does_not_touch_lazy_registry_relationship() -> None:
    request = _request(status=VerificationRequestStatus.PENDING_ADMIN_REVIEW)
    organization = _LazyRegistryOrganization()
    service = _service(request, organization)

    await service.resolve_organization(
        uuid4(),
        request.public_id,
        AdminReviewOrganizationResolutionRequest(organization_public_id=organization.public_id),
    )

    assert request.registry_record_id == organization.registry_record_id
    assert request.registry_resolution_method == "exact_domain"


@pytest.mark.asyncio
async def test_repeating_same_pre_dispatch_resolution_is_idempotent() -> None:
    organization = SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        name="Verifier Organization",
        registry_record_id=uuid4(),
        registry_record=SimpleNamespace(id=uuid4()),
        registry_resolution_confidence=100.0,
        registry_resolved_at=None,
    )
    organization.registry_record.id = organization.registry_record_id
    request = _request(
        status=VerificationRequestStatus.PENDING_ADMIN_REVIEW,
        organization_id=organization.id,
    )
    service = _service(request, organization)

    await service.resolve_organization(
        uuid4(),
        request.public_id,
        AdminReviewOrganizationResolutionRequest(organization_public_id=organization.public_id),
    )

    service._workflow.record_action.assert_not_awaited()
    service._session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_pre_dispatch_resolution_rejects_conflicting_organization() -> None:
    request = _request(
        status=VerificationRequestStatus.PENDING_ADMIN_REVIEW,
        organization_id=uuid4(),
    )
    organization = SimpleNamespace(id=uuid4(), public_id=uuid4(), name="Other Organization")
    service = _service(request, organization)

    with pytest.raises(ConflictError, match="already resolved"):
        await service.resolve_organization(
            uuid4(),
            request.public_id,
            AdminReviewOrganizationResolutionRequest(organization_public_id=organization.public_id),
        )

    service._workflow.record_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolution_fails_closed_for_wrong_state() -> None:
    request = _request(status=VerificationRequestStatus.PENDING_ADMIN_QUALITY_REVIEW)
    organization = SimpleNamespace(id=uuid4(), public_id=uuid4(), name="Verifier Organization")
    service = _service(request, organization)

    with pytest.raises(ConflictError, match="not awaiting organization resolution"):
        await service.resolve_organization(
            uuid4(),
            request.public_id,
            AdminReviewOrganizationResolutionRequest(organization_public_id=organization.public_id),
        )


def test_pre_dispatch_resolution_leaves_canonical_employment_draft() -> None:
    request = _request(status=VerificationRequestStatus.PENDING_ADMIN_REVIEW)

    assert request.employment.verification_status == "draft"
