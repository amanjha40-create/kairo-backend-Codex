"""Focused Admin Operations V1.1 contract and persistence coverage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.admin_operations.enums import (
    CandidateClaimStatus,
    CourtCheckStatus,
    InPersonVerificationResult,
    InPersonVerificationType,
    ProfileProvenanceSource,
)
from app.auth.passwords import verify_password
from app.config import get_settings
from app.core.constants import Role
from app.core.permissions import ROLE_PERMISSIONS, Permission
from app.db.session import async_session_factory
from app.exceptions import ForbiddenError, NotFoundError, ValidationAppError
from app.integrations.email.renderer import EmailTemplateRenderer
from app.models.admin_profile_provenance import AdminProfileProvenance
from app.models.candidate_activation import CandidateActivationToken
from app.models.organization_invitation import OrganizationInvitation
from app.models.organization_member import OrganizationMember
from app.models.organization_person import OrganizationPerson
from app.models.user import User
from app.models.user_account_event import UserAccountEvent
from app.models.user_document import UserDocument
from app.organization.enums import OrganizationRole, OrganizationType
from app.schemas.admin_operations import (
    AdminCreateCandidateRequest,
    AdminFirstHRInvitationRequest,
    AdminOrganizationCreateRequest,
    AdminProfileMutationRequest,
    CandidateClaimRequest,
    CandidateProvenanceConfirmationItem,
    CandidateProvenanceConfirmationRequest,
    CourtCheckWriteRequest,
    InPersonVerificationCreateRequest,
)
from app.schemas.hr_v2 import VerificationReportCheckStatus
from app.services.admin_operations_service import (
    AdminOperationsConflict,
    AdminOperationsService,
)
from app.services.hr_v2_service import HRV2Service
from app.services.workspace_service import WorkspaceService


class _FakeEmailDelivery:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def queue_template_email(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(status="queued")


def _opaque_token(call: dict[str, object], key: str) -> str:
    data = call["template_data"]
    assert isinstance(data, dict)
    url = data[key]
    assert isinstance(url, str)
    return parse_qs(urlparse(url).query)["token"][0]


async def _user(*, role: Role = Role.USER, email_prefix: str = "user") -> User:
    user = User(
        email=f"{email_prefix}-{uuid4()}@example.com",
        full_name=f"{role.value.title()} Person",
        role=role.value,
        is_active=True,
    )
    return user


def test_admin_permissions_and_public_contracts_are_additive() -> None:
    expected = {
        Permission.CREATE_PERSON,
        Permission.MANAGE_ASSISTED_PROFILE,
        Permission.SEND_CANDIDATE_ACTIVATION,
        Permission.CREATE_ORGANIZATION,
        Permission.INVITE_FIRST_HR,
        Permission.MANAGE_COURT_CHECK,
        Permission.PERFORM_IN_PERSON_VERIFICATION,
    }
    assert expected <= ROLE_PERMISSIONS[Role.ADMIN]
    assert not expected.intersection(ROLE_PERMISSIONS[Role.USER])

    from app.main import app

    paths = app.openapi()["paths"]
    assert "/api/v1/admin/operations/candidates" in paths
    assert "/api/v1/candidate-activations/validate" in paths
    assert "/api/v1/candidate-activations/claim" in paths
    assert "/api/v1/admin/users/{id}/verify-all" not in paths
    assert all("permanent-address" not in path for path in paths if "in-person" in path)


def test_activation_email_audit_payload_never_contains_credential() -> None:
    rendered = EmailTemplateRenderer().render(
        template_key="candidate_account_activation",
        to_email="candidate@example.test",
        data={
            "candidate_name": "Candidate",
            "activation_url": "https://app.kairoid.com/activate-account?token=opaque-secret",
            "expires_at_iso": "2026-10-19T00:00:00+00:00",
        },
    )
    assert "opaque-secret" in rendered.text_body
    assert "opaque-secret" not in str(rendered.audit_payload)
    assert "activation_url" not in rendered.audit_payload


@pytest.mark.integration
@pytest.mark.asyncio
async def test_candidate_create_activation_resend_and_claim_lifecycle() -> None:
    email = _FakeEmailDelivery()
    settings = get_settings()
    async with async_session_factory() as session:
        admin = await _user(role=Role.ADMIN, email_prefix="admin-activation")
        session.add(admin)
        await session.commit()
        await session.refresh(admin)
        service = AdminOperationsService(session, settings, email_delivery=email)
        candidate_email = f"candidate-{uuid4()}@example.com"
        payload = AdminCreateCandidateRequest(
            full_name="Assisted Candidate",
            email=candidate_email,
            phone=f"+919{str(uuid4().int)[-9:]}",
            headline="Engineer",
            idempotency_key=uuid4(),
        )

        created = await service.create_candidate(admin.id, payload)
        assert created.claim_status == CandidateClaimStatus.ADMIN_CREATED_UNCLAIMED
        assert created.password_configured is False
        assert created.email_verified is False
        assert created.phone_verified is False
        stored = await session.get(User, created.candidate_id)
        assert stored is not None and stored.password_hash is None

        same_retry = await service.create_candidate(admin.id, payload)
        assert same_retry.candidate_id == created.candidate_id
        with pytest.raises(AdminOperationsConflict) as duplicate:
            await service.create_candidate(
                admin.id,
                payload.model_copy(update={"idempotency_key": uuid4()}),
            )
        assert duplicate.value.code == "candidate_unclaimed_exists"

        await service.send_candidate_activation(admin.id, created.candidate_id, resend=False)
        first_raw = _opaque_token(email.calls[-1], "activation_url")
        first = await session.scalar(
            select(CandidateActivationToken).where(
                CandidateActivationToken.user_id == created.candidate_id,
                CandidateActivationToken.revoked_at.is_(None),
            )
        )
        assert first is not None
        assert first_raw not in first.token_hash
        assert first.token_version == 1

        first.last_sent_at = datetime.now(tz=UTC) - timedelta(seconds=61)
        await session.commit()
        await service.send_candidate_activation(admin.id, created.candidate_id, resend=True)
        second_raw = _opaque_token(email.calls[-1], "activation_url")
        await session.refresh(first)
        second = await session.scalar(
            select(CandidateActivationToken).where(
                CandidateActivationToken.user_id == created.candidate_id,
                CandidateActivationToken.revoked_at.is_(None),
            )
        )
        assert first.revoked_at is not None
        assert second is not None and second.token_version == 2
        assert second_raw != first_raw
        with pytest.raises(AdminOperationsConflict):
            await service.validate_candidate_activation(first_raw)

        password = "Candidate-owned-password-2026!"
        claimed = await service.claim_candidate_account(
            CandidateClaimRequest(
                token=second_raw,
                password=password,
                confirm_password=password,
            )
        )
        assert claimed.claim_status == CandidateClaimStatus.CLAIMED
        assert claimed.email_verified is True
        assert claimed.phone_verified is False
        await session.refresh(stored)
        assert stored.password_hash is not None and verify_password(password, stored.password_hash)
        with pytest.raises(AdminOperationsConflict):
            await service.claim_candidate_account(
                CandidateClaimRequest(
                    token=second_raw,
                    password=password,
                    confirm_password=password,
                )
            )
        with pytest.raises(NotFoundError):
            await service.validate_candidate_activation("x" * 64)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_profile_provenance_confirmation_and_verified_field_protection() -> None:
    settings = get_settings()
    async with async_session_factory() as session:
        admin = await _user(role=Role.ADMIN, email_prefix="admin-profile")
        session.add(admin)
        await session.commit()
        await session.refresh(admin)
        service = AdminOperationsService(
            session, settings, email_delivery=_FakeEmailDelivery()
        )
        created = await service.create_candidate(
            admin.id,
            AdminCreateCandidateRequest(
                full_name="Profile Candidate",
                email=f"profile-{uuid4()}@example.com",
                idempotency_key=uuid4(),
            ),
        )
        updated = await service.update_candidate_profile(
            admin.id,
            created.candidate_id,
            AdminProfileMutationRequest(
                headline="Admin entered headline",
                source=ProfileProvenanceSource.ADMIN_ENTERED,
            ),
        )
        assert updated.candidate_confirmation_required is True
        confirmation = CandidateProvenanceConfirmationRequest(
            items=[
                CandidateProvenanceConfirmationItem(
                    record_type="profile",
                    record_id=created.candidate_id,
                    field_name="headline",
                )
            ]
        )
        confirmed = await service.confirm_candidate_provenance(
            created.candidate_id, confirmation
        )
        assert confirmed.confirmed_count == 1
        latest = await service._latest_provenance(
            created.candidate_id, "profile", created.candidate_id, "headline"
        )
        assert latest is not None
        assert latest.source == ProfileProvenanceSource.CANDIDATE_CONFIRMED.value

        session.add(
            AdminProfileProvenance(
                user_id=created.candidate_id,
                record_type="profile",
                record_id=created.candidate_id,
                field_name="headline",
                source=ProfileProvenanceSource.SOURCE_VERIFIED.value,
                value_hash="0" * 64,
                actor_user_id=admin.id,
                source_verified_at=datetime.now(tz=UTC),
            )
        )
        await session.commit()
        with pytest.raises(AdminOperationsConflict) as protected:
            await service.update_candidate_profile(
                admin.id,
                created.candidate_id,
                AdminProfileMutationRequest(headline="Lower confidence overwrite"),
            )
        assert protected.value.code == "source_verified_field_protected"

        outsider = await _user(email_prefix="outsider-confirm")
        session.add(outsider)
        await session.commit()
        await session.refresh(outsider)
        with pytest.raises(NotFoundError):
            await service.confirm_candidate_provenance(outsider.id, confirmation)

        batch = SimpleNamespace(
            id=uuid4(),
            review_session_id=uuid4(),
            imported_count=2,
            linked_count=1,
            skipped_count=0,
            failed_count=0,
        )
        await service.record_cv_import_audit(admin.id, created.candidate_id, batch)
        await service.record_cv_import_audit(admin.id, created.candidate_id, batch)
        audit_count = await session.scalar(
            select(func.count())
            .select_from(UserAccountEvent)
            .where(
                UserAccountEvent.user_id == created.candidate_id,
                UserAccountEvent.event_type == "admin_cv_import_confirmed",
            )
        )
        assert audit_count == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_admin_organization_first_hr_reuses_secure_team_invitation_acceptance() -> None:
    email = _FakeEmailDelivery()
    settings = get_settings()
    async with async_session_factory() as session:
        admin = await _user(role=Role.ADMIN, email_prefix="admin-org")
        hr_user = await _user(role=Role.HR, email_prefix="first-hr")
        wrong_user = await _user(role=Role.HR, email_prefix="wrong-hr")
        session.add_all([admin, hr_user, wrong_user])
        await session.commit()
        await session.refresh(admin)
        await session.refresh(hr_user)
        await session.refresh(wrong_user)
        service = AdminOperationsService(session, settings, email_delivery=email)
        org_payload = AdminOrganizationCreateRequest(
            name=f"Admin Provisioned {uuid4()}",
            organization_type=OrganizationType.EMPLOYER,
            idempotency_key=uuid4(),
        )
        created = await service.create_organization(admin.id, org_payload)
        assert created.lifecycle_state == "awaiting_first_hr_claim"
        assert created.owner_membership_present is False
        retried = await service.create_organization(admin.id, org_payload)
        assert retried.organization_public_id == created.organization_public_id

        invitation_payload = AdminFirstHRInvitationRequest(
            full_name=hr_user.full_name or "First HR",
            email=hr_user.email,
            role=OrganizationRole.OWNER,
        )
        invitation = await service.invite_first_hr(
            admin.id, created.organization_public_id, invitation_payload
        )
        first_raw = _opaque_token(email.calls[-1], "invitation_url")
        stored = await session.scalar(
            select(OrganizationInvitation).where(
                OrganizationInvitation.public_id == invitation.invitation_public_id
            )
        )
        assert stored is not None
        assert stored.invitee_name == hr_user.full_name
        assert first_raw not in (stored.token_hash or "")
        assert stored.role == OrganizationRole.OWNER

        resent = await service.invite_first_hr(
            admin.id,
            created.organization_public_id,
            invitation_payload,
            resend_invitation_public_id=invitation.invitation_public_id,
        )
        latest_raw = _opaque_token(email.calls[-1], "invitation_url")
        assert resent.invitation_public_id == invitation.invitation_public_id
        assert latest_raw != first_raw
        workspace = WorkspaceService(session)
        with pytest.raises(NotFoundError):
            await workspace.accept_team_invitation(hr_user.id, first_raw)
        with pytest.raises(ForbiddenError):
            await workspace.accept_team_invitation(wrong_user.id, latest_raw)

        accepted = await workspace.accept_team_invitation(hr_user.id, latest_raw)
        assert accepted.role == OrganizationRole.OWNER
        membership = await session.scalar(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == stored.organization_id,
                OrganizationMember.user_id == hr_user.id,
            )
        )
        assert membership is not None and membership.role == OrganizationRole.OWNER
        with pytest.raises(AdminOperationsConflict) as duplicate:
            await service.invite_first_hr(
                admin.id, created.organization_public_id, invitation_payload
            )
        assert duplicate.value.code == "first_hr_already_claimed"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_court_report_and_in_person_records_are_scoped_and_truthful() -> None:
    settings = get_settings()
    async with async_session_factory() as session:
        admin = await _user(role=Role.ADMIN, email_prefix="admin-court")
        candidate = await _user(email_prefix="court-candidate")
        hr_user = await _user(role=Role.HR, email_prefix="court-hr")
        session.add_all([admin, candidate, hr_user])
        await session.commit()
        for row in (admin, candidate, hr_user):
            await session.refresh(row)
        service = AdminOperationsService(
            session, settings, email_delivery=_FakeEmailDelivery()
        )
        organization_response = await service.create_organization(
            admin.id,
            AdminOrganizationCreateRequest(
                name=f"Court Scope {uuid4()}",
                organization_type=OrganizationType.EMPLOYER,
                idempotency_key=uuid4(),
            ),
        )
        organization = await service._admin_provisioned_organization(
            organization_response.organization_public_id
        )
        person = OrganizationPerson(
            organization_id=organization.id,
            linked_user_id=candidate.id,
            full_name="Court Candidate",
            primary_email=candidate.email,
            added_by_user_id=admin.id,
        )
        membership = OrganizationMember(
            organization_id=organization.id,
            user_id=hr_user.id,
            role=OrganizationRole.OWNER,
        )
        evidence = UserDocument(
            user_id=candidate.id,
            document_type="other",
            object_key=f"test/court/{uuid4()}.pdf",
            original_filename="court-record.pdf",
            content_type="application/pdf",
            byte_size=1024,
            checksum_sha256="a" * 64,
            verification_status="pending",
        )
        other_evidence = UserDocument(
            user_id=hr_user.id,
            document_type="other",
            object_key=f"test/court/{uuid4()}.pdf",
            original_filename="other.pdf",
            content_type="application/pdf",
            byte_size=1024,
            checksum_sha256="b" * 64,
            verification_status="pending",
        )
        session.add_all([person, membership, evidence, other_evidence])
        await session.commit()
        for row in (person, evidence, other_evidence):
            await session.refresh(row)

        with pytest.raises(ValidationAppError) as invalid_evidence:
            await service.create_court_check(
                admin.id,
                organization.public_id,
                person.public_id,
                CourtCheckWriteRequest(
                    status=CourtCheckStatus.PENDING,
                    jurisdiction="Delhi District Courts",
                    coverage="Publicly accessible indexed records",
                    source="Court index",
                    limitations="Sealed and unavailable records are excluded.",
                    evidence_document_ids=[other_evidence.id],
                    idempotency_key=uuid4(),
                ),
            )
        assert invalid_evidence.value.code == "invalid_evidence_association"

        searched_at = datetime.now(tz=UTC)
        check = await service.create_court_check(
            admin.id,
            organization.public_id,
            person.public_id,
            CourtCheckWriteRequest(
                status=CourtCheckStatus.NO_MATCH_FOUND,
                searched_at=searched_at,
                jurisdiction="Delhi District Courts",
                coverage="Publicly accessible indexed records",
                search_period="2016-2026",
                source="Court index queried by reviewer",
                limitations="Sealed, non-indexed, and unavailable records are excluded.",
                evidence_document_ids=[evidence.id],
                idempotency_key=uuid4(),
            ),
        )
        assert check.status == CourtCheckStatus.NO_MATCH_FOUND
        assert "not police verification" in check.semantic_notice
        draft_report = await HRV2Service(session, settings).get_verification_report(
            hr_user.id, organization.public_id, person.public_id
        )
        assert draft_report.court_search[0].status == VerificationReportCheckStatus.PENDING
        finalized = await service.finalize_court_check(
            admin.id, organization.public_id, person.public_id, check.public_id
        )
        assert finalized.finalized_at is not None

        report = await HRV2Service(session, settings).get_verification_report(
            hr_user.id, organization.public_id, person.public_id
        )
        assert report.court_search[0].status == VerificationReportCheckStatus.CONFIRMED
        assert report.court_search[0].source == "Court index queried by reviewer"
        assert report.court_search[0].evidence_id == evidence.id
        assert "No match found within the stated court-record scope" == (
            report.court_search[0].finding
        )
        assert next(
            item for item in report.check_summaries if item.check == "court_record_search"
        ).status == VerificationReportCheckStatus.CONFIRMED

        in_person_payload = InPersonVerificationCreateRequest(
            verification_type=InPersonVerificationType.IDENTITY_OBSERVATION,
            performed_at=searched_at,
            person_met="Candidate",
            relationship="Self",
            result=InPersonVerificationResult.OBSERVED_CONSISTENT,
            notes="Observed identity document; no canonical verification status changed.",
            evidence_document_ids=[evidence.id],
            idempotency_key=uuid4(),
        )
        observed = await service.record_in_person_verification(
            admin.id, organization.public_id, person.public_id, in_person_payload
        )
        repeated = await service.record_in_person_verification(
            admin.id, organization.public_id, person.public_id, in_person_payload
        )
        assert repeated.public_id == observed.public_id
        assert observed.method == "in_person"
        assert observed.changes_canonical_verification_status is False
        assert observed.permanent_address_check_credit == 0


def test_migration_093_is_the_single_linear_successor_to_092() -> None:
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path

    path = Path(__file__).parents[1] / "alembic" / "versions" / (
        "093_admin_operations_v1_1_contracts.py"
    )
    spec = spec_from_file_location("admin_operations_migration", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "093"
    assert module.down_revision == "092"
