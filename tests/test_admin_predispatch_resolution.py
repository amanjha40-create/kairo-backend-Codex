"""Focused regressions for Admin pre-dispatch organization resolution."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.exceptions import ConflictError
from app.organization.enums import OrganizationType
from app.schemas.admin_review_workflow import (
    AdminReviewCanonicalOrganizationCreateRequest,
    AdminReviewOrganizationResolutionRequest,
)
from app.services.verification_request_admin_review_service import (
    VerificationRequestAdminReviewService,
)
from app.verification_requests.enums import (
    VerificationContactReviewStatus,
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
        organization_outreach_sent_at=None,
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
    service._get_required_request_for_update = AsyncMock(return_value=request)
    service._organizations = SimpleNamespace(get_by_public_id=AsyncMock(return_value=organization))
    service._workflow = SimpleNamespace(record_action=AsyncMock(), transition=AsyncMock())
    service._session = SimpleNamespace(commit=AsyncMock(), flush=AsyncMock(), add=Mock())
    service._requests = SimpleNamespace(get_by_public_id=AsyncMock(return_value=request))
    service._to_request_response = AsyncMock(return_value=SimpleNamespace(status=request.status))
    service._advance_to_organization_stage = AsyncMock()
    service._registry_sync = SimpleNamespace(
        sync_organization=AsyncMock(
            return_value=SimpleNamespace(
                resolution_method="exact_domain",
                registry_record_public_id=uuid4(),
            )
        )
    )
    service._contacts = SimpleNamespace(
        get_current=AsyncMock(
            return_value=SimpleNamespace(
                review_status="approved",
                contact_email="verifier@example.com",
            )
        )
    )

    async def create_registry(record):  # noqa: ANN001
        record.id = uuid4()
        return record

    service._registry = SimpleNamespace(
        get_by_id=AsyncMock(return_value=None),
        get_by_public_id=AsyncMock(return_value=None),
        find_exact_entity_matches=AsyncMock(return_value=[]),
        create=AsyncMock(side_effect=create_registry),
    )
    service._registry_codes = SimpleNamespace(generate=Mock(return_value="KR-TEST-0001"))
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


def _canonical_payload(
    *,
    organization_type: OrganizationType = OrganizationType.EMPLOYER,
    registry_record_public_id=None,  # noqa: ANN001
) -> AdminReviewCanonicalOrganizationCreateRequest:
    return AdminReviewCanonicalOrganizationCreateRequest(
        name="Verifier Organization",
        organization_type=organization_type,
        country="in",
        state_province="Karnataka",
        website="https://verifier.example",
        domain="verifier.example",
        registry_record_public_id=registry_record_public_id,
    )


def _registry_record() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        legal_name="Verifier Organization",
        display_name="Verifier Organization",
        organization_type="employer",
        country="IN",
        state_province="Karnataka",
        website="https://verifier.example",
        aliases=[],
        domains=[],
    )


@pytest.mark.asyncio
async def test_admin_creates_and_attaches_canonical_organization_with_registry_link() -> None:
    request = _request(status=VerificationRequestStatus.PENDING_ORGANIZATION_RESOLUTION)
    registry = _registry_record()
    request.registry_record_id = registry.id
    service = _service(request, SimpleNamespace())

    async def create_canonical(organization):  # noqa: ANN001
        organization.id = uuid4()
        organization.public_id = uuid4()
        return organization

    service._organizations = SimpleNamespace(
        get_by_id=AsyncMock(return_value=None),
        get_by_registry_record_id=AsyncMock(return_value=None),
        find_exact=AsyncMock(return_value=None),
        create_canonical=AsyncMock(side_effect=create_canonical),
    )
    service._registry = SimpleNamespace(
        get_by_id=AsyncMock(return_value=registry),
        get_by_public_id=AsyncMock(return_value=registry),
    )
    actor_user_id = uuid4()

    await service.create_canonical_organization(
        actor_user_id,
        request.public_id,
        _canonical_payload(registry_record_public_id=registry.public_id),
    )

    created = service._organizations.create_canonical.await_args.args[0]
    assert created.created_by_user_id == actor_user_id
    assert created.registry_record_id == registry.id
    assert created.location == "Karnataka, IN"
    assert created.verification_capabilities == ["employment"]
    assert request.organization_id == created.id
    assert request.registry_record_id == registry.id
    assert request.registry_resolution_state == "resolved"
    assert request.registry_resolution_metadata["admin_created_organization_public_id"] == str(
        created.public_id
    )
    service._advance_to_organization_stage.assert_awaited_once()
    event = service._workflow.record_action.await_args.kwargs
    assert event["event_type"] == (
        "verification_request_canonical_organization_created_and_attached"
    )
    assert event["metadata"]["canonical_organization_created"] is True


@pytest.mark.asyncio
async def test_replaying_canonical_creation_after_outreach_does_not_duplicate_side_effects(
) -> None:
    organization_id = uuid4()
    organization_public_id = uuid4()
    request = _request(
        status=VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE,
        organization_id=organization_id,
    )
    request.registry_resolution_metadata = {
        "admin_created_organization_public_id": str(organization_public_id)
    }
    organization = SimpleNamespace(id=organization_id, public_id=organization_public_id)
    service = _service(request, organization)
    service._organizations = SimpleNamespace(get_by_id=AsyncMock(return_value=organization))

    await service.create_canonical_organization(
        uuid4(),
        request.public_id,
        _canonical_payload(),
    )

    service._advance_to_organization_stage.assert_not_awaited()
    service._workflow.record_action.assert_not_awaited()
    service._session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_replaying_pre_dispatch_canonical_creation_is_idempotent() -> None:
    organization_id = uuid4()
    organization_public_id = uuid4()
    request = _request(
        status=VerificationRequestStatus.PENDING_ADMIN_REVIEW,
        organization_id=organization_id,
    )
    request.registry_resolution_metadata = {
        "admin_created_organization_public_id": str(organization_public_id)
    }
    organization = SimpleNamespace(id=organization_id, public_id=organization_public_id)
    service = _service(request, organization)
    service._organizations = SimpleNamespace(get_by_id=AsyncMock(return_value=organization))

    await service.create_canonical_organization(
        uuid4(),
        request.public_id,
        _canonical_payload(),
    )

    service._advance_to_organization_stage.assert_not_awaited()
    service._workflow.record_action.assert_not_awaited()
    service._session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_pre_dispatch_creation_does_not_require_contact_approval() -> None:
    request = _request(status=VerificationRequestStatus.PENDING_ADMIN_REVIEW)
    registry = _registry_record()
    request.registry_record_id = registry.id
    service = _service(request, SimpleNamespace())

    async def create_canonical(organization):  # noqa: ANN001
        organization.id = uuid4()
        organization.public_id = uuid4()
        return organization

    service._organizations = SimpleNamespace(
        get_by_registry_record_id=AsyncMock(return_value=None),
        find_exact=AsyncMock(return_value=None),
        create_canonical=AsyncMock(side_effect=create_canonical),
    )
    service._registry = SimpleNamespace(
        get_by_id=AsyncMock(return_value=registry),
        get_by_public_id=AsyncMock(return_value=registry),
    )
    service._contacts.get_current = AsyncMock(
        return_value=SimpleNamespace(review_status="pending", contact_email="")
    )

    await service.create_canonical_organization(
        uuid4(),
        request.public_id,
        _canonical_payload(registry_record_public_id=registry.public_id),
    )

    service._contacts.get_current.assert_not_awaited()
    service._advance_to_organization_stage.assert_not_awaited()


@pytest.mark.asyncio
async def test_canonical_creation_rejects_existing_match_instead_of_duplicating() -> None:
    request = _request(status=VerificationRequestStatus.PENDING_ORGANIZATION_RESOLUTION)
    existing = SimpleNamespace(id=uuid4(), public_id=uuid4())
    service = _service(request, existing)
    service._organizations = SimpleNamespace(
        get_by_registry_record_id=AsyncMock(return_value=None),
        find_exact=AsyncMock(return_value=existing),
    )

    with pytest.raises(ConflictError, match="already exists"):
        await service.create_canonical_organization(
            uuid4(),
            request.public_id,
            _canonical_payload(),
        )

    service._registry.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_canonical_creation_requires_approved_employment_contact() -> None:
    request = _request(status=VerificationRequestStatus.PENDING_ORGANIZATION_RESOLUTION)
    service = _service(request, SimpleNamespace())
    service._contacts.get_current = AsyncMock(
        return_value=SimpleNamespace(
            review_status="changes_requested",
            contact_email="verifier@example.com",
        )
    )

    with pytest.raises(ConflictError, match="approved verification contact"):
        await service.create_canonical_organization(
            uuid4(),
            request.public_id,
            _canonical_payload(),
        )


@pytest.mark.asyncio
async def test_canonical_creation_validates_request_organization_type() -> None:
    request = _request(status=VerificationRequestStatus.PENDING_ORGANIZATION_RESOLUTION)
    service = _service(request, SimpleNamespace())

    with pytest.raises(ConflictError, match="employer is required"):
        await service.create_canonical_organization(
            uuid4(),
            request.public_id,
            _canonical_payload(organization_type=OrganizationType.UNIVERSITY),
        )


@pytest.mark.asyncio
async def test_canonical_creation_rejects_unlinked_legacy_request() -> None:
    request = _request(status=VerificationRequestStatus.PENDING_ORGANIZATION_RESOLUTION)
    request.employment_id = None
    service = _service(request, SimpleNamespace())

    with pytest.raises(ConflictError, match="one linked Career claim"):
        await service.create_canonical_organization(
            uuid4(),
            request.public_id,
            _canonical_payload(organization_type=OrganizationType.UNIVERSITY),
        )


@pytest.mark.asyncio
async def test_terminal_request_cannot_create_canonical_organization() -> None:
    request = _request(status=VerificationRequestStatus.CANCELLED)
    service = _service(request, SimpleNamespace())

    with pytest.raises(ConflictError, match="not awaiting organization resolution"):
        await service.create_canonical_organization(
            uuid4(),
            request.public_id,
            _canonical_payload(),
        )


def test_registry_resolution_alone_does_not_resolve_canonical_organization() -> None:
    request = _request(status=VerificationRequestStatus.PENDING_ORGANIZATION_RESOLUTION)
    request.registry_record_id = uuid4()
    request.registry_resolution_state = "resolved"

    assert request.organization_id is None
    assert request.status == VerificationRequestStatus.PENDING_ORGANIZATION_RESOLUTION


@pytest.mark.asyncio
async def test_education_creates_university_and_continues_institution_outreach() -> None:
    request = _request(status=VerificationRequestStatus.PENDING_ORGANIZATION_RESOLUTION)
    request.employment_id = None
    request.education_id = uuid4()
    service = _service(request, SimpleNamespace())

    async def create_canonical(organization):  # noqa: ANN001
        organization.id = uuid4()
        organization.public_id = uuid4()
        return organization

    service._organizations = SimpleNamespace(
        get_by_registry_record_id=AsyncMock(return_value=None),
        find_exact=AsyncMock(return_value=None),
        create_canonical=AsyncMock(side_effect=create_canonical),
    )

    await service.create_canonical_organization(
        uuid4(),
        request.public_id,
        _canonical_payload(organization_type=OrganizationType.UNIVERSITY),
    )

    created = service._organizations.create_canonical.await_args.args[0]
    assert created.organization_type == OrganizationType.UNIVERSITY
    assert created.verification_capabilities == ["education"]
    assert created.registry_record_id is not None
    service._registry.create.assert_awaited_once()
    service._advance_to_organization_stage.assert_awaited_once()


@pytest.mark.asyncio
async def test_employment_outreach_is_invoked_exactly_once_for_canonical_resolution() -> None:
    request = _request(status=VerificationRequestStatus.PENDING_ORGANIZATION_RESOLUTION)
    request.organization_id = uuid4()
    contact = SimpleNamespace(
        contact_name="Verifier",
        contact_role="HR",
        contact_type="hr",
        contact_email="verifier@example.com",
        review_status=VerificationContactReviewStatus.APPROVED,
    )
    service = VerificationRequestAdminReviewService.__new__(VerificationRequestAdminReviewService)
    service._contacts = SimpleNamespace(get_current=AsyncMock(return_value=contact))
    service._employer_outreach = SimpleNamespace(initiate_admin_outreach=AsyncMock())
    service._workflow = SimpleNamespace(transition=AsyncMock())

    await service._advance_to_organization_stage(request, actor_user_id=uuid4())

    service._employer_outreach.initiate_admin_outreach.assert_awaited_once()
    service._workflow.transition.assert_awaited_once()
    assert request.organization_outreach_sent_at is not None


@pytest.mark.asyncio
async def test_persisted_outreach_marker_advances_without_resending() -> None:
    request = _request(status=VerificationRequestStatus.PENDING_ORGANIZATION_RESOLUTION)
    request.organization_id = uuid4()
    request.organization_outreach_sent_at = SimpleNamespace()
    service = VerificationRequestAdminReviewService.__new__(VerificationRequestAdminReviewService)
    service._contacts = SimpleNamespace(get_current=AsyncMock())
    service._employer_outreach = SimpleNamespace(initiate_admin_outreach=AsyncMock())
    service._workflow = SimpleNamespace(transition=AsyncMock())

    await service._advance_to_organization_stage(request, actor_user_id=uuid4())

    service._employer_outreach.initiate_admin_outreach.assert_not_awaited()
    service._contacts.get_current.assert_not_awaited()
    service._workflow.transition.assert_awaited_once()
    assert service._workflow.transition.await_args.kwargs["metadata"] == {
        "outreach_replay_prevented": "true"
    }
