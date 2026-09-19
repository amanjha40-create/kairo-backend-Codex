"""Exact owner bindings, real PostgreSQL queries, synthetic storage only."""

from datetime import UTC, datetime
from urllib.parse import unquote
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from test_document_pack_source_matrix import seed_sources
from test_document_share_packs import setup as document_pack_setup

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import (
    get_certification_service,
    get_education_service,
    get_employment_document_service,
    get_portfolio_service,
)
from app.main import app
from app.models import Education, Employment, VerificationRequest, VerificationRequestEvidence
from app.services.certification_service import CertificationService
from app.services.education_service import EducationService
from app.services.employment_document_service import EmploymentDocumentService
from app.services.portfolio_service import PortfolioService

setup = document_pack_setup


def override_service(instance):
    return lambda: instance


SOURCES = ["employment", "education", "certification", "portfolio"]
SERVICES = [
    (get_employment_document_service, EmploymentDocumentService),
    (get_education_service, EducationService),
    (get_certification_service, CertificationService),
    (get_portfolio_service, PortfolioService),
]


def path(kind, row, parent=None):
    if kind in {"employment", "education"}:
        parent = parent or getattr(row, f"{kind}_id")
        return f"/api/v1/{kind}s/{parent}/documents/{row.id}/content"
    resource = "certifications" if kind == "certification" else "portfolio"
    return f"/api/v1/{resource}/{row.id}/content"


@pytest.fixture
async def sources(setup):
    c = setup
    c.records = await seed_sources(c)
    for dependency, service in SERVICES:
        instance = service(c.session, c.settings)
        app.dependency_overrides[dependency] = override_service(instance)
    try:
        yield c
    finally:
        for dependency, _ in SERVICES:
            app.dependency_overrides.pop(dependency, None)
        app.dependency_overrides.pop(get_current_user, None)


def authenticate(owner):
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=owner.id, email="qa@example.test", role="user"
    )


@pytest.mark.parametrize("kind", SOURCES)
@pytest.mark.parametrize("mime", ["application/pdf", "image/png", "image/jpeg", "image/webp"])
async def test_owner_binary_route_never_returns_storage_location(sources, monkeypatch, kind, mime):
    c = sources
    row = c.records[SOURCES.index(kind)]
    row.content_type = mime
    row.original_filename = "../private\\safe\r\nfile.pdf"
    await c.session.commit()
    head = c.storage.head_object
    monkeypatch.setattr(c.storage, "head_object", lambda **kw: {**head(**kw), "ContentType": mime})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get(path(kind, row))).status_code == 401
        authenticate(c.owner)
        response = await client.get(path(kind, row))
    assert response.status_code == 200
    assert response.content == b"%PDF-synthetic harmless QA"
    assert response.headers["content-type"] == mime
    assert "location" not in response.headers
    assert "no-store" in response.headers["cache-control"]
    assert "private" in response.headers["cache-control"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "sandbox" in response.headers["content-security-policy"]
    disposition = unquote(response.headers["content-disposition"])
    assert disposition.endswith("safefile.pdf")
    assert "\r" not in disposition and "\n" not in disposition and "../" not in disposition
    output = str(dict(response.headers)) + response.text
    assert row.object_key not in output and c.settings.s3_documents_bucket not in output
    assert "amazonaws.com" not in output and "https://" not in output


@pytest.mark.parametrize("kind", SOURCES)
@pytest.mark.parametrize(
    "failure",
    [
        "wrong_owner",
        "deleted",
        "incomplete",
        "mime",
        "size",
        "missing",
        "changed_size",
        "changed_mime",
    ],
)
async def test_unavailable_bindings_fail_closed(sources, monkeypatch, kind, failure):
    c = sources
    row = c.records[SOURCES.index(kind)]
    if failure == "deleted":
        row.deleted_at = datetime.now(UTC)
    elif failure == "incomplete":
        if kind == "portfolio":
            row.upload_completed_at = None
        else:
            row.checksum_sha256 = "0" * 64
    elif failure == "mime":
        row.content_type = "text/html"
    elif failure == "size":
        row.byte_size = 51 * 1024 * 1024
    elif failure == "missing":
        c.storage.objects.clear()
    elif failure == "changed_size":
        row.byte_size += 1
    elif failure == "changed_mime":
        row.content_type = "image/png"
    await c.session.commit()
    if failure in {"wrong_owner", "deleted", "incomplete", "mime", "size"}:

        def forbidden(**_):
            pytest.fail("Unavailable or unauthorized file reached storage")

        monkeypatch.setattr(c.storage, "head_object", forbidden)
    authenticate(c.other if failure == "wrong_owner" else c.owner)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path(kind, row))
    assert response.status_code == 404
    assert row.object_key not in response.text
    assert c.settings.s3_documents_bucket not in response.text


@pytest.mark.parametrize("kind", ["employment", "education"])
@pytest.mark.parametrize("failure", ["deleted_parent", "wrong_parent"])
async def test_exact_parent_tuple_required(sources, kind, failure):
    c = sources
    row = c.records[SOURCES.index(kind)]
    parent_id = getattr(row, f"{kind}_id")
    model = Employment if kind == "employment" else Education
    if failure == "deleted_parent":
        parent = await c.session.get(model, parent_id)
        parent.deleted_at = datetime.now(UTC)
    else:
        parent = model(
            id=uuid4(),
            **(
                {
                    "created_by_user_id": c.owner.id,
                    "subject_full_name": "QA",
                    "employer_legal_name": "QA",
                    "job_title": "QA",
                }
                if kind == "employment"
                else {"user_id": c.owner.id, "institution_name": "QA"}
            ),
        )
        c.session.add(parent)
        parent_id = parent.id
    await c.session.commit()
    authenticate(c.owner)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get(path(kind, row, parent_id))).status_code == 404


@pytest.mark.parametrize("kind", ["employment", "education"])
async def test_evidence_uses_exact_current_binding_not_replacement(sources, kind):
    c = sources
    row = c.records[SOURCES.index(kind)]
    request = VerificationRequest(
        id=uuid4(),
        requested_by_user_id=c.owner.id,
        subject_user_id=c.owner.id,
        subject_name="Synthetic",
        subject_email="qa@example.test",
        request_type=kind,
        status="draft",
    )
    c.session.add(request)
    await c.session.flush()
    c.session.add(
        VerificationRequestEvidence(
            verification_request_id=request.id,
            submitted_by_user_id=c.owner.id,
            evidence_type="document",
            field_key="qa",
            status="superseded",
            **{f"{kind}_document_id": row.id},
        )
    )
    await c.session.commit()
    authenticate(c.owner)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get(path(kind, row))).status_code == 200
        row.deleted_at = datetime.now(UTC)
        await c.session.commit()
        # Other attachments exist but must never stand in for the missing evidence ID.
        await seed_sources(c)
        assert (await client.get(path(kind, row))).status_code == 404


def test_openapi_content_routes_are_authenticated_binary_contracts():
    paths = app.openapi()["paths"]
    for path_ in [
        "/api/v1/employments/{employment_id}/documents/{document_id}/content",
        "/api/v1/educations/{education_id}/documents/{document_id}/content",
        "/api/v1/certifications/{certification_id}/content",
        "/api/v1/portfolio/{item_id}/content",
    ]:
        route = paths[path_]["get"]
        assert route["security"]
        content = route["responses"]["200"]["content"]
        assert "application/json" not in content
        assert content["application/pdf"]["schema"]["format"] == "binary"
