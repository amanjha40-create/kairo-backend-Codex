"""Focused HR V2 contract and security tests with no external provider calls."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationAppError,
)
from app.organization.enums import OrganizationInvitationStatus, OrganizationRole
from app.organization_people.enums import (
    OrganizationPersonEmploymentStatus,
    OrganizationPersonRelationship,
)
from app.schemas.hr_v2 import (
    EmployeeLifecycleUpdateRequest,
    OrganizationLogoUploadIntentRequest,
    OrganizationRoleAssignmentRequest,
    OrganizationVerificationPreferencesUpdateRequest,
    VerificationReportCheckStatus,
    normalize_role_name,
)
from app.schemas.organization import OrganizationInvitationCreateRequest
from app.services.hr_v2_service import HRV2Service
from app.services.organization_service import OrganizationService
from app.services.trust_invitation_service import TrustInvitationService
from app.services.workspace_service import WorkspaceService
from app.verification_requests.enums import VerificationRequestStatus, VerificationRequestType


def _async_session():
    return SimpleNamespace(
        add=lambda _row: None,
        commit=AsyncMock(),
        flush=AsyncMock(),
        refresh=AsyncMock(),
    )


def _active_access():
    return (
        SimpleNamespace(id=uuid4(), public_id=uuid4(), suspended_at=None),
        SimpleNamespace(suspended_at=None, role=OrganizationRole.MEMBER),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("suspended_target", ["organization", "membership"])
async def test_suspended_managers_cannot_use_manager_mutations(suspended_target):
    service = OrganizationService.__new__(OrganizationService)
    organization, membership = _active_access()
    membership.role = OrganizationRole.OWNER
    target = organization if suspended_target == "organization" else membership
    target.suspended_at = datetime.now(tz=UTC)
    service.require_org_member = AsyncMock(return_value=(organization, membership))
    with pytest.raises(ForbiddenError, match="suspended"):
        await service.require_org_manager(uuid4(), organization.public_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("clear_role", [False, True])
async def test_partial_assignment_preserves_role_unless_explicitly_cleared(clear_role):
    service = HRV2Service.__new__(HRV2Service)
    service._session = _async_session()
    organization, membership = _active_access()
    role = SimpleNamespace(id=uuid4(), public_id=uuid4(), name="Engineer")
    service._session.get = AsyncMock(return_value=role)
    service._organizations = SimpleNamespace(
        require_org_member=AsyncMock(return_value=(organization, membership))
    )
    person = SimpleNamespace(
        public_id=uuid4(), role_id=role.id, department="Old", joining_date=None
    )
    service._locked_person = AsyncMock(return_value=person)
    fields = {"department": "New"}
    if clear_role:
        fields["role_id"] = None
    result = await service.assign_role(
        uuid4(),
        organization.public_id,
        person.public_id,
        OrganizationRoleAssignmentRequest(**fields),
    )
    assert person.role_id == (None if clear_role else role.id)
    assert result.role_id == (None if clear_role else role.public_id)
    assert result.department == "New"


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        return self._value


def test_ex_employee_requires_last_working_day() -> None:
    with pytest.raises(ValidationError, match="last_working_day is required"):
        EmployeeLifecycleUpdateRequest(employment_status="ex_employee")


def test_employee_lifecycle_rejects_invalid_date() -> None:
    with pytest.raises(ValidationError):
        EmployeeLifecycleUpdateRequest(
            employment_status="ex_employee",
            last_working_day="not-a-date",
        )


@pytest.mark.asyncio
async def test_employee_transition_is_atomic_and_preserves_related_state() -> None:
    service = HRV2Service.__new__(HRV2Service)
    service._session = _async_session()
    organization, membership = _active_access()
    service._organizations = SimpleNamespace(
        require_org_member=AsyncMock(return_value=(organization, membership))
    )
    person = SimpleNamespace(
        public_id=uuid4(),
        employment_status="active",
        joining_date=date(2022, 1, 1),
        last_working_day=None,
        relationship=OrganizationPersonRelationship.EMPLOYEE,
        updated_at=datetime.now(tz=UTC),
        notes=[object()],
        verification_requests=[object()],
        employments=[object()],
        passport_access_entries=[object()],
    )
    service._locked_person = AsyncMock(return_value=person)
    service._record_event = AsyncMock()

    result = await service.update_employee_lifecycle(
        uuid4(),
        organization.public_id,
        person.public_id,
        EmployeeLifecycleUpdateRequest(
            employment_status="ex_employee",
            last_working_day=date(2025, 1, 31),
        ),
    )

    assert result.employment_status == OrganizationPersonEmploymentStatus.EX_EMPLOYEE
    assert person.relationship == OrganizationPersonRelationship.FORMER_EMPLOYEE
    assert len(person.notes) == len(person.verification_requests) == len(person.employments) == 1
    assert len(person.passport_access_entries) == 1
    service._session.commit.assert_awaited_once()
    service._record_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_employee_transition_rejects_future_last_working_day() -> None:
    service = HRV2Service.__new__(HRV2Service)
    service._session = _async_session()
    organization, membership = _active_access()
    service._organizations = SimpleNamespace(
        require_org_member=AsyncMock(return_value=(organization, membership))
    )
    service._locked_person = AsyncMock(
        return_value=SimpleNamespace(
            employment_status="active",
            joining_date=None,
        )
    )

    with pytest.raises(ValidationAppError, match="cannot be in the future"):
        await service.update_employee_lifecycle(
            uuid4(),
            organization.public_id,
            uuid4(),
            EmployeeLifecycleUpdateRequest(
                employment_status="ex_employee",
                last_working_day=date.today() + timedelta(days=1),
            ),
        )


@pytest.mark.asyncio
async def test_employee_transition_rejects_exit_before_joining_date() -> None:
    service = HRV2Service.__new__(HRV2Service)
    service._session = _async_session()
    organization, membership = _active_access()
    service._organizations = SimpleNamespace(
        require_org_member=AsyncMock(return_value=(organization, membership))
    )
    service._locked_person = AsyncMock(
        return_value=SimpleNamespace(
            employment_status="active",
            joining_date=date(2025, 2, 1),
        )
    )

    with pytest.raises(ValidationAppError, match="cannot be before joining_date"):
        await service.update_employee_lifecycle(
            uuid4(),
            organization.public_id,
            uuid4(),
            EmployeeLifecycleUpdateRequest(
                employment_status="ex_employee",
                last_working_day=date(2025, 1, 31),
            ),
        )


@pytest.mark.asyncio
async def test_employee_lifecycle_hides_cross_org_person() -> None:
    service = HRV2Service.__new__(HRV2Service)
    service._session = _async_session()
    service._organizations = SimpleNamespace(
        require_org_member=AsyncMock(side_effect=NotFoundError("Organization not found"))
    )

    with pytest.raises(NotFoundError, match="Organization not found"):
        await service.update_employee_lifecycle(
            uuid4(),
            uuid4(),
            uuid4(),
            EmployeeLifecycleUpdateRequest(
                employment_status="ex_employee", last_working_day=date.today()
            ),
        )


@pytest.mark.asyncio
async def test_employee_reactivation_is_explicitly_unsupported_v1() -> None:
    service = HRV2Service.__new__(HRV2Service)
    service._session = _async_session()
    organization, membership = _active_access()
    service._organizations = SimpleNamespace(
        require_org_member=AsyncMock(return_value=(organization, membership))
    )
    service._locked_person = AsyncMock(
        return_value=SimpleNamespace(employment_status="ex_employee")
    )

    with pytest.raises(ConflictError, match="Reactivation is not supported"):
        await service.update_employee_lifecycle(
            uuid4(),
            organization.public_id,
            uuid4(),
            EmployeeLifecycleUpdateRequest(employment_status="active"),
        )


@pytest.mark.asyncio
async def test_suspended_membership_cannot_mutate_lifecycle() -> None:
    service = HRV2Service.__new__(HRV2Service)
    service._session = _async_session()
    organization, membership = _active_access()
    membership.suspended_at = datetime.now(tz=UTC)
    service._organizations = SimpleNamespace(
        require_org_member=AsyncMock(return_value=(organization, membership))
    )
    with pytest.raises(ForbiddenError, match="membership is suspended"):
        await service.update_employee_lifecycle(
            uuid4(),
            organization.public_id,
            uuid4(),
            EmployeeLifecycleUpdateRequest(
                employment_status="ex_employee", last_working_day=date.today()
            ),
        )


def test_job_role_normalization_is_case_and_whitespace_insensitive() -> None:
    assert normalize_role_name("  Senior   QA Executive ") == "senior qa executive"
    assert normalize_role_name("SENIOR QA EXECUTIVE") == "senior qa executive"


def test_role_assignment_requires_an_explicit_change() -> None:
    with pytest.raises(ValidationError, match="At least one employment profile field"):
        OrganizationRoleAssignmentRequest()
    assert OrganizationRoleAssignmentRequest(role_id=None).role_id is None


@pytest.mark.asyncio
async def test_role_lookup_is_organization_scoped() -> None:
    service = HRV2Service.__new__(HRV2Service)
    service._session = SimpleNamespace(execute=AsyncMock(return_value=_ScalarResult(None)))

    with pytest.raises(NotFoundError, match="job role not found"):
        await service._role(uuid4(), uuid4())


@pytest.mark.asyncio
async def test_role_deactivation_preserves_existing_assignments_and_count() -> None:
    now = datetime.now(tz=UTC)
    role = SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        name="QA Executive",
        description=None,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    organization = SimpleNamespace(id=uuid4())
    service = HRV2Service.__new__(HRV2Service)
    service._session = _async_session()
    service._organizations = SimpleNamespace(
        require_org_manager=AsyncMock(return_value=(organization, object()))
    )
    service._role = AsyncMock(return_value=role)
    service._record_event = AsyncMock()
    service._role_assignment_count = AsyncMock(return_value=3)

    response = await service.deactivate_role(uuid4(), uuid4(), role.public_id)

    assert role.is_active is False
    assert response.assigned_people_count == 3
    service._role_assignment_count.assert_awaited_once_with(role.id)


def test_role_uniqueness_is_scoped_to_organization() -> None:
    from app.models.organization_job_role import OrganizationJobRole

    unique = next(
        constraint
        for constraint in OrganizationJobRole.__table__.constraints
        if constraint.name == "uq_organization_job_roles_org_normalized_name"
    )
    assert [column.name for column in unique.columns] == ["organization_id", "normalized_name"]


@pytest.mark.asyncio
async def test_logo_upload_intent_uses_org_scoped_random_storage_key() -> None:
    added = []
    organization = SimpleNamespace(id=uuid4())
    service = HRV2Service.__new__(HRV2Service)
    service._session = SimpleNamespace(add=added.append, commit=AsyncMock())
    service._settings = SimpleNamespace(s3_document_key_prefix="private")
    service._organizations = SimpleNamespace(
        require_org_manager=AsyncMock(return_value=(organization, object()))
    )
    service._storage = SimpleNamespace(
        presign_put_url=AsyncMock(return_value=("https://signed.example.test/upload", 600))
    )

    response = await service.create_logo_upload_intent(
        uuid4(),
        uuid4(),
        OrganizationLogoUploadIntentRequest(content_type="image/png", byte_size=1234),
    )

    assert response.upload_url == "https://signed.example.test/upload"
    assert len(added) == 1
    assert f"/organizations/{organization.id}/logo/" in added[0].object_key
    assert added[0].object_key.endswith(".png")


@pytest.mark.asyncio
async def test_logo_rejects_svg_and_oversized_payloads() -> None:
    organization = SimpleNamespace(id=uuid4())
    service = HRV2Service.__new__(HRV2Service)
    service._session = _async_session()
    service._settings = SimpleNamespace(s3_document_key_prefix="private")
    service._organizations = SimpleNamespace(
        require_org_manager=AsyncMock(return_value=(organization, object()))
    )

    with pytest.raises(ValidationAppError, match="PNG, JPEG, or WEBP"):
        await service.create_logo_upload_intent(
            uuid4(),
            uuid4(),
            OrganizationLogoUploadIntentRequest(content_type="image/svg+xml", byte_size=100),
        )
    with pytest.raises(ValidationError):
        OrganizationLogoUploadIntentRequest(content_type="image/png", byte_size=5_000_001)


@pytest.mark.asyncio
async def test_logo_remove_clears_reference_and_deletes_only_previous_object() -> None:
    organization = SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        logo_object_key="private/organizations/org/logo/old.png",
        logo_content_type="image/png",
        logo_byte_size=120,
        updated_at=datetime.now(tz=UTC),
    )
    service = HRV2Service.__new__(HRV2Service)
    service._session = _async_session()
    service._organizations = SimpleNamespace(
        require_org_manager=AsyncMock(return_value=(organization, object()))
    )
    service._storage = SimpleNamespace(delete_object_best_effort=AsyncMock())
    service._record_event = AsyncMock()

    response = await service.remove_logo(uuid4(), uuid4())

    assert response.has_logo is False
    assert organization.logo_object_key is None
    service._storage.delete_object_best_effort.assert_awaited_once_with(
        object_key="private/organizations/org/logo/old.png"
    )


def test_verification_preferences_reject_unsupported_check() -> None:
    with pytest.raises(ValidationError, match="Unsupported verification preference"):
        OrganizationVerificationPreferencesUpdateRequest(
            checks={"identity": True, "police_clearance": True}
        )


def test_reference_count_requires_references_enabled() -> None:
    with pytest.raises(ValidationError, match="reference_count requires references"):
        OrganizationVerificationPreferencesUpdateRequest(
            checks={"references": False}, reference_count=2
        )


def test_preference_defaults_are_deterministic_and_future_read_safe() -> None:
    service = HRV2Service.__new__(HRV2Service)
    response = service._preferences_response(
        {"version": 2, "checks": {"identity": True, "future_check": True}}, None
    )
    assert response.version == 2
    assert response.checks["identity"] is True
    assert response.checks["employment"] is False
    assert response.checks["future_check"] is True


@pytest.mark.asyncio
async def test_preference_update_is_manager_protected_and_audited() -> None:
    organization = SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        verification_preferences={},
        updated_at=datetime.now(tz=UTC),
    )
    service = HRV2Service.__new__(HRV2Service)
    service._session = _async_session()
    service._organizations = SimpleNamespace(
        require_org_manager=AsyncMock(return_value=(organization, object()))
    )
    service._record_event = AsyncMock()
    payload = OrganizationVerificationPreferencesUpdateRequest(
        checks={"identity": True, "references": True}, reference_count=2
    )

    response = await service.update_preferences(uuid4(), organization.public_id, payload)

    assert response.checks["identity"] is True
    assert response.reference_count == 2
    service._organizations.require_org_manager.assert_awaited_once()
    service._record_event.assert_awaited_once()


def test_report_status_mapping_is_neutral_for_non_success() -> None:
    service = HRV2Service.__new__(HRV2Service)
    assert service._request_status(VerificationRequestStatus.VERIFIED) == "CONFIRMED"
    assert service._request_status(VerificationRequestStatus.REJECTED) == "REJECTED"
    assert (
        service._request_status(VerificationRequestStatus.AWAITING_INFORMATION)
        == "AWAITING_RESPONSE"
    )
    assert service._request_status(VerificationRequestStatus.IN_PROGRESS) == "PENDING"
    assert service._request_status(VerificationRequestStatus.UNABLE_TO_VERIFY) == "UNABLE_TO_VERIFY"


def test_report_not_ordered_and_discrepancy_precedence() -> None:
    service = HRV2Service.__new__(HRV2Service)
    assert service._aggregate_status([]) == VerificationReportCheckStatus.NOT_ORDERED
    assert (
        service._aggregate_status(
            [VerificationReportCheckStatus.CONFIRMED, VerificationReportCheckStatus.DISCREPANCY]
        )
        == VerificationReportCheckStatus.DISCREPANCY
    )


def test_report_privacy_masks_contacts_identifiers_and_coordinates() -> None:
    service = HRV2Service.__new__(HRV2Service)
    assert service._mask_email("candidate@example.com") == "c********@example.com"
    assert service._mask_phone("+91 98765 43210") == "***3210"
    assert service._mask_identifier("EMP-123456") == "***3456"
    assert (
        service._display_address(
            {
                "line1": "12 Example Road",
                "city": "Bengaluru",
                "latitude": 12.34,
                "longitude": 56.78,
                "target_encrypted": "secret",
                "target_key_id": "key",
            }
        )
        == "12 Example Road, Bengaluru"
    )


def test_report_contract_has_no_internal_notes_or_sensitive_provider_fields() -> None:
    from app.schemas.hr_v2 import VerificationReportResponse

    serialized_schema = str(VerificationReportResponse.model_json_schema()).lower()
    for forbidden in (
        "internal_notes",
        "aadhaar_number",
        "access_token",
        "provider_response",
        "latitude",
        "longitude",
        "ciphertext",
        "key_id",
        "private_s3_url",
    ):
        assert forbidden not in serialized_schema


@pytest.mark.asyncio
async def test_report_finality_trust_score_and_not_ordered_are_backend_derived() -> None:
    now = datetime.now(tz=UTC)
    organization, membership = _active_access()
    organization.name = "Kairo Labs"
    person = SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        full_name="Candidate Person",
        primary_email="candidate@example.test",
        primary_phone="+91 98765 43210",
        linked_user_id=uuid4(),
        job_role=SimpleNamespace(name="Software Engineer"),
        added_at=now - timedelta(days=2),
        updated_at=now,
    )
    request = SimpleNamespace(
        public_id=uuid4(),
        request_type=VerificationRequestType.IDENTITY,
        status=VerificationRequestStatus.VERIFIED,
        created_at=now - timedelta(days=1),
        updated_at=now,
        consented_at=now - timedelta(hours=20),
    )
    service = HRV2Service.__new__(HRV2Service)
    service._organizations = SimpleNamespace(
        require_org_member=AsyncMock(return_value=(organization, membership))
    )
    service._people = SimpleNamespace(get_by_public_id=AsyncMock(return_value=person))
    service._report_requests = AsyncMock(return_value=[request])
    service._latest_trust_score = AsyncMock(return_value=SimpleNamespace(overall_score=88))
    service._identity_items = AsyncMock(return_value=[])
    service._employment_items = lambda _requests: []
    service._education_items = lambda _requests: []
    service._reference_items = AsyncMock(return_value=[])
    service._address_items = AsyncMock(return_value=[])

    response = await service.get_verification_report(
        uuid4(), organization.public_id, person.public_id
    )

    assert response.header.report_status == "FINAL"
    assert response.header.trust_score == 88
    assert response.header.masked_email != person.primary_email
    summaries = {item.check: item.status for item in response.check_summaries}
    assert summaries["identity"] == "CONFIRMED"
    assert summaries["court_record_search"] == "NOT_ORDERED"
    assert response.open_items == []


@pytest.mark.asyncio
async def test_report_interim_open_items_and_cross_org_denial() -> None:
    service = HRV2Service.__new__(HRV2Service)
    service._organizations = SimpleNamespace(
        require_org_member=AsyncMock(side_effect=NotFoundError("Organization not found"))
    )
    with pytest.raises(NotFoundError, match="Organization not found"):
        await service.get_verification_report(uuid4(), uuid4(), uuid4())

    pending = SimpleNamespace(
        public_id=uuid4(),
        request_type=VerificationRequestType.EMPLOYMENT,
        status=VerificationRequestStatus.PENDING_SUBJECT_SUBMISSION,
    )
    open_items = service._open_items([pending])
    assert open_items[0].code == "AWAITING_RESPONSE"
    assert open_items[0].check == "employment"


def _team_invitation():
    now = datetime.now(tz=UTC)
    inviter = SimpleNamespace(email="owner@example.com", full_name="Owner User")
    organization = SimpleNamespace(id=uuid4(), public_id=uuid4(), name="Kairo Labs")
    return SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        organization_id=organization.id,
        organization=organization,
        invited_by_user=inviter,
        invitee_user_id=None,
        invitee_email="member@example.com",
        role=OrganizationRole.ADMIN,
        status=OrganizationInvitationStatus.PENDING,
        token_hash=None,
        token_version=0,
        token_expires_at=None,
        token_used_at=None,
        token_revoked_at=None,
        last_sent_at=None,
        delivery_failed_at=None,
        expires_at=now + timedelta(days=7),
        accepted_at=None,
        declined_at=None,
        cancelled_at=None,
    )


def test_team_invitation_token_is_hashed_and_rotated() -> None:
    service = OrganizationService.__new__(OrganizationService)
    invitation = _team_invitation()
    first = service._rotate_team_invitation_token(invitation)
    first_hash = invitation.token_hash
    second = service._rotate_team_invitation_token(invitation)

    assert len(first) >= 32
    assert first not in first_hash
    assert second != first
    assert invitation.token_hash != first_hash
    assert invitation.token_version == 2


@pytest.mark.asyncio
async def test_team_invitation_email_adapter_invoked_exactly_once() -> None:
    service = OrganizationService.__new__(OrganizationService)
    service._session = _async_session()
    service._settings = SimpleNamespace(hr_portal_base_url="https://hr.kairoid.com")
    service._email_delivery = SimpleNamespace(
        queue_template_email=AsyncMock(return_value=SimpleNamespace(status="queued"))
    )
    invitation = _team_invitation()
    raw_token = service._rotate_team_invitation_token(invitation)

    await service._deliver_team_invitation(invitation, raw_token)

    service._email_delivery.queue_template_email.assert_awaited_once()
    call = service._email_delivery.queue_template_email.await_args.kwargs
    assert call["template_key"] == "team_invitation"
    assert call["to_email"] == invitation.invitee_email
    assert call["template_data"]["invitation_url"].startswith(
        "https://hr.kairoid.com/team-invitations/accept?token="
    )
    assert raw_token not in str(call["template_data"].keys())


@pytest.mark.asyncio
async def test_team_invitation_email_failure_is_truthful() -> None:
    service = OrganizationService.__new__(OrganizationService)
    service._session = _async_session()
    service._settings = SimpleNamespace(hr_portal_base_url="https://hr.kairoid.com")
    service._email_delivery = SimpleNamespace(
        queue_template_email=AsyncMock(side_effect=RuntimeError("provider unavailable"))
    )
    invitation = _team_invitation()
    raw_token = service._rotate_team_invitation_token(invitation)

    with pytest.raises(ValidationAppError, match="email delivery failed"):
        await service._deliver_team_invitation(invitation, raw_token)
    assert invitation.delivery_failed_at is not None
    service._session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_used_team_invitation_token_is_denied() -> None:
    service = WorkspaceService.__new__(WorkspaceService)
    service._session = _async_session()
    invitation = _team_invitation()
    token_service = OrganizationService.__new__(OrganizationService)
    raw_token = token_service._rotate_team_invitation_token(invitation)
    invitation.token_used_at = datetime.now(tz=UTC)
    service._invitations = SimpleNamespace(get_by_token_hash=AsyncMock(return_value=invitation))

    with pytest.raises(ConflictError, match="already been used"):
        await service._resolve_team_token(raw_token, for_accept=True)


@pytest.mark.asyncio
async def test_expired_team_invitation_token_is_denied_and_revoked() -> None:
    service = WorkspaceService.__new__(WorkspaceService)
    service._session = _async_session()
    invitation = _team_invitation()
    token_service = OrganizationService.__new__(OrganizationService)
    raw_token = token_service._rotate_team_invitation_token(invitation)
    invitation.token_expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
    service._invitations = SimpleNamespace(get_by_token_hash=AsyncMock(return_value=invitation))

    with pytest.raises(ConflictError, match="expired"):
        await service._resolve_team_token(raw_token, for_accept=True)
    assert invitation.status == OrganizationInvitationStatus.EXPIRED
    assert invitation.token_revoked_at is not None


@pytest.mark.asyncio
async def test_invalid_and_revoked_team_invitation_tokens_are_denied() -> None:
    service = WorkspaceService.__new__(WorkspaceService)
    service._session = _async_session()
    service._invitations = SimpleNamespace(get_by_token_hash=AsyncMock(return_value=None))
    with pytest.raises(NotFoundError, match="not found"):
        await service._resolve_team_token("x" * 40)

    invitation = _team_invitation()
    token_service = OrganizationService.__new__(OrganizationService)
    raw_token = token_service._rotate_team_invitation_token(invitation)
    invitation.token_revoked_at = datetime.now(tz=UTC)
    service._invitations = SimpleNamespace(get_by_token_hash=AsyncMock(return_value=invitation))
    with pytest.raises(ConflictError, match="no longer actionable"):
        await service._resolve_team_token(raw_token, for_accept=True)


@pytest.mark.asyncio
async def test_team_invitation_acceptance_binds_email_and_creates_membership() -> None:
    actor_id = uuid4()
    user = SimpleNamespace(
        id=actor_id,
        email="member@example.com",
        active_organization_id=None,
    )
    invitation = _team_invitation()
    invitation.organization.public_id = uuid4()
    created = []

    async def add_member(membership):
        membership.public_id = uuid4()
        created.append(membership)
        return membership

    service = WorkspaceService.__new__(WorkspaceService)
    service._session = _async_session()
    service._require_user = AsyncMock(return_value=user)
    service._resolve_team_token = AsyncMock(return_value=invitation)
    service._organizations = SimpleNamespace(
        get_membership=AsyncMock(return_value=None),
        add_member=add_member,
    )

    response = await service.accept_team_invitation(actor_id, "x" * 40)

    assert len(created) == 1
    assert created[0].role == invitation.role
    assert invitation.token_used_at is not None
    assert invitation.status == OrganizationInvitationStatus.ACCEPTED
    assert response.membership_public_id == created[0].public_id


@pytest.mark.asyncio
async def test_team_invitation_acceptance_rejects_wrong_authenticated_email() -> None:
    invitation = _team_invitation()
    service = WorkspaceService.__new__(WorkspaceService)
    service._require_user = AsyncMock(
        return_value=SimpleNamespace(id=uuid4(), email="other@example.com")
    )
    service._resolve_team_token = AsyncMock(return_value=invitation)

    with pytest.raises(ForbiddenError, match="not assigned"):
        await service.accept_team_invitation(uuid4(), "x" * 40)


def test_team_invitation_cannot_grant_owner_role() -> None:
    with pytest.raises(ValidationError, match="owner role cannot be assigned"):
        OrganizationInvitationCreateRequest(
            invitee_email="member@example.com", role=OrganizationRole.OWNER
        )


def test_trust_invitation_defaults_map_without_retroactive_mutation() -> None:
    service = TrustInvitationService.__new__(TrustInvitationService)
    raw = {"version": 1, "checks": {"identity": True, "references": True}}
    snapshot = service._preference_snapshot(raw)
    types = service._verification_types_from_preferences(snapshot)
    raw["checks"]["identity"] = False

    assert {item.value for item in types} == {"identity", "professional_reference"}
    assert snapshot["checks"]["identity"] is True


def test_hr_v2_migration_is_single_successor_to_091() -> None:
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path

    path = Path(__file__).parents[1] / "alembic" / "versions" / "092_hr_v2_contracts.py"
    spec = spec_from_file_location("hr_v2_migration", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "092"
    assert module.down_revision == "091"


def test_openapi_exposes_additive_hr_v2_contracts() -> None:
    from app.main import app

    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/organizations/{org_public_id}/people/{person_public_id}/lifecycle": "patch",
        (
            "/api/v1/organizations/{org_public_id}/people/{person_public_id}/employment-profile"
        ): "patch",
        "/api/v1/organizations/{org_public_id}/job-roles": "get",
        "/api/v1/organizations/{org_public_id}/logo/upload-intents": "post",
        "/api/v1/organizations/{org_public_id}/verification-preferences": "put",
        (
            "/api/v1/organizations/{org_public_id}/people/{person_public_id}/verification-report"
        ): "get",
        "/api/v1/workspace/team-invitations/{token}": "get",
        "/api/v1/workspace/team-invitations/{token}/accept": "post",
    }
    for path, method in expected.items():
        assert method in paths[path]
