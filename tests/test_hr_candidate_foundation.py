"""Focused contracts for the HR-to-Candidate foundation in DB097."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.exceptions import ConflictError
from app.main import app
from app.organization.enums import OrganizationRole
from app.schemas.hr_v2 import (
    FormerEmployeeCorrectionCreateRequest,
    OrganizationJobRoleCreateRequest,
)
from app.schemas.organization import OrganizationInvitationCreateRequest
from app.schemas.trust_invitation import (
    CandidateInvitationHomeSummary,
    CandidateTrustInvitationResponse,
    TrustInvitationCreateRequest,
    TrustInvitationRequirementProgress,
)
from app.services.hr_v2_service import HRV2Service
from app.services.trust_invitation_service import TrustInvitationService
from app.trust_invitations.enums import TrustInvitationVerificationType


def _service() -> TrustInvitationService:
    service = TrustInvitationService.__new__(TrustInvitationService)
    service._settings = SimpleNamespace(jwt_secret_key="foundation-test-secret")
    return service


def test_requirement_snapshot_preserves_mandatory_optional_and_configuration() -> None:
    payload = TrustInvitationCreateRequest(
        subject_name="Candidate",
        subject_email="candidate@example.com",
        expires_at=datetime.now(tz=UTC) + timedelta(days=2),
        requirements=[
            {
                "requirement_type": "identity",
                "mandatory": True,
                "configuration": {"document": "pan"},
            },
            {
                "requirement_type": "education",
                "mandatory": False,
                "configuration": {"minimum_records": 1},
            },
        ],
    )

    snapshot = _service()._requirements_snapshot(payload.requirements, [])

    assert snapshot == [
        {"type": "identity", "mandatory": True, "configuration": {"document": "pan"}},
        {
            "type": "education",
            "mandatory": False,
            "configuration": {"minimum_records": 1},
        },
    ]


def test_duplicate_requirement_types_are_rejected() -> None:
    with pytest.raises(ValidationError, match="Requirement types must be unique"):
        TrustInvitationCreateRequest(
            subject_name="Candidate",
            subject_email="candidate@example.com",
            expires_at=datetime.now(tz=UTC) + timedelta(days=2),
            requirements=[
                {"requirement_type": "identity"},
                {"requirement_type": "identity", "mandatory": False},
            ],
        )


def test_share_scope_rejects_missing_mandatory_and_allows_missing_optional() -> None:
    service = _service()
    invitation = SimpleNamespace(
        requirements_snapshot=[
            {"type": "identity", "mandatory": True, "configuration": {}},
            {"type": "education", "mandatory": False, "configuration": {}},
        ],
        requested_verification_types=[],
    )

    with pytest.raises(ConflictError, match="excludes mandatory"):
        service._assert_share_scope(invitation, SimpleNamespace(permissions={}))

    service._assert_share_scope(
        invitation,
        SimpleNamespace(permissions={"include_profile": True}),
    )


def test_invitation_url_uses_canonical_https_route_without_email() -> None:
    invitation_id = uuid4()
    url = _service()._build_invitation_url(invitation_id)

    assert url.startswith("https://kairoid.com/invite/v2.")
    assert "candidate@" not in url


@pytest.mark.asyncio
async def test_requirement_progress_reuses_current_durable_records() -> None:
    now = datetime.now(tz=UTC)
    session = SimpleNamespace(
        scalars=AsyncMock(
            return_value=SimpleNamespace(
                all=lambda: [
                    SimpleNamespace(
                        integrity_result="verified",
                        match_result="VERIFIED_MATCH",
                        verified_at=now,
                        profile_revision_at=now,
                        document_valid_until=None,
                    )
                ]
            )
        ),
        scalar=AsyncMock(side_effect=[1, 1, 0, 2, uuid4()]),
    )
    service = _service()
    service._session = session
    invitation = SimpleNamespace(
        requirements_snapshot=[
            {"type": "identity", "mandatory": True, "configuration": {}},
            {"type": "employment", "mandatory": True, "configuration": {}},
            {"type": "education", "mandatory": True, "configuration": {}},
            {"type": "certification", "mandatory": False, "configuration": {}},
            {
                "type": "professional_reference",
                "mandatory": True,
                "configuration": {"minimum_count": 2},
            },
            {"type": "permanent_address", "mandatory": True, "configuration": {}},
        ],
        requested_verification_types=[],
    )
    user = SimpleNamespace(id=uuid4(), updated_at=now)

    progress = await service._requirement_progress(invitation, user)

    assert [item.status for item in progress] == [
        "completed",
        "completed",
        "completed",
        "action_required",
        "completed",
        "completed",
    ]
    assert progress[3].action == "OPEN_CERTIFICATION"
    assert progress[5].action is None


@pytest.mark.asyncio
async def test_home_summary_uses_actionable_invitation_progress() -> None:
    service = _service()
    now = datetime.now(tz=UTC)
    ready = CandidateTrustInvitationResponse(
        public_id=uuid4(),
        organization_public_id=uuid4(),
        organization_name="Kairo",
        purpose=None,
        message=None,
        lifecycle_state="accepted",
        requirements_version=1,
        requirements=[
            TrustInvitationRequirementProgress(
                requirement_type=TrustInvitationVerificationType.IDENTITY,
                mandatory=True,
                status="completed",
            )
        ],
        completed_requirements=1,
        required_requirements=1,
        accepted_at=now,
        declined_at=None,
        completed_at=None,
        expires_at=now + timedelta(days=1),
    )
    needs_action = ready.model_copy(
        update={
            "public_id": uuid4(),
            "requirements": [
                TrustInvitationRequirementProgress(
                    requirement_type=TrustInvitationVerificationType.EMPLOYMENT,
                    mandatory=True,
                    status="action_required",
                    action="OPEN_EMPLOYMENT",
                )
            ],
            "completed_requirements": 0,
        }
    )
    service.list_my = AsyncMock(return_value=[ready, needs_action])

    result: CandidateInvitationHomeSummary = await service.home_summary(uuid4())

    assert result.pending_invitation_count == 2
    assert result.action_required_invitation_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("member_role", "mode", "expected_status"),
    [
        (OrganizationRole.ADMIN, "submit", "active"),
        (OrganizationRole.MEMBER, "submit", "pending_approval"),
        (OrganizationRole.ADMIN, "draft", "draft"),
    ],
)
async def test_hiring_role_creation_respects_approval_policy(
    member_role: OrganizationRole, mode: str, expected_status: str
) -> None:
    captured = []
    session = SimpleNamespace(
        add=captured.append,
        flush=AsyncMock(),
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )
    organization = SimpleNamespace(id=uuid4(), public_id=uuid4(), suspended_at=None)
    membership = SimpleNamespace(role=member_role, suspended_at=None)
    service = HRV2Service.__new__(HRV2Service)
    service._session = session
    service._organizations = SimpleNamespace(
        require_org_member=AsyncMock(return_value=(organization, membership))
    )
    service._assert_unique_role_name = AsyncMock()
    service._record_event = AsyncMock()
    service._role_response = lambda role, _count: SimpleNamespace(status=role.status)

    result = await service.create_role(
        uuid4(),
        organization.public_id,
        OrganizationJobRoleCreateRequest(name="Finance Analyst", mode=mode),
    )

    assert result.status == expected_status
    assert captured[0].is_active is (expected_status == "active")


def test_team_invitation_contract_preserves_name_and_message() -> None:
    payload = OrganizationInvitationCreateRequest(
        invitee_email="member@example.com",
        invitee_name="Team Member",
        personal_message="Welcome to the hiring team.",
        role="member",
    )

    assert payload.invitee_name == "Team Member"
    assert payload.personal_message == "Welcome to the hiring team."


def test_former_employee_correction_rejects_non_historical_fields() -> None:
    with pytest.raises(ValidationError, match="historical employment fields"):
        FormerEmployeeCorrectionCreateRequest(
            proposed_changes={"full_name": "Changed"},
            reason="Correction requested",
        )


def test_migration_097_is_additive_and_reversible() -> None:
    path = Path(__file__).parents[1] / "alembic/versions/097_hr_candidate_foundation.py"
    spec = importlib.util.spec_from_file_location("migration_097", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = path.read_text()

    assert module.revision == "097"
    assert module.down_revision == "096"
    for field in (
        "requirements_snapshot",
        "passport_share_link_id",
        "personal_message",
        "organization_person_corrections",
    ):
        assert field in source
    assert "def downgrade" in source


def test_openapi_exposes_candidate_and_hr_foundation_routes() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/candidate/trust-invitations" in paths
    assert "/api/v1/candidate/trust-invitations/home-summary" in paths
    assert "/api/v1/candidate/trust-invitations/{trust_invitation_public_id}/finalize" in paths
    assert "/api/v1/organizations/{org_public_id}/job-roles/{role_public_id}/approve" in paths
    assert (
        "/api/v1/organizations/{org_public_id}/people/corrections/"
        "{correction_public_id}/approve"
    ) in paths
