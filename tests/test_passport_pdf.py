"""Contract, privacy, truth, and rendering tests for Passport PDF export."""

from __future__ import annotations

from datetime import UTC, date, datetime
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pypdf import PdfReader
from sqlalchemy.exc import NoResultFound

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_passport_pdf_service
from app.exceptions import NotFoundError, ServiceUnavailableError
from app.main import app
from app.schemas.passport_engine import (
    OwnerPassportResponse,
    PassportMetadata,
    PassportSectionStatusSummary,
    PassportSharingSummary,
    PassportVerificationSummary,
)
from app.schemas.public_passport import (
    PublicPassportCertification,
    PublicPassportDocument,
    PublicPassportEducation,
    PublicPassportEmployment,
    PublicPassportProject,
    PublicPassportSkill,
    PublicPassportUserDocument,
    PublicPassportVault,
)
from app.schemas.trust_score import TrustScoreResponse
from app.schemas.user import UserPublic
from app.services.passport_pdf_service import (
    PDF_FILENAME,
    PassportPDFDocument,
    PassportPDFService,
    build_passport_pdf_projection,
    render_passport_pdf,
    verification_status_label,
)

GENERATED_AT = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
PRIVATE_EMAIL = "private-owner@example.com"
PRIVATE_PHONE = "+91-9000000000"
PRIVATE_DOCUMENT = "PRIVATE-DOCUMENT-SENTINEL.pdf"
PRIVATE_EVIDENCE_URL = "https://private-storage.example.test/evidence-sentinel"
PRIVATE_PROJECT_URL = "https://private-project.example.test/sentinel"
PRIVATE_AVATAR_URL = "https://private-avatar.example.test/sentinel"


class StubPassportPDFService:
    async def generate(self, owner_user_id: UUID) -> PassportPDFDocument:
        assert owner_user_id
        projection = build_passport_pdf_projection(_owner_passport(), generated_at=GENERATED_AT)
        return PassportPDFDocument(
            content=render_passport_pdf(projection),
            filename=PDF_FILENAME,
            generated_at=GENERATED_AT,
        )


async def _candidate_user() -> CurrentUser:
    return CurrentUser(id=uuid4(), email=PRIVATE_EMAIL, role="user")


async def _admin_user() -> CurrentUser:
    return CurrentUser(id=uuid4(), email="admin@example.test", role="admin")


@pytest.fixture(autouse=True)
def _clear_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_passport_pdf_requires_authentication() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/passport/me/pdf")

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/json")


@pytest.mark.asyncio
async def test_passport_pdf_is_candidate_owner_only() -> None:
    app.dependency_overrides[get_current_user] = _admin_user
    app.dependency_overrides[get_passport_pdf_service] = lambda: StubPassportPDFService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/passport/me/pdf")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


@pytest.mark.asyncio
async def test_passport_pdf_success_contract_and_headers() -> None:
    app.dependency_overrides[get_current_user] = _candidate_user
    app.dependency_overrides[get_passport_pdf_service] = lambda: StubPassportPDFService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/passport/me/pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == (
        'attachment; filename="Kairo-Trust-Passport.pdf"'
    )
    assert response.headers["cache-control"] == "private, no-store"
    assert response.content.startswith(b"%PDF-")
    assert len(response.content) > 1_000


def test_openapi_models_binary_pdf_and_auth_errors() -> None:
    operation = app.openapi()["paths"]["/api/v1/passport/me/pdf"]["get"]

    assert operation["security"] == [{"HTTPBearer": []}]
    assert operation["responses"]["200"]["content"] == {
        "application/pdf": {"schema": {"type": "string", "format": "binary"}}
    }
    assert {"401", "403", "404", "429", "500", "503"}.issubset(operation["responses"])


def test_projection_and_pdf_exclude_private_fields_and_documents() -> None:
    owner = _owner_passport()
    projection = build_passport_pdf_projection(owner, generated_at=GENERATED_AT)
    projection_json = projection.model_dump_json()
    pdf_text = _pdf_text(render_passport_pdf(projection))

    sentinels = {
        PRIVATE_EMAIL,
        PRIVATE_PHONE,
        "1990-01-02",
        str(owner.profile.id),
        str(owner.passport_metadata.owner_user_id),
        PRIVATE_DOCUMENT,
        PRIVATE_EVIDENCE_URL,
        PRIVATE_PROJECT_URL,
        PRIVATE_AVATAR_URL,
        "identity-document",
        "offer-letter",
    }
    for sentinel in sentinels:
        assert sentinel not in projection_json
        assert sentinel not in pdf_text


