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
    return service


@pytest.mark.asyncio
async def test_admin_resolves_organization_during_pre_dispatch_without_dispatching() -> None:
    request = _request(status=VerificationRequestStatus.PENDING_ADMIN_REVIEW)
    organization = SimpleNamespace(id=uuid4(), public_id=uuid4(), name="Verifier Organization")
    service = _service(request, organization)

    result = await service.resolve_organization(
        uuid4(),
        request.public_id,
        AdminReviewOrganizationResolutionRequest(organization_public_id=organization.public_id),
    )

    assert result.status == VerificationRequestStatus.PENDING_ADMIN_REVIEW
    assert request.organization_id == organization.id
    assert request.target_organization_name == organization.name
    assert request.employment.verification_status == "draft"
    service._workflow.record_action.assert_awaited_once()
    call = service._workflow.record_action.await_args.kwargs
    assert call["event_type"] == "verification_request_organization_resolved"
    assert call["event_source"] == VerificationRequestEventSource.ADMIN
    service._advance_to_organization_stage.assert_not_awaited()


@pytest.mark.asyncio
async def test_repeating_same_pre_dispatch_resolution_is_idempotent() -> None:
    organization = SimpleNamespace(id=uuid4(), public_id=uuid4(), name="Verifier Organization")
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
    service._session.commit.assert_not_awaited()


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
