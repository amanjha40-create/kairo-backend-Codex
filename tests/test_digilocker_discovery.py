"""Synthetic-only dynamic DigiLocker discovery and import contract tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from test_digilocker_lifecycle import harness as digilocker_harness  # noqa: F401

from app.api.v1.routes.digilocker import get_discovery_service
from app.auth.deps import CurrentUser, get_current_user
from app.db.session import async_session_factory
from app.exceptions import ValidationAppError
from app.integrations.digilocker.documents import RetrievedDocument, normalize_items
from app.integrations.digilocker.education import (
    parse_driving_licence_address,
    parse_education_xml,
)
from app.integrations.digilocker.registry import DOCUMENT_ROUTES, SUPPORTED_DOCTYPES
from app.main import app
from app.models import (
    DigiLockerIdentityVerification,
    Education,
    EducationDocument,
    PermanentAddressVersion,
    User,
)
from app.schemas.public_passport import PublicPassportResponse
from app.services.digilocker_discovery_service import DigiLockerDiscoveryService


@pytest.fixture(name="harness")
async def harness_fixture(digilocker_harness):  # noqa: F811
    yield digilocker_harness


ALL_DOCTYPES = [
    "PANCR",
    "DRVLC",
    "SSCER",
    "HSCER",
    "SPCER",
    "HPCER",
    "PACER",
    "DGCER",
    "DGMST",
    "DIPCR",
    "PRVCR",
    "PVCER",
    "TRTMP",
    "MICER",
    "SSMGR",
    "HSMGR",
]


def issued(doctype: str, *, mime=None, suffix="ONE") -> dict:
    return {
        "name": "Synthetic document",
        "type": "file",
        "date": "2026-01-01",
        "mime": mime or ["application/xml", "application/pdf"],
        "uri": f"in.test-{doctype}-{suffix}",
        "doctype": doctype,
        "issuerid": "in.test",
        "issuer": "Synthetic University",
        "description": "Synthetic issued record",
    }


def identity_xml(doctype: str, *, address=True) -> bytes:
    extra = (
        ' address="Synthetic Road" district="Mumbai" state="Maharashtra" '
        'pincode="400001" country="IN"'
        if address and doctype == "DRVLC"
        else ""
    )
    number = "ABCDE1234F" if doctype == "PANCR" else "MH-12 2020/001234"
    status = "A" if doctype == "PANCR" else "Active"
    return (
        f'<Certificate type="{doctype}" number="{number}" status="{status}">'
        f'<IssuedTo><Person name="Test Candidate" dob="01-01-1990"{extra}/></IssuedTo>'
        "</Certificate>"
    ).encode()


def drvlc_prefill_xml() -> bytes:
    return (
        '<Certificate type="DRVLC" number="SYNTHETIC" status="Active">'
        '<IssuedTo><Person name="Test Candidate" dob="01-01-1990">'
        '<Address type="present" line1="Private Synthetic Free Form" country="IN"/>'
        "</Person></IssuedTo></Certificate>"
    ).encode()


def education_xml(
    doctype: str,
    *,
    institution="Synthetic University",
    qualification="Bachelor of Commerce",
    year="2020",
) -> bytes:
    return (
        f'<Certificate type="{doctype}"><IssuedTo><Person name="Test Candidate"/></IssuedTo>'
        f'<CertificateData institutionName="{institution}" qualification="{qualification}" '
        f'completionYear="{year}"/></Certificate>'
    ).encode()


def spcer_sscer_variant_xml(
    *,
    namespaced: bool = False,
    include_institution: bool = True,
    include_year: bool = True,
) -> bytes:
    namespace = ' xmlns="urn:synthetic:digilocker:certificate"' if namespaced else ""
    institution = ' boardName="Synthetic Board"' if include_institution else ""
    year = ' passingYear="2020"' if include_year else ""
    return (
        f'<Certificate{namespace} type="SSCER">'
        '<CertificateData certificateNumber="SYNTHETIC"/>'
        '<IssuedTo><Person name="Test Candidate"/></IssuedTo>'
        f'<Examination{institution}{year} result="PASS"/>'
        '<Issuer><Board/></Issuer>'
        '</Certificate>'
    ).encode()


class FakeDocuments:
    def __init__(self, rows, payloads=None, failures=None):
        self.rows = rows
        self.payloads = payloads or {}
        self.failures = failures or set()
        self.issued_calls = 0
        self.retrieve_calls = []

    async def issued(self, _token):
        self.issued_calls += 1
        return normalize_items({"items": self.rows})

    async def retrieve(self, _token, uri, *, xml=False):
        self.retrieve_calls.append((uri, xml))
        if uri in self.failures:
            from app.integrations.digilocker.provider import ProviderError

            raise ProviderError("invalid_response")
        content = self.payloads[uri]
        mime = "application/xml" if xml else "application/pdf"
        return RetrievedDocument(content, mime)


class FakeStorage:
    def __init__(self):
        self.objects = {}

    async def put_private(self, *, object_key, content, content_type):
        self.objects[object_key] = (content, content_type)

    async def delete_best_effort(self, *, object_key):
        self.objects.pop(object_key, None)


class FailingStorage(FakeStorage):
    async def put_private(self, *, object_key, content, content_type):
        if self.objects:
            from app.exceptions import ServiceUnavailableError

            raise ServiceUnavailableError("Synthetic storage failure")
        await super().put_private(object_key=object_key, content=content, content_type=content_type)


async def prepare_user(harness):
    await harness.activate()
    async with async_session_factory() as session:
        user = await session.get(User, harness.ids[0])
        user.full_name = "Test Candidate"
        user.date_of_birth = date(1990, 1, 1)
        await session.commit()


async def service(harness, documents, *, storage=None):
    session = async_session_factory()
    return session, DigiLockerDiscoveryService(
        session,
        harness.config,
        harness.redis,
        documents=documents,
        storage=storage or FakeStorage(),
    )


def test_registry_is_complete_canonical_and_routes_education():
    assert set(ALL_DOCTYPES) == SUPPORTED_DOCTYPES == set(DOCUMENT_ROUTES)
    assert DOCUMENT_ROUTES["PANCR"].record_type == "pan"
    assert DOCUMENT_ROUTES["DRVLC"].secondary_uses == ("permanent_address_candidate",)
    assert all(DOCUMENT_ROUTES[value].domain == "education" for value in ALL_DOCTYPES[2:])
    assert DOCUMENT_ROUTES["SSMGR"].group_strategy == "class_x"
    assert DOCUMENT_ROUTES["HSMGR"].group_strategy == "class_xii"


def test_all_supported_doctypes_normalize_and_unknown_is_ignored():
    rows, malformed = normalize_items(
        {"items": [issued(doctype) for doctype in ALL_DOCTYPES] + [issued("UNKNOWN")]}
    )
    assert malformed == 0
    assert sum(row["supported"] for row in rows) == len(ALL_DOCTYPES)
    assert rows[-1]["supported"] is False


@pytest.mark.parametrize(
    "doctype,domain",
    [("PANCR", "identity"), ("DRVLC", "identity"), ("DGCER", "education"), ("HSCER", "education")],
)
async def test_single_document_discovery_succeeds(harness, doctype, domain):
    await prepare_user(harness)
    row = issued(doctype)
    payload = identity_xml(doctype) if domain == "identity" else education_xml(doctype)
    docs = FakeDocuments([row], {row["uri"]: payload})
    session, discovery = await service(harness, docs)
    try:
        result = await discovery.available_records(harness.ids[0])
    finally:
        await session.close()
    assert result[domain]
    assert result["counts"]["supported"] == 1
    assert result["counts"]["parse_failures"] == 0


async def test_unknown_and_no_supported_documents_are_successful(harness):
    await prepare_user(harness)
    docs = FakeDocuments([issued("UNKNOWN")])
    session, discovery = await service(harness, docs)
    try:
        result = await discovery.available_records(harness.ids[0])
    finally:
        await session.close()
    assert result["identity"] == result["education"] == []
    assert result["counts"] | {"unsupported": 1} == result["counts"]
    assert result["counts"]["total_issued"] == result["counts"]["unsupported"] == 1


async def test_all_supported_doctypes_discover_in_one_isolated_sync(harness):
    await prepare_user(harness)
    rows = [issued(doctype, suffix=str(index)) for index, doctype in enumerate(ALL_DOCTYPES)]
    payloads = {
        row["uri"]: identity_xml(row["doctype"])
        if row["doctype"] in {"PANCR", "DRVLC"}
        else education_xml(row["doctype"])
        for row in rows
    }
    session, discovery = await service(harness, FakeDocuments(rows, payloads))
    try:
        result = await discovery.available_records(harness.ids[0])
    finally:
        await session.close()
    assert result["counts"]["total_issued"] == len(ALL_DOCTYPES)
    assert result["counts"]["supported"] == len(ALL_DOCTYPES)
    assert result["counts"]["unsupported"] == 0
    assert result["counts"]["identity"] == 2
    assert result["counts"]["parse_failures"] == 0


async def test_pdf_only_remains_available_without_retrieval(harness):
    await prepare_user(harness)
    row = issued("DGCER", mime=["application/pdf"])
    docs = FakeDocuments([row])
    session, discovery = await service(harness, docs)
    try:
        result = await discovery.available_records(harness.ids[0])
    finally:
        await session.close()
    evidence = result["education"][0]["evidence"][0]
    assert evidence["pdf_available"] is True
    assert evidence["xml_available"] is evidence["parsed_data_available"] is False
    assert evidence["review_state"] == "needs_review"
    assert docs.retrieve_calls == []


async def test_pdf_only_can_link_to_owner_validated_existing_education(harness):
    await prepare_user(harness)
    education_id = (await add_education(harness.ids[0]))[0]
    row = issued("DGCER", mime=["application/pdf"])
    docs = FakeDocuments([row], {row["uri"]: b"%PDF-synthetic"})
    storage = FakeStorage()
    session, discovery = await service(harness, docs, storage=storage)
    try:
        available = await discovery.available_records(harness.ids[0])
        candidate_id = available["education"][0]["candidate_id"]
        result = await discovery.import_records(
            harness.ids[0],
            [candidate_id],
            education_targets={candidate_id: education_id},
            consent=False,
            consent_version="v1",
        )
    finally:
        await session.close()
    assert result["outcomes"][0]["status"] == "linked"
    assert result["outcomes"][0]["record_id"] == education_id
    assert len(storage.objects) == 1


async def test_malformed_xml_and_one_failure_are_isolated(harness):
    await prepare_user(harness)
    pan, degree, transcript = issued("PANCR"), issued("DGCER"), issued("TRTMP")
    docs = FakeDocuments(
        [pan, degree, transcript],
        {
            pan["uri"]: identity_xml("PANCR"),
            degree["uri"]: education_xml("DGCER"),
            transcript["uri"]: b"<not-valid",
        },
    )
    session, discovery = await service(harness, docs)
    try:
        result = await discovery.available_records(harness.ids[0])
    finally:
        await session.close()
    assert len(result["identity"]) == 1
    assert len(result["education"]) == 2
    assert result["counts"]["parse_failures"] == 1
    assert any(group["review_state"] == "ready" for group in result["education"])
    assert any(group["review_state"] == "parse_failed" for group in result["education"])


@pytest.mark.parametrize("address", [True, False])
async def test_driving_licence_address_candidate_is_optional(harness, address, caplog):
    await prepare_user(harness)
    row = issued("DRVLC")
    docs = FakeDocuments([row], {row["uri"]: identity_xml("DRVLC", address=address)})
    session, discovery = await service(harness, docs)
    try:
        result = await discovery.available_records(harness.ids[0])
    finally:
        await session.close()
    assert len(result["identity"]) == 1
    assert len(result["address_candidates"]) == int(address)
    assert result["address_prefill_candidates"] == []
    assert result["address_discovery_state"] == (
        "STRUCTURED_ADDRESS_CANDIDATE" if address else "NO_ADDRESS_AVAILABLE"
    )
    if address:
        candidate = result["address_candidates"][0]
        assert candidate["source"] == "digilocker_driving_licence"
        assert candidate["candidate_type"] == "structured"
        assert candidate["address_state"] == "STRUCTURED_ADDRESS_CANDIDATE"
        assert candidate["document_address_type"] == "untyped"
        assert candidate["requires_permanent_confirmation"] is True
        assert candidate["requires_replacement_confirmation"] is False
        assert candidate["address"] == candidate["structured_address"]
        assert "google_place_id" not in candidate["address"]
    assert "Synthetic Road" not in repr([record.__dict__ for record in caplog.records])


async def test_present_free_form_address_uses_additive_prefill_contract(
    harness, caplog, monkeypatch
):
    await prepare_user(harness)
    row = issued("DRVLC")
    docs = FakeDocuments([row], {row["uri"]: drvlc_prefill_xml()})
    google_calls = []

    def forbidden_geocoder(*args, **kwargs):
        google_calls.append((args, kwargs))
        raise AssertionError("Discovery must not construct a geocoder")

    monkeypatch.setattr(
        "app.services.permanent_address_geocoder.build_address_geocoder",
        forbidden_geocoder,
    )
    session, discovery = await service(harness, docs)
    try:
        result = await discovery.available_records(harness.ids[0])
    finally:
        await session.close()

    assert result["address_candidates"] == []
    assert result["address_discovery_state"] == "ADDRESS_PREFILL_CANDIDATE"
    assert result["counts"]["address_candidates"] == 0
    assert result["counts"]["address_prefill_candidates"] == 1
    candidate = result["address_prefill_candidates"][0]
    assert candidate == {
        "candidate_id": candidate["candidate_id"],
        "doctype": "DRVLC",
        "display_type": "Driving Licence address",
        "source": "digilocker_driving_licence",
        "review_state": "ready",
        "candidate_type": "prefill",
        "address_state": "ADDRESS_PREFILL_CANDIDATE",
        "document_address_type": "present_or_current",
        "requires_permanent_confirmation": True,
        "requires_replacement_confirmation": False,
        "prefill_text": "Private Synthetic Free Form, IN",
        "structured_address": None,
    }
    assert google_calls == []
    assert "Private Synthetic Free Form" not in repr(
        [record.__dict__ for record in caplog.records]
    )

    async with async_session_factory() as check:
        assert (
            await check.scalar(
                select(func.count())
                .select_from(PermanentAddressVersion)
                .where(PermanentAddressVersion.user_id == harness.ids[0])
            )
            == 0
        )


def test_public_passport_contract_cannot_expose_ephemeral_address_prefill():
    schema = repr(PublicPassportResponse.model_json_schema())
    assert "prefill_text" not in schema
    assert "AddressPrefillCandidate" not in schema


async def test_address_candidate_reports_existing_address_without_replacing_it(harness):
    await prepare_user(harness)
    async with async_session_factory() as setup:
        setup.add(
            PermanentAddressVersion(
                user_id=harness.ids[0],
                version=1,
                claimed_address={
                    "address_line_1": "Existing Synthetic Address",
                    "city": "Existing City",
                    "state": "Existing State",
                    "postal_code": "400001",
                    "country": "IN",
                },
                address_hash="a" * 64,
                geocode_status="READY",
                target_source="provider_geocode",
                target_status="active",
                document_status="REQUIRED",
                cycle=1,
            )
        )
        await setup.commit()
    row = issued("DRVLC")
    session, discovery = await service(
        harness,
        FakeDocuments([row], {row["uri"]: identity_xml("DRVLC")}),
    )
    try:
        result = await discovery.available_records(harness.ids[0])
    finally:
        await session.close()

    candidate = result["address_candidates"][0]
    assert candidate["requires_replacement_confirmation"] is True
    async with async_session_factory() as check:
        current = await check.scalar(
            select(PermanentAddressVersion).where(
                PermanentAddressVersion.user_id == harness.ids[0],
                PermanentAddressVersion.invalidated_at.is_(None),
            )
        )
        assert current is not None
        assert current.version == 1
        assert current.claimed_address["address_line_1"] == "Existing Synthetic Address"


async def test_prefill_candidate_requires_confirmation_before_replacing_existing_address(harness):
    await prepare_user(harness)
    async with async_session_factory() as setup:
        setup.add(
            PermanentAddressVersion(
                user_id=harness.ids[0],
                version=1,
                claimed_address={
                    "address_line_1": "Existing Synthetic Address",
                    "city": "Existing City",
                    "state": "Existing State",
                    "postal_code": "400001",
                    "country": "IN",
                },
                address_hash="b" * 64,
                geocode_status="READY",
                target_source="provider_geocode",
                target_status="active",
                document_status="REQUIRED",
                cycle=1,
            )
        )
        await setup.commit()
    row = issued("DRVLC")
    session, discovery = await service(
        harness,
        FakeDocuments([row], {row["uri"]: drvlc_prefill_xml()}),
    )
    try:
        result = await discovery.available_records(harness.ids[0])
    finally:
        await session.close()

    candidate = result["address_prefill_candidates"][0]
    assert candidate["requires_replacement_confirmation"] is True
    assert candidate["requires_permanent_confirmation"] is True
    async with async_session_factory() as check:
        current = await check.scalar(
            select(PermanentAddressVersion).where(
                PermanentAddressVersion.user_id == harness.ids[0],
                PermanentAddressVersion.invalidated_at.is_(None),
            )
        )
        assert current is not None
        assert current.version == 1


def test_parser_extracts_safe_education_and_address_contracts():
    route = DOCUMENT_ROUTES["DGCER"]
    parsed = parse_education_xml(
        education_xml("DGCER"),
        doctype="DGCER",
        route=route,
        issuer_name="Synthetic issuer",
    )
    assert (parsed.institution_name, parsed.qualification, parsed.completion_year) == (
        "Synthetic University",
        "Bachelor of Commerce",
        2020,
    )
    address = parse_driving_licence_address(identity_xml("DRVLC"))
    assert address is not None and address.country == "IN"


@pytest.mark.parametrize("namespaced", [False, True])
def test_spcer_accepts_signed_sscer_schema_variant(namespaced):
    parsed = parse_education_xml(
        spcer_sscer_variant_xml(namespaced=namespaced),
        doctype="SPCER",
        route=DOCUMENT_ROUTES["SPCER"],
        issuer_name="Synthetic Board",
    )
    assert parsed.parser_status == "parsed"
    assert parsed.education_level == "high_school"
    assert parsed.qualification == "Class X"
    assert parsed.institution_name == "Synthetic Board"
    assert parsed.completion_year == 2020


def test_spcer_variant_allows_optional_year_but_requires_institution():
    optional_year = parse_education_xml(
        spcer_sscer_variant_xml(include_year=False),
        doctype="SPCER",
        route=DOCUMENT_ROUTES["SPCER"],
        issuer_name="Synthetic Board",
    )
    assert optional_year.parser_status == "parsed"
    assert optional_year.completion_year is None

    missing_institution = parse_education_xml(
        spcer_sscer_variant_xml(include_institution=False),
        doctype="SPCER",
        route=DOCUMENT_ROUTES["SPCER"],
        issuer_name=None,
    )
    assert missing_institution.parser_status == "needs_review"
    assert missing_institution.institution_name is None


def test_spcer_alias_is_one_way_and_malformed_xml_remains_failed():
    wrong_route = parse_education_xml(
        education_xml("SPCER"),
        doctype="SSCER",
        route=DOCUMENT_ROUTES["SSCER"],
        issuer_name="Synthetic Board",
    )
    malformed = parse_education_xml(
        b"<Certificate",
        doctype="SPCER",
        route=DOCUMENT_ROUTES["SPCER"],
        issuer_name="Synthetic Board",
    )
    assert wrong_route.parser_status == malformed.parser_status == "parse_failed"


async def test_class_x_and_xii_supporting_documents_group_once(harness):
    await prepare_user(harness)
    rows = [issued(value) for value in ("SSCER", "SPCER", "SSMGR", "HSCER", "HPCER", "HSMGR")]
    payloads = {
        row["uri"]: education_xml(
            row["doctype"],
            qualification="Class X" if row["doctype"].startswith("S") else "Class XII",
        )
        for row in rows
    }
    session, discovery = await service(harness, FakeDocuments(rows, payloads))
    try:
        result = await discovery.available_records(harness.ids[0])
    finally:
        await session.close()
    assert len(result["education"]) == 2
    assert sorted(len(group["evidence"]) for group in result["education"]) == [3, 3]


async def test_degree_certificate_marksheet_and_transcript_group_once(harness):
    await prepare_user(harness)
    rows = [issued(value) for value in ("DGCER", "DGMST", "TRTMP")]
    docs = FakeDocuments(rows, {row["uri"]: education_xml(row["doctype"]) for row in rows})
    session, discovery = await service(harness, docs)
    try:
        result = await discovery.available_records(harness.ids[0])
    finally:
        await session.close()
    assert len(result["education"]) == 1
    assert len(result["education"][0]["evidence"]) == 3


async def test_repeated_discovery_is_stable_and_mutates_nothing(harness):
    await prepare_user(harness)
    rows = [issued("PANCR"), issued("DRVLC"), issued("DGCER")]
    docs = FakeDocuments(
        rows,
        {
            rows[0]["uri"]: identity_xml("PANCR"),
            rows[1]["uri"]: identity_xml("DRVLC"),
            rows[2]["uri"]: education_xml("DGCER"),
        },
    )
    session, discovery = await service(harness, docs)
    try:
        first = await discovery.available_records(harness.ids[0])
        second = await discovery.available_records(harness.ids[0])
    finally:
        await session.close()
    assert first["identity"][0]["candidate_id"] == second["identity"][0]["candidate_id"]
    assert first["education"][0]["candidate_id"] == second["education"][0]["candidate_id"]
    assert first["address_candidates"] == second["address_candidates"]
    async with async_session_factory() as check:
        assert (
            await check.scalar(
                select(func.count())
                .select_from(Education)
                .where(Education.user_id == harness.ids[0])
            )
            == 0
        )
        assert (
            await check.scalar(
                select(func.count())
                .select_from(PermanentAddressVersion)
                .where(PermanentAddressVersion.user_id == harness.ids[0])
            )
            == 0
        )
        assert (
            await check.scalar(
                select(func.count())
                .select_from(EducationDocument)
                .join(Education, Education.id == EducationDocument.education_id)
                .where(Education.user_id == harness.ids[0])
            )
            == 0
        )
        assert (
            await check.scalar(
                select(func.count())
                .select_from(DigiLockerIdentityVerification)
                .where(DigiLockerIdentityVerification.user_id == harness.ids[0])
            )
            == 0
        )


async def add_education(user_id, *, duplicate=False):
    async with async_session_factory() as session:
        rows = []
        for _ in range(2 if duplicate else 1):
            row = Education(
                user_id=user_id,
                institution_name="Synthetic University",
                degree="Bachelor of Commerce",
                education_level="bachelors",
                end_date=date(2020, 12, 31),
                end_date_precision="year",
                is_currently_studying=False,
                verification_status="draft",
            )
            session.add(row)
            rows.append(row)
        await session.commit()
        return [row.id for row in rows]


async def add_class_x_education(user_id, *, duplicate=False):
    async with async_session_factory() as session:
        rows = []
        for _ in range(2 if duplicate else 1):
            row = Education(
                user_id=user_id,
                institution_name="Synthetic Board",
                degree="Class X",
                education_level="high_school",
                end_date=date(2020, 12, 31),
                end_date_precision="year",
                is_currently_studying=False,
                verification_status="draft",
            )
            session.add(row)
            rows.append(row)
        await session.commit()
        return [row.id for row in rows]


async def add_manual_class_x_education(
    user_id, *, degree="High School", institution="Synthetic Secondary School", year=None
):
    async with async_session_factory() as session:
        row = Education(
            user_id=user_id,
            institution_name=institution,
            degree=degree,
            education_level="high_school",
            end_date=date(year, 12, 31) if year else None,
            end_date_precision="year" if year else None,
            is_currently_studying=False,
            verification_status="draft",
        )
        session.add(row)
        await session.commit()
        return row.id


@pytest.mark.parametrize(
    "existing,duplicate,expected_match,expected_review",
    [
        (False, False, "NO_MATCH", "ready"),
        (True, False, "CLEAR_MATCH", "ready"),
        (True, True, "AMBIGUOUS", "needs_review"),
    ],
)
async def test_spcer_sscer_variant_resolution(
    harness, existing, duplicate, expected_match, expected_review
):
    await prepare_user(harness)
    if existing:
        await add_class_x_education(harness.ids[0], duplicate=duplicate)
    row = issued("SPCER")
    documents = FakeDocuments([row], {row["uri"]: spcer_sscer_variant_xml()})
    session, discovery = await service(harness, documents)
    try:
        result = await discovery.available_records(harness.ids[0])
    finally:
        await session.close()
    group = result["education"][0]
    assert group["possible_existing_record_match"] == expected_match
    assert group["review_state"] == expected_review
    assert group["import_status"] == (
        "available" if expected_review == "ready" else "needs_review"
    )


async def test_spcer_variant_repeated_import_is_idempotent(harness):
    await prepare_user(harness)
    row = issued("SPCER")
    storage = FakeStorage()
    session, discovery = await service(
        harness,
        FakeDocuments([row], {row["uri"]: spcer_sscer_variant_xml()}),
        storage=storage,
    )
    try:
        available = await discovery.available_records(harness.ids[0])
        selected = available["education"][0]["candidate_id"]
        first = await discovery.import_records(
            harness.ids[0], [selected], consent=False, consent_version="v1"
        )
        education = await session.scalar(
            select(Education).where(Education.user_id == harness.ids[0])
        )
        first_verified_at = education.verified_at
        second = await discovery.import_records(
            harness.ids[0], [selected], consent=False, consent_version="v1"
        )
    finally:
        await session.close()
    assert first["outcomes"][0]["status"] == "imported"
    assert second["outcomes"][0]["status"] == "already_added"
    assert first_verified_at is not None
    async with async_session_factory() as check:
        education = await check.scalar(
            select(Education).where(Education.user_id == harness.ids[0])
        )
        assert education.verification_status == "verified"
        assert education.verified_at == first_verified_at
        assert (
            await check.scalar(
                select(func.count())
                .select_from(EducationDocument)
                .join(Education, Education.id == EducationDocument.education_id)
                .where(Education.user_id == harness.ids[0])
            )
            == 1
        )
    assert len(storage.objects) == 1


async def test_manual_class_x_alias_links_without_duplicate_or_optional_year(harness):
    await prepare_user(harness)
    education_id = await add_manual_class_x_education(harness.ids[0])
    row = issued("SPCER")
    storage = FakeStorage()
    session, discovery = await service(
        harness,
        FakeDocuments([row], {row["uri"]: spcer_sscer_variant_xml()}),
        storage=storage,
    )
    try:
        available = await discovery.available_records(harness.ids[0])
        assert available["education"][0]["possible_existing_record_match"] == "CLEAR_MATCH"
        selected = available["education"][0]["candidate_id"]
        result = await discovery.import_records(
            harness.ids[0], [selected], consent=False, consent_version="v1"
        )
    finally:
        await session.close()
    assert result["outcomes"][0]["status"] == "linked"
    assert result["outcomes"][0]["record_id"] == education_id
    async with async_session_factory() as check:
        assert (
            await check.scalar(
                select(func.count())
                .select_from(Education)
                .where(Education.user_id == harness.ids[0], Education.deleted_at.is_(None))
            )
            == 1
        )


async def test_class_x_conflicting_year_or_board_requires_review(harness):
    await prepare_user(harness)
    await add_manual_class_x_education(
        harness.ids[0], institution="CBSE", year=2019, degree="Class X"
    )
    row = issued("SPCER")
    documents = FakeDocuments([row], {row["uri"]: spcer_sscer_variant_xml()})
    session, discovery = await service(harness, documents)
    try:
        result = await discovery.available_records(harness.ids[0])
    finally:
        await session.close()
    group = result["education"][0]
    assert group["possible_existing_record_match"] == "CONFLICT"
    assert group["review_state"] == "needs_review"


async def test_import_prefers_pdf_and_retains_safe_structured_metadata(harness):
    await prepare_user(harness)
    row = issued("SPCER")
    storage = FakeStorage()
    documents = FakeDocuments([row], {row["uri"]: spcer_sscer_variant_xml()})
    session, discovery = await service(harness, documents, storage=storage)
    try:
        available = await discovery.available_records(harness.ids[0])
        selected = available["education"][0]["candidate_id"]
        await discovery.import_records(
            harness.ids[0], [selected], consent=False, consent_version="v1"
        )
        evidence = await session.scalar(
            select(EducationDocument).where(
                EducationDocument.uploaded_by_user_id == harness.ids[0]
            )
        )
    finally:
        await session.close()
    assert documents.retrieve_calls == [(row["uri"], True), (row["uri"], True), (row["uri"], False)]
    assert evidence.content_type == "application/pdf"
    assert evidence.extracted_payload["digilocker"]["safe_preview"] == {
        "qualification": "Class X",
        "completion_year": 2020,
    }
    assert len(storage.objects) == 1


@pytest.mark.parametrize("existing,expected", [(False, "NO_MATCH"), (True, "CLEAR_MATCH")])
async def test_manual_or_resume_education_exact_match(harness, existing, expected):
    await prepare_user(harness)
    if existing:
        await add_education(harness.ids[0])
    row = issued("DGCER")
    docs = FakeDocuments([row], {row["uri"]: education_xml("DGCER")})
    session, discovery = await service(harness, docs)
    try:
        result = await discovery.available_records(harness.ids[0])
    finally:
        await session.close()
    assert result["education"][0]["possible_existing_record_match"] == expected


async def test_manual_education_is_upgraded_without_duplicate(harness):
    await prepare_user(harness)
    education_id = (await add_education(harness.ids[0]))[0]
    row = issued("DGCER")
    storage = FakeStorage()
    session, discovery = await service(
        harness,
        FakeDocuments([row], {row["uri"]: education_xml("DGCER")}),
        storage=storage,
    )
    try:
        available = await discovery.available_records(harness.ids[0])
        selected = available["education"][0]["candidate_id"]
        result = await discovery.import_records(
            harness.ids[0], [selected], consent=False, consent_version="v1"
        )
    finally:
        await session.close()
    assert result["outcomes"][0]["status"] == "linked"
    assert result["outcomes"][0]["record_id"] == education_id
    async with async_session_factory() as check:
        educations = list(
            (
                await check.scalars(
                    select(Education).where(Education.user_id == harness.ids[0])
                )
            ).all()
        )
        assert len(educations) == 1
        assert educations[0].verification_status == "verified"
        assert educations[0].verified_at is not None


async def test_ambiguous_education_requires_review(harness):
    await prepare_user(harness)
    await add_education(harness.ids[0], duplicate=True)
    row = issued("DGCER")
    session, discovery = await service(
        harness, FakeDocuments([row], {row["uri"]: education_xml("DGCER")})
    )
    try:
        result = await discovery.available_records(harness.ids[0])
    finally:
        await session.close()
    group = result["education"][0]
    assert group["possible_existing_record_match"] == "AMBIGUOUS"
    assert group["review_state"] == "needs_review"


async def test_selected_education_import_is_idempotent_and_unselected_is_untouched(harness):
    await prepare_user(harness)
    degree, transcript = issued("DGCER"), issued("TRTMP", suffix="TWO")
    docs = FakeDocuments(
        [degree, transcript],
        {
            degree["uri"]: education_xml("DGCER"),
            transcript["uri"]: education_xml("TRTMP"),
        },
    )
    storage = FakeStorage()
    session, discovery = await service(harness, docs, storage=storage)
    try:
        available = await discovery.available_records(harness.ids[0])
        selected = available["education"][0]["candidate_id"]
        first = await discovery.import_records(
            harness.ids[0], [selected], consent=False, consent_version="v1"
        )
        second = await discovery.import_records(
            harness.ids[0], [selected], consent=False, consent_version="v1"
        )
    finally:
        await session.close()
    assert first["outcomes"][0]["status"] == "imported"
    assert second["outcomes"][0]["status"] == "already_added"
    async with async_session_factory() as check:
        assert (
            await check.scalar(
                select(func.count())
                .select_from(Education)
                .where(Education.user_id == harness.ids[0])
            )
            == 1
        )
        assert (
            await check.scalar(
                select(func.count())
                .select_from(EducationDocument)
                .join(Education, Education.id == EducationDocument.education_id)
                .where(Education.user_id == harness.ids[0])
            )
            == 2
        )
    assert len(storage.objects) == 2


async def test_unselected_education_group_causes_zero_mutation(harness):
    await prepare_user(harness)
    degree, school = issued("DGCER"), issued("HSCER", suffix="TWO")
    docs = FakeDocuments(
        [degree, school],
        {
            degree["uri"]: education_xml("DGCER"),
            school["uri"]: education_xml(
                "HSCER", institution="Synthetic Board", qualification="Class XII"
            ),
        },
    )
    session, discovery = await service(harness, docs, storage=FakeStorage())
    try:
        available = await discovery.available_records(harness.ids[0])
        selected = next(
            group["candidate_id"]
            for group in available["education"]
            if group["record_type"] == "degree"
        )
        await discovery.import_records(
            harness.ids[0], [selected], consent=False, consent_version="v1"
        )
    finally:
        await session.close()
    async with async_session_factory() as check:
        educations = (
            await check.scalars(select(Education).where(Education.user_id == harness.ids[0]))
        ).all()
    assert len(educations) == 1
    assert educations[0].degree == "Bachelor of Commerce"


async def test_identity_import_requires_consent_and_is_idempotent(harness, monkeypatch):
    await prepare_user(harness)
    row = issued("PANCR")
    docs = FakeDocuments([row], {row["uri"]: identity_xml("PANCR")})
    monkeypatch.setattr(
        "app.services.digilocker_identity_service.notify_identity_result", AsyncMock()
    )
    session, discovery = await service(harness, docs)
    try:
        available = await discovery.available_records(harness.ids[0])
        selected = available["identity"][0]["candidate_id"]
        with pytest.raises(ValidationAppError):
            await discovery.import_records(
                harness.ids[0], [selected], consent=False, consent_version="v1"
            )
        first = await discovery.import_records(
            harness.ids[0], [selected], consent=True, consent_version="v1"
        )
        second = await discovery.import_records(
            harness.ids[0], [selected], consent=True, consent_version="v1"
        )
    finally:
        await session.close()
    assert first["outcomes"][0]["status"] == "imported"
    assert second["outcomes"][0]["status"] == "already_added"
    async with async_session_factory() as check:
        count = await check.scalar(
            select(func.count())
            .select_from(DigiLockerIdentityVerification)
            .where(DigiLockerIdentityVerification.user_id == harness.ids[0])
        )
    assert count == 1


async def test_identity_import_verifies_exact_selected_same_doctype_document(harness, monkeypatch):
    await prepare_user(harness)
    first = issued("PANCR", suffix="FIRST")
    second = issued("PANCR", suffix="SECOND")
    docs = FakeDocuments(
        [first, second],
        {
            first["uri"]: identity_xml("PANCR"),
            second["uri"]: identity_xml("PANCR"),
        },
    )
    monkeypatch.setattr(
        "app.services.digilocker_identity_service.notify_identity_result", AsyncMock()
    )
    session, discovery = await service(harness, docs)
    try:
        available = await discovery.available_records(harness.ids[0])
        selected = available["identity"][1]["candidate_id"]
        result = await discovery.import_records(
            harness.ids[0], [selected], consent=True, consent_version="v1"
        )
    finally:
        await session.close()

    assert result["outcomes"][0]["status"] == "imported"
    assert docs.retrieve_calls[-1] == (second["uri"], True)


async def test_education_import_storage_failure_rolls_back_and_cleans_object(harness):
    from app.exceptions import ServiceUnavailableError

    await prepare_user(harness)
    rows = [issued("DGCER"), issued("TRTMP", suffix="TWO")]
    docs = FakeDocuments(rows, {row["uri"]: education_xml(row["doctype"]) for row in rows})
    storage = FailingStorage()
    session, discovery = await service(harness, docs, storage=storage)
    try:
        available = await discovery.available_records(harness.ids[0])
        selected = available["education"][0]["candidate_id"]
        with pytest.raises(ServiceUnavailableError):
            await discovery.import_records(
                harness.ids[0], [selected], consent=False, consent_version="v1"
            )
    finally:
        await session.close()
    assert storage.objects == {}
    async with async_session_factory() as check:
        count = await check.scalar(
            select(func.count()).select_from(Education).where(Education.user_id == harness.ids[0])
        )
    assert count == 0


async def test_address_selection_never_mutates_permanent_address(harness):
    await prepare_user(harness)
    row = issued("DRVLC")
    docs = FakeDocuments([row], {row["uri"]: identity_xml("DRVLC")})
    session, discovery = await service(harness, docs)
    try:
        available = await discovery.available_records(harness.ids[0])
        selected = available["address_candidates"][0]["candidate_id"]
        result = await discovery.import_records(
            harness.ids[0], [selected], consent=False, consent_version="v1"
        )
    finally:
        await session.close()
    assert result["outcomes"] == [
        {
            "candidate_id": selected,
            "domain": "address",
            "status": "use_address_save",
            "record_id": None,
            "verification_id": None,
            "evidence_count": 0,
            "review_state": "ready",
        }
    ]


async def test_invalid_or_duplicate_selection_fails_without_mutation(harness):
    await prepare_user(harness)
    row = issued("DGCER")
    docs = FakeDocuments([row], {row["uri"]: education_xml("DGCER")})
    session, discovery = await service(harness, docs)
    try:
        with pytest.raises(ValidationAppError):
            await discovery.import_records(
                harness.ids[0], ["dl1_invalid"], consent=False, consent_version="v1"
            )
        available = await discovery.available_records(harness.ids[0])
        selected = available["education"][0]["candidate_id"]
        with pytest.raises(ValidationAppError):
            await discovery.import_records(
                harness.ids[0], [selected, selected], consent=False, consent_version="v1"
            )
    finally:
        await session.close()
    async with async_session_factory() as check:
        assert (
            await check.scalar(
                select(func.count())
                .select_from(Education)
                .where(Education.user_id == harness.ids[0])
            )
            == 0
        )


async def test_routes_require_auth_hide_cache_and_reject_client_document_metadata():
    previous = app.dependency_overrides.copy()
    now = datetime.now(UTC)
    fake = SimpleNamespace(
        available_records=AsyncMock(
            return_value={
                "identity": [],
                "education": [],
                "address_candidates": [],
                "counts": {
                    "total_issued": 0,
                    "supported": 0,
                    "unsupported": 0,
                    "identity": 0,
                    "education": 0,
                    "address_candidates": 0,
                    "xml_available": 0,
                    "pdf_only": 0,
                    "parse_failures": 0,
                    "malformed": 0,
                },
                "discovered_at": now,
            }
        ),
        import_records=AsyncMock(return_value={"outcomes": [], "completed_at": now}),
    )
    app.dependency_overrides[get_discovery_service] = lambda: fake
    base = "/api/v1/integrations/digilocker"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            assert (await client.get(base + "/available-records")).status_code == 401
            assert (
                await client.post(
                    base + "/records/import",
                    json={"candidate_ids": ["dl1_synthetic_candidate"]},
                )
            ).status_code == 401
            user = CurrentUser(id=uuid4(), email="synthetic@example.invalid", role="user")
            app.dependency_overrides[get_current_user] = lambda: user
            response = await client.get(base + "/available-records")
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            fake.available_records.assert_awaited_once_with(user.id)
            invalid = await client.post(
                base + "/records/import",
                json={
                    "candidate_ids": ["dl1_synthetic_candidate"],
                    "issuer": "client-controlled",
                },
            )
            assert invalid.status_code == 422
            response = await client.post(
                base + "/records/import",
                json={
                    "candidate_ids": ["dl1_synthetic_candidate"],
                    "consent": True,
                    "consent_version": "v1",
                },
            )
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            fake.import_records.assert_awaited_once_with(
                user.id,
                ["dl1_synthetic_candidate"],
                education_targets={},
                consent=True,
                consent_version="v1",
            )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
