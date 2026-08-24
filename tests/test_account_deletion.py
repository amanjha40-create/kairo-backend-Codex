from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, or_, select

from app.admin_review.enums import VerificationRequestEvidenceStatus
from app.config import get_settings
from app.core.constants import Role, SignupKind
from app.db.session import async_session_factory
from app.exceptions import ForbiddenError, NotFoundError, UnauthorizedError, ValidationAppError
from app.models import (
    Certification,
    EmailDeliveryLog,
    Employment,
    EmploymentDocument,
    FreelanceContract,
    FreelanceContractDocument,
    GigPlatform,
    InstitutionPersonConsent,
    Internship,
    InternshipDocument,
    Notification,
    NotificationPreference,
    Organization,
    OrganizationMember,
    OrganizationPerson,
    PassportShareLink,
    PasswordResetToken,
    PendingSignup,
    PortfolioItem,
    ProfileLanguage,
    ProfileLink,
    Project,
    RefreshToken,
    ResumeDocument,
    ResumeImportBatch,
    ResumeImportResult,
    ResumeParsedResult,
    ResumeProcessingJob,
    ResumeRecordProvenance,
    ResumeReviewItem,
    ResumeReviewSession,
    Skill,
    TrustInvitation,
    TrustScoreSnapshot,
    User,
    UserDocument,
    UserSocialAccount,
    VerificationContact,
    VerificationRequest,
    VerificationRequestEvidence,
)
from app.organization.enums import OrganizationRole, OrganizationType, OrganizationVerificationState
from app.organization_people.enums import OrganizationPersonPassportStatusSummary
from app.schemas.account_deletion import AccountDeletionRequest
from app.schemas.auth import RegisterRequest
from app.services.account_deletion_service import AccountDeletionService
from app.trust_invitations.enums import (
    TrustInvitationDeliveryMethod,
    TrustInvitationDeliveryState,
    TrustInvitationStatus,
)
from app.verification_requests.enums import (
    VerificationContactReviewStatus,
    VerificationContactType,
    VerificationRequestOriginType,
    VerificationRequestStatus,
    VerificationRequestType,
)


class _FakeDeletionService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def delete_candidate_account(
        self, actor_user_id, payload: AccountDeletionRequest
    ) -> None:  # noqa: ANN001
        self.calls.append((str(actor_user_id), payload.current_password))
        assert payload.confirm == "DELETE"


class _FakeRedis:
    def __init__(self) -> None:
        self.deleted_keys: list[str] = []

    async def delete(self, key: str) -> None:
        self.deleted_keys.append(key)


class _RecordingS3Client:
    def __init__(self) -> None:
        self.deleted: list[tuple[str, str]] = []

    def delete_object(self, *, Bucket: str, Key: str) -> None:  # noqa: N803
        self.deleted.append((Bucket, Key))


def _hash_password(plain: str) -> str:
    from app.auth.passwords import hash_password

    return hash_password(plain)


async def _candidate_user():
    from app.api.dependencies.auth import CurrentUser

    return CurrentUser(
        id=uuid4(),
        email="candidate@example.com",
        role=Role.USER.value,
        full_name="Candidate User",
    )


async def _make_candidate(
    session,
    *,
    email: str | None = None,
    phone: str | None = None,
    password: str = "CandidatePass123!",
    full_name: str = "Delete Me",
) -> User:
    candidate = User(
        email=email or f"candidate-{uuid4()}@example.com",
        password_hash=_hash_password(password),
        full_name=full_name,
        profile_slug=f"candidate-{uuid4().hex[:8]}",
        phone=phone or f"+91999{uuid4().int % 10000000:07d}",
        role=Role.USER.value,
        is_active=True,
        email_verified_at=datetime.now(tz=UTC),
        phone_verified_at=datetime.now(tz=UTC),
    )
    session.add(candidate)
    await session.flush()
    return candidate