def test_projection_schema_is_an_exact_professional_allowlist() -> None:
    projection = build_passport_pdf_projection(_owner_passport(), generated_at=GENERATED_AT)

    assert set(projection.model_dump()) == {
        "profile",
        "trust_score",
        "employments",
        "educations",
        "certifications",
        "projects",
        "skills",
        "generated_at",
    }
    assert set(projection.profile.model_dump()) == {
        "display_name",
        "headline",
        "location",
        "professional_summary",
        "current_role",
        "industry",
        "years_of_experience",
    }
    assert set(projection.employments[0].model_dump()) == {
        "employer_name",
        "job_title",
        "start_date",
        "end_date",
        "verification_status",
        "verification_label",
    }
    assert set(projection.educations[0].model_dump()) == {
        "institution_name",
        "degree",
        "field_of_study",
        "start_date",
        "end_date",
        "is_currently_studying",
        "verification_status",
        "verification_label",
    }
    assert set(projection.certifications[0].model_dump()) == {
        "title",
        "issuing_organization",
        "issued_date",
        "expiry_date",
        "does_not_expire",
        "verification_status",
        "verification_label",
    }
    assert set(projection.projects[0].model_dump()) == {
        "title",
        "role",
        "organization_name",
        "description",
        "start_date",
        "end_date",
        "is_ongoing",
        "verification_status",
        "verification_label",
    }
    assert set(projection.skills[0].model_dump()) == {
        "name",
        "verification_status",
        "verification_label",
    }


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("verified", "Verified"),
        ("approved", "Verified"),
        ("draft", "Self-declared / Not Verified"),
        ("self_declared", "Self-declared / Not Verified"),
        ("not_verified", "Self-declared / Not Verified"),
        ("pending", "Pending"),
        ("submitted", "Submitted for verification"),
        ("under_review", "In verification"),
        ("additional_info_requested", "Additional information requested"),
        ("unable_to_verify", "Unable to verify"),
        ("rejected", "Rejected"),
        ("cancelled", "Cancelled"),
    ],
)
def test_truthful_verification_status_mapping(status: str, expected: str) -> None:
    assert verification_status_label(status) == expected


def test_pdf_preserves_verified_self_declared_and_in_progress_truth() -> None:
    owner = _owner_passport(
        employment_statuses=("verified", "draft", "under_review"),
        certification_status="self_declared",
    )
    text = _pdf_text(
        render_passport_pdf(build_passport_pdf_projection(owner, generated_at=GENERATED_AT))
    )

    assert "Verified" in text
    assert "Self-declared / Not Verified" in text
    assert "In verification" in text
    assert "Cloud Security" in text


def test_trust_score_is_omitted_when_consent_gates_the_value() -> None:
    owner = _owner_passport(trust_score_available=False)
    projection = build_passport_pdf_projection(owner, generated_at=GENERATED_AT)
    text = _pdf_text(render_passport_pdf(projection))

    assert projection.trust_score is None
    assert "Trust Score" not in text


def test_authoritative_trust_score_is_rendered_without_recalculation() -> None:
    owner = _owner_passport(trust_score_available=True)
    projection = build_passport_pdf_projection(owner, generated_at=GENERATED_AT)
    text = _pdf_text(render_passport_pdf(projection))

    assert projection.trust_score is not None
    assert projection.trust_score.overall == 82
    assert "Trust Score" in text
    assert "82 / 100" in text


def test_pdf_contains_supported_sections_and_omits_empty_optional_sections() -> None:
    projection = build_passport_pdf_projection(_owner_passport(), generated_at=GENERATED_AT)
    text = _pdf_text(render_passport_pdf(projection))

    for section in ("Employment", "Education", "Certifications", "Projects", "Skills"):
        assert section in text
    assert "Internships" not in text
    assert "Freelance" not in text
    assert "Gig platforms" not in text
    assert "Portfolio" not in text
    assert "Documents" not in text

    empty_projection = projection.model_copy(
        update={"certifications": [], "projects": [], "skills": []}
    )
    empty_text = _pdf_text(render_passport_pdf(empty_projection))
    assert "Certifications" not in empty_text
    assert "Projects" not in empty_text
    assert "Skills" not in empty_text


