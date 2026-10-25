"""Shared PDF authorization and disclosure regressions, without external services."""

from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pypdf import PdfReader

from app.api.dependencies.services import get_public_passport_service
from app.exceptions import NotFoundError
from app.infrastructure.redis.deps import get_redis
from app.logging.request_redaction import redact_request_credentials
from app.main import app
from app.schemas.passport_share import PassportSharePermissions
from app.schemas.public_passport import (
    PublicPassportDocument,
    PublicPassportEducation,
    PublicPassportEmployment,
    PublicPassportProfile,
    PublicPassportResponse,
    PublicPassportShareMetadata,
    PublicPassportVault,
)
from app.services.public_passport_pdf import render_public_passport_pdf
from app.services.public_passport_service import PublicPassportService


@pytest.fixture(autouse=True)
def pdf_limiter():
    redis = SimpleNamespace(eval=AsyncMock(return_value=1), ttl=AsyncMock(return_value=60))
    app.dependency_overrides[get_redis] = lambda: redis
    yield redis
    app.dependency_overrides.pop(get_redis, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("counts", [[11], [1, 6]])
async def test_limiter_blocks_before_render_without_raw_token_keys(pdf_limiter, counts):
    svc, _ = service()
    svc.get_pdf_by_token = AsyncMock()
    pdf_limiter.eval.side_effect = counts
    app.dependency_overrides[get_public_passport_service] = lambda: svc
    try:
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            response = await client.get("/api/v1/public/passport/opaque-test-token/pdf")
    finally:
        app.dependency_overrides.pop(get_public_passport_service, None)
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"
    assert "no-store" in response.headers["cache-control"]
    svc.get_pdf_by_token.assert_not_awaited()
    assert all("opaque-test-token" not in str(call) for call in pdf_limiter.eval.call_args_list)


@pytest.mark.asyncio
async def test_limiter_unavailable_fails_closed(pdf_limiter):
    from redis.exceptions import ConnectionError

    pdf_limiter.eval.side_effect = ConnectionError("PRIVATE_INFRA_DETAIL")
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.get("/api/v1/public/passport/opaque-test-token/pdf")
    assert response.status_code == 503
    assert "PRIVATE_INFRA_DETAIL" not in response.text


def passport():
    permissions = PassportSharePermissions(
        **{field: field == "include_educations" for field in PassportSharePermissions.model_fields}
    )
    return PublicPassportResponse(
        profile=PublicPassportProfile(
            full_name="Synthetic Candidate",
            headline="HIDDEN_HEADLINE",
            location="HIDDEN_LOCATION",
            avatar_url="TOKEN_PHOTO_URL",
            profile_slug="HIDDEN_SLUG",
        ),
        trust_score=None,
        vault=PublicPassportVault(
            employments=[
                PublicPassportEmployment(
                    id=uuid4(),
                    employer_legal_name="HIDDEN_EMPLOYER",
                    job_title="HIDDEN_JOB",
                    start_date=None,
                    end_date=None,
                    verification_status="verified",
                    verification_method="HIDDEN_METHOD",
                    documents=[
                        PublicPassportDocument(
                            id=uuid4(),
                            document_type="letter",
                            original_filename="HIDDEN_DOC.pdf",
                            byte_size=100,
                            verification_status="uploaded",
                        )
                    ],
                )
            ],
            educations=[
                PublicPassportEducation(
                    id=uuid4(),
                    institution_name="Synthetic University",
                    degree="BSc",
                    field_of_study="Computing",
                    education_level="bachelors",
                    grade=None,
                    start_date=date(2020, 1, 1),
                    start_date_precision="year",
                    end_date=date(2023, 6, 1),
                    end_date_precision="month",
                    is_currently_studying=False,
                    verification_status="verified",
                )
            ],
            internships=[],
            freelance=[],
            gig_platforms=[],
            portfolio=[],
            certifications=[],
            user_documents=[],
        ),
        share=PublicPassportShareMetadata(
            id=uuid4(),
            label="INTERNAL_LABEL",
            expires_at=None,
            track_views=False,
            permissions=permissions,
        ),
    )


def text(content):
    return "\n".join(page.extract_text() for page in PdfReader(BytesIO(content)).pages)


def service(*, state="active"):
    payload = passport()
    link = SimpleNamespace(
        id=payload.share.id,
        owner_user_id=uuid4(),
        label=None,
        permissions=payload.share.permissions.model_dump(),
        track_views=False,
        revoked_at=None,
        expires_at=None,
    )
    if state == "revoked":
        link.revoked_at = datetime.now(UTC)
    if state == "expired":
        link.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    svc = PublicPassportService(
        SimpleNamespace(
            scalar=AsyncMock(return_value=None if state == "deleted_owner" else link.owner_user_id)
        ),
        SimpleNamespace(),
    )
    svc._shares = SimpleNamespace(
        get_by_token_hash=AsyncMock(return_value=None if state == "invalid" else link)
    )
    svc._users = SimpleNamespace(get_public_profile=AsyncMock(return_value=payload.profile))
    svc.build_vault_for_user = AsyncMock(return_value=payload.vault)
    return svc, link


def test_pdf_branded_permission_limited_and_no_identifiers():
    data = passport()
    content = render_public_passport_pdf(data)
    assert content.startswith(b"%PDF-")
    reader = PdfReader(BytesIO(content))
    assert len(reader.pages[0].images) == 1
    rendered = text(content)
    for expected in ("KairoID", "Synthetic University", "Education", "2020", "Jun 2023"):
        assert expected in rendered
    for hidden in (
        "HIDDEN",
        "TOKEN_PHOTO_URL",
        "INTERNAL_LABEL",
        str(data.share.id),
        str(data.vault.educations[0].id),
        "01 Jan 2020",
        "masked_identifier",
        "••••••234F",
        "••••••••1234",
    ):
        assert hidden not in rendered
    assert "Employment" not in rendered
    assert reader.metadata.author == "KairoID"


def test_employer_and_document_flags_remain_independent():
    data = passport()
    data.share.permissions.include_employments = True
    result = text(render_public_passport_pdf(data))
    assert "HIDDEN_JOB" in result
    assert "HIDDEN_EMPLOYER" not in result
    assert "HIDDEN_DOC" not in result
    assert "HIDDEN_METHOD" not in result
    data.share.permissions.show_documents = True
    data.share.permissions.show_employer_names = True
    result = text(render_public_passport_pdf(data))
    assert "HIDDEN_EMPLOYER" in result
    assert "HIDDEN_DOC.pdf" in result
    assert "HIDDEN_METHOD" not in result


def test_no_markup_execution_and_long_records_paginate():
    data = passport()
    data.vault.educations[0].institution_name = '<a href="https://secret.invalid">Not a link</a>'
    data.vault.educations *= 30
    reader = PdfReader(BytesIO(render_public_passport_pdf(data)))
    assert len(reader.pages) > 1
    assert all(not page.get("/Annots") for page in reader.pages)


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["active", "invalid", "revoked", "expired", "deleted_owner"])
async def test_pdf_endpoint_authorizes_every_download(state):
    svc, _ = service(state=state)
    app.dependency_overrides[get_public_passport_service] = lambda: svc
    try:
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            response = await client.get("/api/v1/public/passport/opaque-test-token/pdf")
    finally:
        app.dependency_overrides.pop(get_public_passport_service, None)
    assert "no-store" in response.headers["cache-control"]
    if state == "active":
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert (
            response.headers["content-disposition"]
            == 'attachment; filename="KairoID-Shared-Passport.pdf"'
        )
        assert "Synthetic University" in text(response.content)
        assert "opaque-test-token" not in text(response.content)
    else:
        assert response.status_code == 404
        svc.build_vault_for_user.assert_not_awaited()
        assert not response.content.startswith(b"%PDF-")


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["revoke", "expire", "narrow"])
async def test_share_changes_during_render_fail_closed(monkeypatch, change):
    svc, link = service()

    def rendering(_):
        if change == "revoke":
            link.revoked_at = datetime.now(UTC)
        elif change == "expire":
            link.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        else:
            link.permissions = {**link.permissions, "include_educations": False}
        return b"%PDF-not-delivered"

    monkeypatch.setattr("app.services.public_passport_pdf.render_public_passport_pdf", rendering)
    with pytest.raises(NotFoundError):
        await svc.get_pdf_by_token("opaque-test-token")