@pytest.mark.asyncio
async def test_delete_me_route_returns_204_and_delegates() -> None:
    from httpx import ASGITransport, AsyncClient

    from app.api.dependencies.auth import get_current_user
    from app.api.dependencies.services import get_account_deletion_service
    from app.main import app

    fake = _FakeDeletionService()
    app.dependency_overrides[get_current_user] = _candidate_user
    app.dependency_overrides[get_account_deletion_service] = lambda: fake
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.request(
                "DELETE",
                "/api/v1/users/me",
                json={"confirm": "DELETE", "current_password": "StrongPass123!"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204
    assert fake.calls
    assert fake.calls[0][1] == "StrongPass123!"


@pytest.mark.asyncio
async def test_delete_me_route_requires_authentication() -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.request(
            "DELETE",
            "/api/v1/users/me",
            json={"confirm": "DELETE", "current_password": "StrongPass123!"},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.integration
async def test_account_deletion_rejects_wrong_confirmation() -> None:
    settings = get_settings()
    candidate_id = None

    try:
        async with async_session_factory() as session:
            candidate = await _make_candidate(session)
            candidate_id = candidate.id
            await session.commit()

            service = AccountDeletionService(session, settings, _FakeRedis())
            with pytest.raises(ValidationAppError):
                await service.delete_candidate_account(
                    candidate.id,
                    AccountDeletionRequest(confirm="ERASE", current_password="CandidatePass123!"),
                )

        async with async_session_factory() as assert_session:
            candidate = await assert_session.get(User, candidate_id)
            assert candidate is not None
            assert candidate.deleted_at is None
            assert candidate.is_active is True
    finally:
        async with async_session_factory() as cleanup:
            if candidate_id is not None:
                await cleanup.execute(delete(User).where(User.id == candidate_id))
            await cleanup.commit()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_account_deletion_rejects_wrong_password() -> None:
    settings = get_settings()
    candidate_id = None

    try:
        async with async_session_factory() as session:
            candidate = await _make_candidate(session)
            candidate_id = candidate.id
            await session.commit()

            service = AccountDeletionService(session, settings, _FakeRedis())
            with pytest.raises(UnauthorizedError):
                await service.delete_candidate_account(
                    candidate.id,
                    AccountDeletionRequest(confirm="DELETE", current_password="WrongPass123!"),
                )

        async with async_session_factory() as assert_session:
            candidate = await assert_session.get(User, candidate_id)
            assert candidate is not None
            assert candidate.deleted_at is None
            assert candidate.is_active is True
    finally:
        async with async_session_factory() as cleanup:
            if candidate_id is not None:
                await cleanup.execute(delete(User).where(User.id == candidate_id))
            await cleanup.commit()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_account_deletion_erases_candidate_data_and_scrubs_shared_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    original_bucket = settings.s3_documents_bucket
    settings.s3_documents_bucket = "test-private-bucket"
    s3_client = _RecordingS3Client()
    monkeypatch.setattr(
        "app.services.account_deletion_service.get_s3_client", lambda _settings: s3_client
    )

    now = datetime.now(tz=UTC)
    actor_id = None
    org_user_id = None
    org_id = None
    expected_deleted_keys: set[str] = set()
    purgeable_request_id = None
    retained_request_id = None

    try:
        async with async_session_factory() as session:
            org_user = User(
                email=f"deleter-org-{uuid4()}@example.invalid",
                password_hash=_hash_password("OrgOwnerPass123!"),
                full_name="Org Owner",
                role=Role.HR.value,
                is_active=True,
                email_verified_at=now,
            )
            candidate = User(
                email=f"delete-me-{uuid4()}@example.invalid",
                password_hash=_hash_password("CandidatePass123!"),
                full_name="Delete Me",
                profile_slug=f"delete-me-{uuid4().hex[:8]}",
                phone=f"+91999{uuid4().int % 10000000:07d}",
                role=Role.USER.value,
                is_active=True,
                email_verified_at=now,
                phone_verified_at=now,
                avatar_key=f"avatars/{uuid4()}.png",
            )
            session.add_all([org_user, candidate])
            await session.flush()
            org_user_id = org_user.id
            actor_id = candidate.id
            if candidate.avatar_key:
                expected_deleted_keys.add(candidate.avatar_key)

            organization = Organization(
                created_by_user_id=org_user.id,
                name="Synthetic Employer",
                organization_type=OrganizationType.EMPLOYER,
                verification_state=OrganizationVerificationState.VERIFIED,
                work_email="hr@synthetic.example",
                domain="synthetic.example",
            )
            session.add(organization)
            await session.flush()
            org_id = organization.id

            person = OrganizationPerson(
                organization_id=organization.id,
                linked_user_id=candidate.id,
                full_name=candidate.full_name or "Delete Me",
                primary_email=candidate.email,
                relationship="candidate",
                lifecycle_status="active",
                trust_state="unknown",
                invitation_status_summary="accepted",
                verification_status_summary="not_started",
                passport_status_summary=OrganizationPersonPassportStatusSummary.ACTIVE,
                added_by_user_id=org_user.id,
            )
            session.add(person)
            await session.flush()

            session.add(
                InstitutionPersonConsent(
                    organization_id=organization.id,
                    organization_person_id=person.id,
                    subject_user_id=candidate.id,
                    allowed_fields=["employment_history"],
                    consent_version="v1",
                    granted_at=now,
                )
            )

            purgeable_employment = Employment(
                created_by_user_id=candidate.id,
                subject_full_name=candidate.full_name or "Delete Me",
                subject_email=candidate.email,
                employer_legal_name="Draft Corp",
                job_title="Analyst",
                employment_type="full_time",
                verification_method="document",
                verification_status="draft",
            )
            retained_employment = Employment(
                created_by_user_id=candidate.id,
                subject_full_name=candidate.full_name or "Delete Me",
                subject_email=candidate.email,
                employer_legal_name="Retained Corp",
                job_title="Manager",
                employment_type="full_time",
                verification_method="document",
                verification_status="approved",
            )
            session.add_all([purgeable_employment, retained_employment])
            await session.flush()

            user_document = UserDocument(
                user_id=candidate.id,
                document_type="passport",
                object_key=f"user-documents/{candidate.id}/{uuid4()}.pdf",
                original_filename="passport.pdf",
                content_type="application/pdf",
                byte_size=1234,
                checksum_sha256="a" * 64,
            )
            employment_document = EmploymentDocument(
                employment_id=retained_employment.id,
                uploaded_by_user_id=candidate.id,
                document_type="offer_letter",
                object_key=f"employment-documents/{candidate.id}/{uuid4()}.pdf",
                original_filename="offer.pdf",
                content_type="application/pdf",
                byte_size=4321,
                checksum_sha256="b" * 64,
            )
            session.add_all([user_document, employment_document])
            await session.flush()
            expected_deleted_keys.update({user_document.object_key, employment_document.object_key})

            retained_request = VerificationRequest(
                origin_type=VerificationRequestOriginType.SUBJECT_INITIATED,
                organization_id=organization.id,
                organization_person_id=person.id,
                subject_user_id=candidate.id,
                employment_id=retained_employment.id,
                subject_name=candidate.full_name or "Delete Me",
                subject_email=candidate.email,
                target_organization_name="Retained Corp",
                target_organization_email="hr@retained.example",
                request_type=VerificationRequestType.EMPLOYMENT,
                status=VerificationRequestStatus.VERIFIED,
                requested_by_user_id=candidate.id,
                consented_fields=["job_title", "employment_dates"],
                consented_evidence_scope=["offer_letter"],
                candidate_response="This note should be scrubbed",
                candidate_response_submitted_at=now,
            )
            purgeable_request = VerificationRequest(
                origin_type=VerificationRequestOriginType.SUBJECT_INITIATED,
                organization_id=organization.id,
                subject_user_id=candidate.id,
                employment_id=purgeable_employment.id,
                subject_name=candidate.full_name or "Delete Me",
                subject_email=candidate.email,
                target_organization_name="Draft Corp",
                target_organization_email="hr@draft.example",
                request_type=VerificationRequestType.EMPLOYMENT,
                status=VerificationRequestStatus.DRAFT,
                requested_by_user_id=candidate.id,
            )
            session.add_all([retained_request, purgeable_request])
            await session.flush()
            retained_request_id = retained_request.id
            purgeable_request_id = purgeable_request.id

            session.add(
                VerificationContact(
                    verification_request_id=retained_request.id,
                    contact_name="Verifier",
                    contact_email="verifier@retained.example",
                    contact_role="HR",
                    contact_type=VerificationContactType.HR,
                    candidate_note="Please verify quietly",
                    submitted_by_user_id=candidate.id,
                    review_status=VerificationContactReviewStatus.PENDING,
                )
            )
            session.add(
                VerificationRequestEvidence(
                    verification_request_id=retained_request.id,
                    submitted_by_user_id=candidate.id,
                    evidence_type="document",
                    field_key="offer_letter",
                    document_id=user_document.id,
                    employment_document_id=employment_document.id,
                    value={"candidate_comment": "private"},
                    status=VerificationRequestEvidenceStatus.SUBMITTED,
                )
            )

            invitation = TrustInvitation(
                organization_id=organization.id,
                organization_person_id=person.id,
                subject_name=candidate.full_name or "Delete Me",
                subject_email=candidate.email,
                subject_phone=candidate.phone,
                purpose="Verification",
                requested_verification_types=["employment"],
                token_hash=f"{uuid4().hex}{uuid4().hex}",
                status=TrustInvitationStatus.ACCEPTED,
                delivery_method=TrustInvitationDeliveryMethod.EMAIL,
                delivery_state=TrustInvitationDeliveryState.DELIVERED,
                created_by_user_id=org_user.id,
                accepted_by_user_id=candidate.id,
                expires_at=now + timedelta(days=7),
                accepted_at=now,
            )
            session.add(invitation)

            certification_key = f"certifications/{candidate.id}/{uuid4()}.pdf"
            portfolio_key = f"portfolio/{candidate.id}/{uuid4()}.pdf"
            internship_key = f"internships/{candidate.id}/{uuid4()}.pdf"
            freelance_key = f"freelance/{candidate.id}/{uuid4()}.pdf"
            session.add_all(
                [
                    PendingSignup(
                        email=candidate.email,
                        phone=candidate.phone,
                        password_hash=_hash_password("CandidatePass123!"),
                        full_name=candidate.full_name,
                        signup_kind=SignupKind.CANDIDATE,
                        expires_at=now + timedelta(hours=12),
                        completed_user_id=candidate.id,
                        completed_at=now,
                    ),
                    RefreshToken(
                        user_id=candidate.id,
                        token_hash=f"{uuid4().hex}{uuid4().hex}",
                        expires_at=now + timedelta(days=7),
                        family_id=uuid4(),
                    ),
                    PasswordResetToken(
                        user_id=candidate.id,
                        token_hash=f"{uuid4().hex}{uuid4().hex}",
                        expires_at=now + timedelta(hours=1),
                    ),
                    ProfileLanguage(user_id=candidate.id, language="English", proficiency="native"),
                    ProfileLink(
                        user_id=candidate.id,
                        link_type="linkedin",
                        url="https://example.com/candidate",
                    ),
                    NotificationPreference(
                        user_id=candidate.id,
                        event_type="verification_completed",
                        enabled=True,
                        preferred_channels=["email"],
                    ),
                    Notification(
                        notification_type="transactional",
                        event_type="verification_completed",
                        title="Verification complete",
                        body="Completed",
                        status="sent",
                        recipient_user_id=candidate.id,
                        recipient_email=candidate.email,
                        channel="email",
                        template_key="verification_completed",
                        template_version="v1",
                        payload={"subject_name": candidate.full_name},
                        metadata_payload={},
                    ),
                    EmailDeliveryLog(
                        template_key="verification_completed",
                        template_version="v1",
                        recipient_email=candidate.email,
                        recipient_user_id=candidate.id,
                        provider="console",
                        status="sent",
                        payload={"subject_name": candidate.full_name},
                    ),
                        PassportShareLink(
                            owner_user_id=candidate.id,
                            label="Public share",
                            token_hash=f"{uuid4().hex}{uuid4().hex}",
                            permissions={"employment": True},
                        ),
                    TrustScoreSnapshot(
                        user_id=candidate.id,
                        score_version="v1",
                        status="ready",
                        overall_score=72,
                        verification_completeness_percentage=80,
                        domain_scores={"employment": 40},
                        positive_contributors=[],
                        negative_contributors=[],
                        critical_overrides=[],
                    ),
                    UserSocialAccount(
                        user_id=candidate.id,
                        provider="google",
                        provider_user_id=f"google-{uuid4()}",
                        provider_email=candidate.email,
                    ),
                    Certification(
                        user_id=candidate.id,
                        title="Certified Thing",
                        object_key=certification_key,
                    ),
                    Project(
                        user_id=candidate.id,
                        title="Candidate Project",
                    ),
                    PortfolioItem(
                        user_id=candidate.id,
                        title="Portfolio Case Study",
                        object_key=portfolio_key,
                    ),
                    Skill(
                        user_id=candidate.id,
                        name="Python",
                        normalized_name="python",
                    ),
                    GigPlatform(
                        user_id=candidate.id,
                        platform_name="Gig Platform",
                    ),
                    Internship(
                        user_id=candidate.id,
                        company_name="Intern Corp",
                        role="Intern",
                    ),
                    FreelanceContract(
                        user_id=candidate.id,
                        client_name="Freelance Client",
                        project_title="Freelance Project",
                    ),
                ]
            )
            await session.flush()

            internship = await session.scalar(
                select(Internship).where(Internship.user_id == candidate.id)
            )
            freelance = await session.scalar(
                select(FreelanceContract).where(FreelanceContract.user_id == candidate.id)
            )
            assert internship is not None
            assert freelance is not None
            session.add_all(
                [
                    InternshipDocument(
                        internship_id=internship.id,
                        uploaded_by_user_id=candidate.id,
                        document_type="certificate",
                        object_key=internship_key,
                        original_filename="internship.pdf",
                        content_type="application/pdf",
                        byte_size=100,
                        checksum_sha256="1" * 64,
                    ),
                    FreelanceContractDocument(
                        freelance_contract_id=freelance.id,
                        uploaded_by_user_id=candidate.id,
                        document_type="contract",
                        object_key=freelance_key,
                        original_filename="contract.pdf",
                        content_type="application/pdf",
                        byte_size=100,
                        checksum_sha256="2" * 64,
                    ),
                ]
            )
            expected_deleted_keys.update(
                {certification_key, portfolio_key, internship_key, freelance_key}
            )

            resume_storage_key = f"resumes/{candidate.id}/{uuid4()}/resume.pdf"
            resume_document = ResumeDocument(
                user_id=candidate.id,
                storage_bucket="test-private-bucket",
                storage_key=resume_storage_key,
                original_filename="resume.pdf",
                normalized_filename="resume.pdf",
                content_type="application/pdf",
                file_size_bytes=128,
                checksum_sha256="9" * 64,
                upload_status="uploaded",
                processing_status="needs_review",
                consent_at=now,
                consent_version="v1",
            )
            session.add(resume_document)
            await session.flush()
            expected_deleted_keys.add(resume_storage_key)
            processing_job = ResumeProcessingJob(
                resume_document_id=resume_document.id,
                user_id=candidate.id,
                status="needs_review",
                extraction_provider="synthetic",
                parsing_provider="synthetic",
                parser_schema_version="1",
                idempotency_key=f"resume-delete-{uuid4()}",
            )
            session.add(processing_job)
            await session.flush()
            parsed_result = ResumeParsedResult(
                job_id=processing_job.id,
                user_id=candidate.id,
                schema_version="1",
                structured_result={"employments": []},
                parser_metadata={},
                warnings=[],
            )
            session.add(parsed_result)
            await session.flush()
            review_session = ResumeReviewSession(
                user_id=candidate.id,
                resume_document_id=resume_document.id,
                processing_job_id=processing_job.id,
                parsed_result_id=parsed_result.id,
                status="draft",
                schema_version="1",
                version=1,
            )
            session.add(review_session)
            await session.flush()
            review_item = ResumeReviewItem(
                review_session_id=review_session.id,
                user_id=candidate.id,
                claim_type="employment",
                source_claim_id=f"source-{uuid4()}",
                original_payload={"company_name": "Synthetic"},
                edited_payload={"company_name": "Synthetic"},
                selected=True,
                review_status="confirmed",
                import_action="create",
            )
            session.add(review_item)
            await session.flush()
            import_batch = ResumeImportBatch(
                user_id=candidate.id,
                review_session_id=review_session.id,
                status="completed",
                idempotency_key=f"import-delete-{uuid4()}",
            )
            session.add(import_batch)
            await session.flush()
            session.add_all(
                [
                    ResumeImportResult(
                        import_batch_id=import_batch.id,
                        review_item_id=review_item.id,
                        outcome="imported",
                        record_type="employment",
                        record_id=retained_employment.id,
                    ),
                    ResumeRecordProvenance(
                        user_id=candidate.id,
                        record_type="employment",
                        record_id=retained_employment.id,
                        resume_document_id=resume_document.id,
                        parsed_result_id=parsed_result.id,
                        review_session_id=review_session.id,
                        review_item_id=review_item.id,
                        import_batch_id=import_batch.id,
                        original_payload_hash="a" * 64,
                        edited_payload_hash="b" * 64,
                        confirmed_at=now,
                    ),
                ]
            )
            await session.commit()

            service = AccountDeletionService(session, settings, _FakeRedis())
            await service.delete_candidate_account(
                candidate.id,
                AccountDeletionRequest(confirm="DELETE", current_password="CandidatePass123!"),
            )

        async with async_session_factory() as assert_session:
            deleted_user = await assert_session.get(User, actor_id)
            assert deleted_user is not None
            assert deleted_user.deleted_at is not None
            assert deleted_user.is_active is False
            assert deleted_user.password_hash is None
            assert deleted_user.phone is None
            assert deleted_user.email.startswith("deleted-candidate+")

            assert (
                await assert_session.scalar(
                    select(RefreshToken).where(RefreshToken.user_id == actor_id)
                )
                is None
            )
            assert (
                await assert_session.scalar(
                    select(PasswordResetToken).where(PasswordResetToken.user_id == actor_id)
                )
                is None
            )
            assert (
                await assert_session.scalar(
                    select(PendingSignup).where(PendingSignup.completed_user_id == actor_id)
                )
                is None
            )
            assert (
                await assert_session.scalar(
                    select(ProfileLanguage).where(ProfileLanguage.user_id == actor_id)
                )
                is None
            )
            assert (
                await assert_session.scalar(
                    select(ProfileLink).where(ProfileLink.user_id == actor_id)
                )
                is None
            )
            assert (
                await assert_session.scalar(
                    select(NotificationPreference).where(NotificationPreference.user_id == actor_id)
                )
                is None
            )
            assert (
                await assert_session.scalar(
                    select(Notification).where(Notification.recipient_user_id == actor_id)
                )
                is None
            )
            assert (
                await assert_session.scalar(
                    select(EmailDeliveryLog).where(EmailDeliveryLog.recipient_user_id == actor_id)
                )
                is None
            )
            assert (
                await assert_session.scalar(
                    select(PassportShareLink).where(PassportShareLink.owner_user_id == actor_id)
                )
                is None
            )
            assert (
                await assert_session.scalar(
                    select(TrustScoreSnapshot).where(TrustScoreSnapshot.user_id == actor_id)
                )
                is None
            )
            assert (
                await assert_session.scalar(
                    select(UserSocialAccount).where(UserSocialAccount.user_id == actor_id)
                )
                is None
            )
            assert (
                await assert_session.scalar(
                    select(ResumeDocument).where(ResumeDocument.user_id == actor_id)
                )
                is None
            )
            assert (
                await assert_session.scalar(
                    select(ResumeImportBatch).where(ResumeImportBatch.user_id == actor_id)
                )
                is None
            )
            assert (
                await assert_session.scalar(
                    select(Certification).where(Certification.user_id == actor_id)
                )
                is None
            )
            assert (
                await assert_session.scalar(select(Project).where(Project.user_id == actor_id))
                is None
            )
            assert (
                await assert_session.scalar(
                    select(PortfolioItem).where(PortfolioItem.user_id == actor_id)
                )
                is None
            )
            assert (
                await assert_session.scalar(select(Skill).where(Skill.user_id == actor_id)) is None
            )
            assert (
                await assert_session.scalar(
                    select(GigPlatform).where(GigPlatform.user_id == actor_id)
                )
                is None
            )
            assert (
                await assert_session.scalar(
                    select(Internship).where(Internship.user_id == actor_id)
                )
                is None
            )
            assert (
                await assert_session.scalar(
                    select(FreelanceContract).where(FreelanceContract.user_id == actor_id)
                )
                is None
            )

            assert await assert_session.get(VerificationRequest, purgeable_request_id) is None

            retained_request = await assert_session.get(VerificationRequest, retained_request_id)
            assert retained_request is not None
            assert retained_request.subject_user_id is None
            assert retained_request.subject_name == "Deleted Candidate"
            assert retained_request.subject_email == deleted_user.email
            assert retained_request.candidate_response is None
            assert retained_request.candidate_response_submitted_at is None

            retained_employment = await assert_session.get(
                Employment, retained_request.employment_id
            )
            assert retained_employment is not None
            assert retained_employment.deleted_at is not None
            assert retained_employment.subject_full_name == "Deleted Candidate"
            assert retained_employment.subject_email is None

            contact = await assert_session.scalar(
                select(VerificationContact).where(
                    VerificationContact.verification_request_id == retained_request.id
                )
            )
            assert contact is not None
            assert contact.candidate_note is None

            evidence = await assert_session.scalar(
                select(VerificationRequestEvidence).where(
                    VerificationRequestEvidence.verification_request_id == retained_request.id
                )
            )
            assert evidence is not None
            assert evidence.document_id is None
            assert evidence.employment_document_id is None
            assert evidence.education_document_id is None
            assert evidence.value is None

            invitation = await assert_session.scalar(
                select(TrustInvitation).where(TrustInvitation.organization_id == org_id)
            )
            assert invitation is not None
            assert invitation.subject_name == "Deleted Candidate"
            assert invitation.subject_email == deleted_user.email
            assert invitation.accepted_by_user_id is None
            assert invitation.subject_phone is None
            assert invitation.expires_at <= datetime.now(tz=UTC)

            person = await assert_session.scalar(
                select(OrganizationPerson).where(OrganizationPerson.organization_id == org_id)
            )
            assert person is not None
            assert person.linked_user_id is None

            consent = await assert_session.scalar(
                select(InstitutionPersonConsent).where(
                    InstitutionPersonConsent.organization_id == org_id
                )
            )
            assert consent is not None
            assert consent.subject_user_id is None

        deleted_keys = {key for _, key in s3_client.deleted}
        assert expected_deleted_keys.issubset(deleted_keys)
    finally:
        settings.s3_documents_bucket = original_bucket
        async with async_session_factory() as cleanup:
            if actor_id is not None:
                await cleanup.execute(
                    delete(VerificationRequestEvidence).where(
                        VerificationRequestEvidence.verification_request_id.in_(
                            select(VerificationRequest.id).where(
                                or_(
                                    VerificationRequest.subject_user_id == actor_id,
                                    VerificationRequest.requested_by_user_id == actor_id,
                                )
                            )
                        )
                    )
                )
                await cleanup.execute(
                    delete(VerificationContact).where(
                        VerificationContact.verification_request_id.in_(
                            select(VerificationRequest.id).where(
                                or_(
                                    VerificationRequest.subject_user_id == actor_id,
                                    VerificationRequest.requested_by_user_id == actor_id,
                                )
                            )
                        )
                    )
                )
                await cleanup.execute(
                    delete(VerificationRequest).where(
                        or_(
                            VerificationRequest.subject_user_id == actor_id,
                            VerificationRequest.requested_by_user_id == actor_id,
                        )
                    )
                )
                await cleanup.execute(
                    delete(ResumeRecordProvenance).where(ResumeRecordProvenance.user_id == actor_id)
                )
                await cleanup.execute(
                    delete(ResumeImportBatch).where(ResumeImportBatch.user_id == actor_id)
                )
                await cleanup.execute(
                    delete(ResumeReviewItem).where(ResumeReviewItem.user_id == actor_id)
                )
                await cleanup.execute(
                    delete(ResumeReviewSession).where(ResumeReviewSession.user_id == actor_id)
                )
                await cleanup.execute(
                    delete(ResumeParsedResult).where(ResumeParsedResult.user_id == actor_id)
                )
                await cleanup.execute(
                    delete(ResumeProcessingJob).where(ResumeProcessingJob.user_id == actor_id)
                )
                await cleanup.execute(
                    delete(ResumeDocument).where(ResumeDocument.user_id == actor_id)
                )
                await cleanup.execute(
                    delete(EmploymentDocument).where(
                        EmploymentDocument.uploaded_by_user_id == actor_id
                    )
                )
                await cleanup.execute(delete(UserDocument).where(UserDocument.user_id == actor_id))
                await cleanup.execute(
                    delete(InternshipDocument).where(
                        InternshipDocument.uploaded_by_user_id == actor_id
                    )
                )
                await cleanup.execute(
                    delete(FreelanceContractDocument).where(
                        FreelanceContractDocument.uploaded_by_user_id == actor_id
                    )
                )
                await cleanup.execute(
                    delete(Employment).where(Employment.created_by_user_id == actor_id)
                )
                await cleanup.execute(
                    delete(Certification).where(Certification.user_id == actor_id)
                )
                await cleanup.execute(delete(Project).where(Project.user_id == actor_id))
                await cleanup.execute(
                    delete(PortfolioItem).where(PortfolioItem.user_id == actor_id)
                )
                await cleanup.execute(delete(Skill).where(Skill.user_id == actor_id))
                await cleanup.execute(delete(GigPlatform).where(GigPlatform.user_id == actor_id))
                await cleanup.execute(delete(Internship).where(Internship.user_id == actor_id))
                await cleanup.execute(
                    delete(FreelanceContract).where(FreelanceContract.user_id == actor_id)
                )
            if org_id is not None:
                await cleanup.execute(
                    delete(InstitutionPersonConsent).where(
                        InstitutionPersonConsent.organization_id == org_id
                    )
                )
                await cleanup.execute(
                    delete(OrganizationPerson).where(OrganizationPerson.organization_id == org_id)
                )
                await cleanup.execute(
                    delete(TrustInvitation).where(TrustInvitation.organization_id == org_id)
                )
                await cleanup.execute(delete(Organization).where(Organization.id == org_id))
            if actor_id is not None:
                await cleanup.execute(delete(User).where(User.id == actor_id))
            if org_user_id is not None:
                await cleanup.execute(delete(User).where(User.id == org_user_id))
            await cleanup.commit()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_account_deletion_allows_same_email_reregistration() -> None:
    settings = get_settings()
    original_email = f"reregister-{uuid4()}@example.com"
    original_phone = f"+91999{uuid4().int % 10000000:07d}"
    candidate_id = None
    pending_id = None

    try:
        async with async_session_factory() as session:
            candidate = await _make_candidate(
                session,
                email=original_email,
                phone=original_phone,
            )
            candidate_id = candidate.id
            await session.commit()

            deletion = AccountDeletionService(session, settings, _FakeRedis())
            await deletion.delete_candidate_account(
                candidate.id,
                AccountDeletionRequest(confirm="DELETE", current_password="CandidatePass123!"),
            )

            from app.auth.service import AuthService

            auth = AuthService(session, settings, _FakeRedis())
            response = await auth.start_signup(
                RegisterRequest(
                    full_name="Fresh Candidate",
                    email=original_email,
                    phone=original_phone,
                    password="NewCandidatePass123!",
                )
            )
            pending_id = response.signup_session_id
            await session.commit()

        async with async_session_factory() as assert_session:
            tombstoned_user = await assert_session.get(User, candidate_id)
            assert tombstoned_user is not None
            assert tombstoned_user.deleted_at is not None
            assert tombstoned_user.email != original_email

            pending = await assert_session.get(PendingSignup, pending_id)
            assert pending is not None
            assert pending.email == original_email
            assert pending.phone == original_phone
            assert pending.completed_user_id is None
    finally:
        async with async_session_factory() as cleanup:
            if pending_id is not None:
                await cleanup.execute(delete(PendingSignup).where(PendingSignup.id == pending_id))
            if candidate_id is not None:
                await cleanup.execute(delete(User).where(User.id == candidate_id))
            await cleanup.commit()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_account_deletion_rolls_back_when_s3_delete_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    original_bucket = settings.s3_documents_bucket
    settings.s3_documents_bucket = "test-private-bucket"
    candidate_id = None
    document_id = None

    class _FailingS3Client:
        def delete_object(self, *, Bucket: str, Key: str) -> None:  # noqa: N803
            raise RuntimeError("synthetic s3 failure")

    monkeypatch.setattr(
        "app.services.account_deletion_service.get_s3_client",
        lambda _settings: _FailingS3Client(),
    )

    try:
        async with async_session_factory() as session:
            candidate = await _make_candidate(session)
            candidate.avatar_key = f"avatars/{uuid4()}.png"
            document = UserDocument(
                user_id=candidate.id,
                document_type="passport",
                object_key=f"user-documents/{candidate.id}/{uuid4()}.pdf",
                original_filename="passport.pdf",
                content_type="application/pdf",
                byte_size=1234,
                checksum_sha256="a" * 64,
            )
            session.add(document)
            await session.flush()
            candidate_id = candidate.id
            document_id = document.id
            await session.commit()

            service = AccountDeletionService(session, settings, _FakeRedis())
            with pytest.raises(RuntimeError, match="synthetic s3 failure"):
                await service.delete_candidate_account(
                    candidate.id,
                    AccountDeletionRequest(confirm="DELETE", current_password="CandidatePass123!"),
                )

        async with async_session_factory() as assert_session:
            candidate = await assert_session.get(User, candidate_id)
            assert candidate is not None
            assert candidate.deleted_at is None
            assert candidate.is_active is True
            document = await assert_session.get(UserDocument, document_id)
            assert document is not None
    finally:
        settings.s3_documents_bucket = original_bucket
        async with async_session_factory() as cleanup:
            if document_id is not None:
                await cleanup.execute(delete(UserDocument).where(UserDocument.id == document_id))
            if candidate_id is not None:
                await cleanup.execute(delete(User).where(User.id == candidate_id))
            await cleanup.commit()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_account_deletion_invalidates_public_passport_links() -> None:
    settings = get_settings()
    candidate_id = None

    raw_token = f"public-passport-{uuid4()}"
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    try:
        async with async_session_factory() as session:
            candidate = await _make_candidate(session)
            candidate_id = candidate.id
            session.add(
                PassportShareLink(
                    owner_user_id=candidate.id,
                    label="Public share",
                    token_hash=token_hash,
                    permissions={"include_employments": True},
                )
            )
            await session.commit()

            from app.services.public_passport_service import PublicPassportService

            passport = PublicPassportService(session, settings)
            response = await passport.get_by_token(raw_token)
            assert response.share.label == "Public share"

            deletion = AccountDeletionService(session, settings, _FakeRedis())
            await deletion.delete_candidate_account(
                candidate.id,
                AccountDeletionRequest(confirm="DELETE", current_password="CandidatePass123!"),
            )

            with pytest.raises(NotFoundError):
                await passport.get_by_token(raw_token)
    finally:
        async with async_session_factory() as cleanup:
            if candidate_id is not None:
                await cleanup.execute(delete(User).where(User.id == candidate_id))
            await cleanup.commit()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_deleted_candidate_access_token_fails_current_user_lookup() -> None:
    from fastapi.security import HTTPAuthorizationCredentials

    from app.auth.deps import get_current_user

    settings = get_settings()
    candidate_id = None

    try:
        async with async_session_factory() as session:
            candidate = await _make_candidate(session)
            candidate_id = candidate.id
            from app.auth.tokens import create_access_token

            token = create_access_token(
                settings,
                subject=candidate.id,
                role=candidate.role,
                extra_claims={"email": candidate.email},
            )
            await session.commit()

            deletion = AccountDeletionService(session, settings, _FakeRedis())
            await deletion.delete_candidate_account(
                candidate.id,
                AccountDeletionRequest(confirm="DELETE", current_password="CandidatePass123!"),
            )

        async with async_session_factory() as assert_session:
            with pytest.raises(UnauthorizedError):
                await get_current_user(
                    credentials=HTTPAuthorizationCredentials(
                        scheme="Bearer",
                        credentials=token,
                    ),
                    session=assert_session,
                    settings=settings,
                )
    finally:
        async with async_session_factory() as cleanup:
            if candidate_id is not None:
                await cleanup.execute(delete(User).where(User.id == candidate_id))
            await cleanup.commit()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_account_deletion_repeat_delete_fails_closed() -> None:
    settings = get_settings()
    candidate_id = None

    try:
        async with async_session_factory() as session:
            candidate = await _make_candidate(session)
            candidate_id = candidate.id
            await session.commit()

            deletion = AccountDeletionService(session, settings, _FakeRedis())
            await deletion.delete_candidate_account(
                candidate.id,
                AccountDeletionRequest(confirm="DELETE", current_password="CandidatePass123!"),
            )

            with pytest.raises(NotFoundError):
                await deletion.delete_candidate_account(
                    candidate.id,
                    AccountDeletionRequest(confirm="DELETE", current_password="CandidatePass123!"),
                )
    finally:
        async with async_session_factory() as cleanup:
            if candidate_id is not None:
                await cleanup.execute(delete(User).where(User.id == candidate_id))
            await cleanup.commit()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_account_deletion_rejects_organization_workspace_member() -> None:
    settings = get_settings()
    now = datetime.now(tz=UTC)
    candidate_id = None
    org_user_id = None
    org_id = None

    try:
        async with async_session_factory() as session:
            org_user = User(
                email=f"org-owner-{uuid4()}@example.invalid",
                password_hash=_hash_password("OwnerPass123!"),
                full_name="Owner",
                role=Role.HR.value,
                is_active=True,
                email_verified_at=now,
            )
            candidate = User(
                email=f"member-candidate-{uuid4()}@example.invalid",
                password_hash=_hash_password("CandidatePass123!"),
                full_name="Candidate Member",
                role=Role.USER.value,
                is_active=True,
                email_verified_at=now,
            )
            session.add_all([org_user, candidate])
            await session.flush()
            org_user_id = org_user.id
            candidate_id = candidate.id

            organization = Organization(
                created_by_user_id=org_user.id,
                name="Workspace Org",
                organization_type=OrganizationType.EMPLOYER,
                verification_state=OrganizationVerificationState.VERIFIED,
            )
            session.add(organization)
            await session.flush()
            org_id = organization.id

            session.add(
                OrganizationMember(
                    organization_id=organization.id,
                    user_id=candidate.id,
                    role=OrganizationRole.MEMBER,
                )
            )
            await session.commit()

            service = AccountDeletionService(session, settings, _FakeRedis())
            with pytest.raises(ForbiddenError):
                await service.delete_candidate_account(
                    candidate.id,
                    AccountDeletionRequest(confirm="DELETE", current_password="CandidatePass123!"),
                )
    finally:
        async with async_session_factory() as cleanup:
            if org_id is not None:
                await cleanup.execute(delete(Organization).where(Organization.id == org_id))
            if candidate_id is not None:
                await cleanup.execute(delete(User).where(User.id == candidate_id))
            if org_user_id is not None:
                await cleanup.execute(delete(User).where(User.id == org_user_id))
            await cleanup.commit()