def test_long_unicode_content_renders_across_multiple_pages_without_loss() -> None:
    projection = build_passport_pdf_projection(_owner_passport(), generated_at=GENERATED_AT)
    long_description = (
        "Designed a resilient résumé processing platform for R&D teams & candidates. " * 30
    )
    projects = [
        projection.projects[0].model_copy(
            update={
                "title": f"Résumé Platform {index:02d}",
                "description": long_description,
            }
        )
        for index in range(18)
    ]
    projection = projection.model_copy(
        update={
            "profile": projection.profile.model_copy(update={"display_name": "Zoë García"}),
            "projects": projects,
        }
    )
    pdf = render_passport_pdf(projection)
    reader = PdfReader(BytesIO(pdf))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert len(reader.pages) >= 3
    assert "Zoë García" in text
    assert "Résumé Platform 17" in text
    assert "R&D teams & candidates" in text


def test_user_controlled_markup_is_rendered_as_literal_text() -> None:
    projection = build_passport_pdf_projection(_owner_passport(), generated_at=GENERATED_AT)
    projection = projection.model_copy(
        update={
            "profile": projection.profile.model_copy(update={"display_name": "<b>Zoë & Co</b>"})
        }
    )

    text = _pdf_text(render_passport_pdf(projection))

    assert "<b>Zoë & Co</b>" in text


def test_renderer_is_deterministic_for_fixed_projection() -> None:
    projection = build_passport_pdf_projection(_owner_passport(), generated_at=GENERATED_AT)
    assert render_passport_pdf(projection) == render_passport_pdf(projection)


@pytest.mark.asyncio
async def test_service_maps_absent_owner_to_not_found() -> None:
    class MissingEngine:
        async def get_owner_passport(self, owner_user_id):  # noqa: ANN001
            raise NoResultFound

    with pytest.raises(NotFoundError, match="Trust Passport not found"):
        await PassportPDFService(MissingEngine()).generate(uuid4())


@pytest.mark.asyncio
async def test_service_rejects_malformed_renderer_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    class Engine:
        async def get_owner_passport(self, owner_user_id):  # noqa: ANN001
            return _owner_passport()

    monkeypatch.setattr(
        "app.services.passport_pdf_service.render_passport_pdf",
        lambda projection: b"not-a-pdf",
    )

    with pytest.raises(ServiceUnavailableError, match="temporarily unavailable"):
        await PassportPDFService(Engine()).generate(uuid4())


