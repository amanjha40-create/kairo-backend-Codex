"""Focused regression for verification detail to Registry projection."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.schemas.verification_request import VerificationRequestResponse
from app.services.verification_request_admin_review_service import (
    VerificationRequestAdminReviewService,
)
from app.verification_requests.enums import VerificationRequestStatus, VerificationRequestType


def _request(*, organization_id, registry_record_id=None) -> SimpleNamespace:  # noqa: ANN001
    return SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        employment_id=None,
        organization_id=organization_id,
        registry_record_id=registry_record_id,
        registry_resolution_state="resolved",
        registry_resolution_method="exact_domain",
        registry_resolution_confidence=100.0,
        registry_resolution_metadata={"routing_confidence": 100},
        target_organization_name="KDTU",
    )


def _request_response(request_public_id) -> VerificationRequestResponse:  # noqa: ANN001
    now = datetime.now(UTC)
    return VerificationRequestResponse(
        public_id=request_public_id,
        candidate_user_public_id=None,
        employment_id=None,
        education_id=None,
        origin_type=None,
        organization_public_id=None,
        trust_invitation_public_id=None,
        subject_name="Candidate Example",
        subject_email="candidate@example.com",
        target_organization_name="KDTU",
        target_organization_email="hr@kdtu.example",
        request_type=VerificationRequestType.EMPLOYMENT,
        status=VerificationRequestStatus.PENDING_ADMIN_REVIEW,
        priority="normal",
        due_date=None,
        trust_context={},
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_detail_projects_registry_link_from_resolved_org() -> None:
    organization = SimpleNamespace(
        public_id=uuid4(),
        name="KDTU",
        registry_record_id=uuid4(),
    )
    registry_record = SimpleNamespace(
        public_id=uuid4(),
        registry_code="KR-ORG-KDTU",
        display_name="KDTU",
        legal_name="KDTU",
    )
    request = _request(organization_id=uuid4(), registry_record_id=None)

    service = VerificationRequestAdminReviewService.__new__(VerificationRequestAdminReviewService)
    service._get_required_request = AsyncMock(return_value=request)
    service._evidence = SimpleNamespace(list_for_request=AsyncMock(return_value=[]))
    service._reviews = SimpleNamespace(
        list_reviews_for_request=AsyncMock(return_value=[]),
        list_open_corrections_for_request=AsyncMock(return_value=[]),
        list_notes_for_request=AsyncMock(return_value=[]),
    )
    service._contacts = SimpleNamespace(list_versions=AsyncMock(return_value=[]))
    service._employments = SimpleNamespace(get_active_by_id=AsyncMock(return_value=None))
    service._organizations = SimpleNamespace(get_by_id=AsyncMock(return_value=organization))
    service._registry = SimpleNamespace(get_by_id=AsyncMock(return_value=registry_record))
    service._employer_verifications = SimpleNamespace(
        get_by_verification_request_id=AsyncMock(return_value=None)
    )
    service._to_request_response = AsyncMock(return_value=_request_response(request.public_id))

    detail = await service.get_detail(request.public_id)

    assert detail.registry_resolution.status == "resolved"
    assert detail.registry_resolution.registry_record_public_id == registry_record.public_id
    assert detail.registry_resolution.registry_name == "KDTU"
    service._registry.get_by_id.assert_awaited_once_with(organization.registry_record_id)