@pytest.mark.asyncio
async def test_later_download_does_not_reuse_previously_authorized_pdf():
    svc, link = service()
    assert (await svc.get_pdf_by_token("opaque-test-token")).startswith(b"%PDF-")
    link.revoked_at = datetime.now(UTC)
    with pytest.raises(NotFoundError):
        await svc.get_pdf_by_token("opaque-test-token")


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["invalid", "revoked", "expired", "deleted_owner"])
async def test_page_and_pdf_share_the_same_active_share_guard(state):
    svc, _ = service(state=state)
    with pytest.raises(NotFoundError):
        await svc.get_by_token("opaque-test-token")
    with pytest.raises(NotFoundError):
        await svc.get_pdf_by_token("opaque-test-token")
    svc._users.get_public_profile.assert_not_awaited()


def test_download_path_uses_existing_token_redaction():
    assert redact_request_credentials("/api/v1/public/passport/opaque-secret/pdf") == (
        "/api/v1/public/passport/[REDACTED]/pdf"
    )


@pytest.mark.asyncio
async def test_renderer_failure_does_not_expose_document_text(monkeypatch):
    svc, _ = service()

    def fail(_):
        raise ValueError("PRIVATE DOCUMENT TEXT")

    monkeypatch.setattr("app.services.public_passport_pdf.render_public_passport_pdf", fail)
    app.dependency_overrides[get_public_passport_service] = lambda: svc
    try:
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            response = await client.get("/api/v1/public/passport/opaque-test-token/pdf")
    finally:
        app.dependency_overrides.pop(get_public_passport_service, None)
    assert response.status_code == 503
    assert "PRIVATE DOCUMENT TEXT" not in response.text
    assert "no-store" in response.headers["cache-control"]


