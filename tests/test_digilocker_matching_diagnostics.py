"""Synthetic-only fixtures for the observed DRVLC status attribute variant."""

from datetime import date

import pytest
from test_digilocker_identity import DOB, TODAY, certificate, identity  # noqa: F401
from test_digilocker_lifecycle import harness  # noqa: F401

from app.integrations.digilocker.documents import RetrievedDocument
from app.integrations.digilocker.identity import match_document


def observed_dl(
    *,
    status="Active",
    namespace="",
    person=True,
    optional=True,
    name="Test Candidate",
    dob="02-01-1990",
    expiry="24-09-2030",
):
    xml = (
        f'<Certificate {namespace} type="DRVLC" status="{status}" number="PRIVATE-LICENCE-CANARY" '
        f'issueDate="01-01-2020" validFromDate="01-01-2020" expiryDate="{expiry}">'
        + ('<IssuedBy><Organization name="SYNTHETIC ISSUER"/></IssuedBy>' if optional else "")
        + "<IssuedTo>"
        + (
            f'<Person name="{name}" dob="{dob}" uid="PRIVATE-ID-CANARY" '
            'gender="" swd="" swdIndicator=""/>'
            if person
            else ""
        )
        + "</IssuedTo>"
        + ("<CertificateData><DrivingLicense/></CertificateData><Signature/>" if optional else "")
        + "</Certificate>"
    )
    return RetrievedDocument(xml.encode(), "application/xml")


@pytest.mark.parametrize("namespace", ["", 'xmlns="urn:synthetic:digilocker:certificate"'])
@pytest.mark.parametrize("optional", [True, False])
def test_observed_active_variant_namespace_and_optional_nodes(namespace, optional):
    result = match_document(
        observed_dl(namespace=namespace, optional=optional), "DRVLC", "Test Candidate", DOB, TODAY
    )
    assert result.result == "VERIFIED_MATCH" and result.category == "XML_SUPPORTED"
    assert result.diagnostics["parser_guard"] == "NONE"
    assert result.diagnostics["structural_category"] == "ATTRIBUTE_LAYOUT_VARIANT"


@pytest.mark.parametrize(
    "status",
    ["R", "E", "S", "Revoked", "Expired", "Inactive", "active", "ACTIVE", "Active ", "UNKNOWN"],
)
def test_only_exact_observed_active_variant_is_supported(status):
    result = match_document(observed_dl(status=status), "DRVLC", "Test Candidate", DOB, TODAY)
    assert result.result == "UNABLE_TO_VERIFY"
    assert result.diagnostics["parser_guard"] == "CERTIFICATE_STATUS"


def test_active_variant_is_not_enabled_for_pan():
    doc = RetrievedDocument(
        certificate().content.replace(b'status="A"', b'status="Active"'), "application/xml"
    )
    assert match_document(doc, "PANCR", "Test Candidate", DOB, TODAY).result == "UNABLE_TO_VERIFY"


@pytest.mark.parametrize("expiry", ["23-09-2026", "invalid"])
def test_active_variant_preserves_date_guards(expiry):
    assert (
        match_document(observed_dl(expiry=expiry), "DRVLC", "Test Candidate", DOB, TODAY).result
        == "UNABLE_TO_VERIFY"
    )


@pytest.mark.parametrize(
    "name,dob,outcome,reason",
    [
        ("Test Candidate", DOB, "VERIFIED_MATCH", "OTHER"),
        (" TEST.   CANDIDATE ", DOB, "VERIFIED_MATCH", "OTHER"),
        ("Ｔｅｓｔ Candidate", DOB, "VERIFIED_MATCH", "OTHER"),
        ("Other Candidate", DOB, "MISMATCH", "NAME_MISMATCH"),
        ("Test Candidate", date(1980, 1, 1), "MISMATCH", "DOB_MISMATCH"),
        ("Other Candidate", date(1980, 1, 1), "MISMATCH", "NAME_AND_DOB_MISMATCH"),
        ("Test Candidate", None, "PARTIAL_MATCH", "REQUIRED_FIELD_MISSING"),
        (None, None, "UNABLE_TO_VERIFY", "REQUIRED_FIELD_MISSING"),
        ("Candidate Test", DOB, "MISMATCH", "NAME_MISMATCH"),
        ("T Candidate", DOB, "MISMATCH", "NAME_MISMATCH"),
    ],
)
@pytest.mark.parametrize("doctype", ["PANCR", "DRVLC"])
def test_conservative_matching_with_safe_boolean_diagnostics(doctype, name, dob, outcome, reason):
    doc = certificate() if doctype == "PANCR" else observed_dl()
    result = match_document(doc, doctype, name, dob, TODAY)
    assert result.result == outcome and result.diagnostics["mismatch_reason"] == reason
    assert all(
        type(v) is bool for k, v in result.diagnostics.items() if k.endswith(("present", "match"))
    )
    if name == "Candidate Test":
        assert result.diagnostics["normalized_name_token_match"]
        assert not result.diagnostics["normalized_name_exact_match"]
    assert "Candidate" not in str(result.diagnostics)
    assert "1990" not in str(result.diagnostics)


@pytest.mark.parametrize(
    "doc,guard",
    [
        (RetrievedDocument(b"bad-xml", "application/xml"), "XML_PARSE"),
        (RetrievedDocument(b"<Unknown/>", "application/xml"), "ROOT"),
        (certificate(), "CERTIFICATE_TYPE"),
        (observed_dl(person=False), "PERSON_CARDINALITY"),
    ],
)
def test_structural_guard_categories_fail_closed(doc, guard):
    result = match_document(doc, "DRVLC", "Test Candidate", DOB, TODAY)
    assert result.result == "UNABLE_TO_VERIFY" and result.diagnostics["parser_guard"] == guard


def test_iso_dob_supported_without_heuristics():
    assert (
        match_document(observed_dl(dob="1990-01-02"), "DRVLC", "Test Candidate", DOB, TODAY).result
        == "VERIFIED_MATCH"
    )


async def test_live_shape_safe_logging_and_existing_row_update(identity, caplog):  # noqa: F811
    t = identity
    t.docs.retrieve.side_effect = lambda token, uri, **kwargs: (
        observed_dl(status="Active") if "DRVLC" in uri else certificate(name="Other Candidate")
    )
    caplog.set_level("INFO", logger="app.services.digilocker_identity_service")
    first = await t.call(["PANCR", "DRVLC"])
    second = await t.call(["PANCR", "DRVLC"])
    assert {r["id"] for r in first["items"]} == {r["id"] for r in second["items"]}
    assert len((await t.call())["items"]) == 2
    assert {r["document_type"]: r["match_result"] for r in second["items"]} == {
        "PANCR": "MISMATCH",
        "DRVLC": "VERIFIED_MATCH",
    }
    logs = [r for r in caplog.records if r.message == "digilocker_identity_match"]
    assert len(logs) == 4
    pan = next(r for r in logs if r.document_type == "PANCR")
    assert pan.mismatch_reason == "NAME_MISMATCH" and pan.normalized_dob_match
    serialized = str([r.__dict__ for r in logs])
    for canary in [
        "Other Candidate",
        "Test Candidate",
        "02-01-1990",
        "PRIVATE-LICENCE-CANARY",
        "PRIVATE-ID-CANARY",
        "<Certificate",
        "SYNTHETIC ISSUER",
    ]:
        assert canary not in serialized