def _pdf_text(content: bytes) -> str:
    reader = PdfReader(BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _owner_passport(
    *,
    employment_statuses: tuple[str, ...] = ("verified",),
    certification_status: str = "self_declared",
    trust_score_available: bool = True,
) -> OwnerPassportResponse:
    owner_id = UUID("11111111-1111-4111-8111-111111111111")
    document_id = UUID("22222222-2222-4222-8222-222222222222")
    trust_score = (
        TrustScoreResponse(
            overall=82,
            status="calculated",
            verification_completeness_percentage=100,
            last_calculated_at=GENERATED_AT,
        )
        if trust_score_available
        else TrustScoreResponse(
            overall=None,
            status="consent_required",
            manual_review_reason="Consent is required.",
            last_calculated_at=GENERATED_AT,
        )
    )
    employments = [
        PublicPassportEmployment(
            id=uuid4(),
            employer_legal_name=f"Example Employer {index + 1}",
            job_title=f"Platform Engineer {index + 1}",
            start_date=date(2020 + index, 1, 1),
            end_date=None,
            verification_status=status,
            verification_method="document",
            documents=[
                PublicPassportDocument(
                    id=document_id,
                    document_type="offer-letter",
                    original_filename=PRIVATE_DOCUMENT,
                    byte_size=9_999,
                    verification_status="verified",
                )
            ],
        )
        for index, status in enumerate(employment_statuses)
    ]
    education = PublicPassportEducation(
        id=uuid4(),
        institution_name="Example Institute of Technology",
        degree="Bachelor of Technology",
        field_of_study="Computer Science",
        education_level="bachelors",
        grade=None,
        start_date=date(2016, 7, 1),
        end_date=date(2020, 5, 1),
        is_currently_studying=False,
        verification_status="verified",
    )
    certification = PublicPassportCertification(
        id=uuid4(),
        title="Cloud Security",
        issuing_organization="Example Academy",
        issued_date=date(2025, 3, 1),
        expiry_date=None,
        does_not_expire=True,
        credential_id="PRIVATE-CREDENTIAL-ID",
        credential_url=PRIVATE_EVIDENCE_URL,
        verification_status=certification_status,
    )
    project = PublicPassportProject(
        id=uuid4(),
        title="Trust Platform",
        role="Lead Engineer",
        description="Built a professional credential platform with careful status semantics.",
        start_date=date(2024, 1, 1),
        end_date=None,
        is_ongoing=True,
        project_url=PRIVATE_PROJECT_URL,
        repository_url="https://private-repository.example.test/sentinel",
        organization_name="Example Labs",
        verification_status="self_declared",
    )
    user_document = PublicPassportUserDocument(
        id=document_id,
        document_type="identity-document",
        original_filename=PRIVATE_DOCUMENT,
        byte_size=8_888,
        verification_status="verified",
        expires_at=None,
    )
    empty = PassportSectionStatusSummary(total=0, statuses={})

    return OwnerPassportResponse(
        profile=UserPublic(
            id=owner_id,
            email=PRIVATE_EMAIL,
            full_name="QA Owner",
            profile_slug="private-profile-slug",
            phone=PRIVATE_PHONE,
            current_role="Principal Engineer",
            industry="Technology",
            years_of_experience=8,
            location="Bengaluru, India",
            headline="Building trustworthy career infrastructure",
            bio="Backend and mobile systems leader.",
            date_of_birth=date(1990, 1, 2),
            avatar_url=PRIVATE_AVATAR_URL,
            role="user",
            is_active=True,
            phone_verified_at=GENERATED_AT,
            email_verified_at=GENERATED_AT,
            employment_onboarding_completed_at=GENERATED_AT,
            created_at=GENERATED_AT,
        ),
        trust_score=trust_score,
        vault=PublicPassportVault(
            employments=employments,
            educations=[education],
            internships=[],
            freelance=[],
            gig_platforms=[],
            portfolio=[],
            certifications=[certification],
            skills=[
                PublicPassportSkill(name="Swift", verification_status="self_declared"),
                PublicPassportSkill(name="Python", verification_status="verified"),
            ],
            projects=[project],
            user_documents=[user_document],
        ),
        passport_metadata=PassportMetadata(
            owner_user_id=owner_id,
            profile_slug="private-profile-slug",
            is_email_verified=True,
            is_onboarding_complete=True,
            created_at=GENERATED_AT,
            updated_at=GENERATED_AT,
            employment_onboarding_completed_at=GENERATED_AT,
        ),
        sharing_summary=PassportSharingSummary(
            total_links=1,
            active_links=0,
            revoked_links=1,
            expired_links=0,
            total_views=1,
            unique_views=1,
            latest_share_created_at=GENERATED_AT,
            last_viewed_at=GENERATED_AT,
        ),
        verification_summary=PassportVerificationSummary(
            overall=PassportSectionStatusSummary(total=6, statuses={"verified": 3}),
            employments=PassportSectionStatusSummary(
                total=len(employments), statuses={status: 1 for status in employment_statuses}
            ),
            educations=PassportSectionStatusSummary(total=1, statuses={"verified": 1}),
            internships=empty,
            freelance=empty,
            gig_platforms=empty,
            portfolio=empty,
            certifications=PassportSectionStatusSummary(
                total=1, statuses={certification_status: 1}
            ),
            skills=PassportSectionStatusSummary(
                total=2, statuses={"self_declared": 1, "verified": 1}
            ),
            projects=PassportSectionStatusSummary(total=1, statuses={"self_declared": 1}),
            user_documents=PassportSectionStatusSummary(total=1, statuses={"verified": 1}),
        ),
    )