@pytest.mark.parametrize(
    "section",
    [
        "internships",
        "freelance",
        "gig_platforms",
        "portfolio",
        "certifications",
        "skills",
        "projects",
        "user_documents",
    ],
)
def test_every_additional_section_requires_its_permission(section):
    from typing import get_args

    data = passport()
    model = get_args(PublicPassportVault.model_fields[section].annotation)[0]
    values = {field: None for field in model.model_fields}
    values.update(
        {
            "id": uuid4(),
            "name": "ALLOWED_RECORD",
            "title": "ALLOWED_RECORD",
            "company_name": "ALLOWED_RECORD",
            "role": "Analyst",
            "client_name": "ALLOWED_RECORD",
            "project_title": "Project",
            "platform_name": "ALLOWED_RECORD",
            "partner_role": "Partner",
            "original_filename": "ALLOWED_RECORD.pdf",
            "document_type": "other",
            "byte_size": 100,
            "start_date": date(2020, 1, 1),
            "started_at": date(2020, 1, 1),
            "is_ongoing": False,
            "is_active": False,
            "does_not_expire": True,
            "tags": [],
            "verification_status": "self_declared",
        }
    )
    setattr(data.vault, section, [model.model_validate(values)])
    assert "ALLOWED_RECORD" not in text(render_public_passport_pdf(data))
    setattr(data.share.permissions, f"include_{section}", True)
    if section == "user_documents":
        assert "ALLOWED_RECORD" not in text(render_public_passport_pdf(data))
        data.share.permissions.show_documents = True
    assert "ALLOWED_RECORD" in text(render_public_passport_pdf(data))
