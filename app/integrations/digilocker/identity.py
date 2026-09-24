"""Deterministic matching of bounded XML certificates; never OCR or infer identity."""

import base64
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from xml.etree.ElementTree import ParseError

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring

MAX_XML_BYTES = 1024 * 1024


@dataclass(frozen=True, repr=False)
class Match:
    result: str
    valid_until: date | None = None
    category: str = "XML_SUPPORTED"
    diagnostics: dict = field(default_factory=dict)


def _match_diagnostics(given, expected, birth, dob):
    name_bad = bool(given and expected and given != expected)
    dob_bad = bool(birth and dob and birth != dob)
    reason = (
        "NAME_AND_DOB_MISMATCH"
        if name_bad and dob_bad
        else "NAME_MISMATCH"
        if name_bad
        else "DOB_MISMATCH"
        if dob_bad
        else "REQUIRED_FIELD_MISSING"
        if not all([given, expected, birth, dob])
        else "OTHER"
    )
    return {
        "document_name_present": bool(given),
        "document_dob_present": bool(birth),
        "profile_name_present": bool(expected),
        "profile_dob_present": bool(dob),
        "normalized_name_exact_match": bool(given and expected and given == expected),
        # Diagnostic only. Token reordering never changes the matching decision.
        "normalized_name_token_match": bool(
            given and expected and Counter(given.split()) == Counter(expected.split())
        ),
        "normalized_dob_match": bool(birth and dob and birth == dob),
        "mismatch_reason": reason,
    }


def normalize_name(value):
    if not isinstance(value, str) or len(value) > 255:
        return ""
    value = unicodedata.normalize("NFKC", value).casefold()
    # Only spacing and periods are normalized. No token sorting, initials or fuzzy match.
    if any(unicodedata.category(c).startswith("C") for c in value):
        return ""
    return " ".join(value.replace(".", " ").split())


def _date(value):
    if not value:
        return None
    for pattern, fmt in [(r"\d{2}-\d{2}-\d{4}", "%d-%m-%Y"), (r"\d{4}-\d{2}-\d{2}", "%Y-%m-%d")]:
        if re.fullmatch(pattern, value):
            return datetime.strptime(value, fmt).date()
    raise ValueError()


def _xml(content):
    if not content or len(content) > MAX_XML_BYTES:
        raise ValueError()
    root = fromstring(content, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    if sum(1 for _ in root.iter()) > 500:
        raise ValueError()
    # Accept namespace-qualified standard structures, never search arbitrary descendant Persons.
    for node in root.iter():
        node.tag = node.tag.rsplit("}", 1)[-1]
    return root


def match_document(document, doctype, name, dob, today):
    """Called only after the provider's HMAC gate. Return no extracted personal facts."""
    diagnostic = {"parser_guard": "NONE", "structural_category": "SUPPORTED"}

    def rejected(category, guard, structure, until=None):
        return Match(
            "UNABLE_TO_VERIFY",
            until,
            category,
            diagnostic
            | {
                "parser_guard": guard,
                "structural_category": structure,
            },
        )

    try:
        if doctype not in {"PANCR", "DRVLC"} or document.mime not in {
            "application/xml",
            "text/xml",
        }:
            return rejected("UNSUPPORTED_MIME", "MIME_OR_DOCTYPE", "OTHER")
        root = _xml(document.content)
        if root.tag == "PullDocResponse":
            statuses = root.findall("ResponseStatus")
            containers = root.findall("./DocDetails/DataContent")
            if len(statuses) != 1 or statuses[0].get("status") != "1" or len(containers) != 1:
                return rejected(
                    "PROVIDER_RESPONSE_INVALID", "ENVELOPE_LAYOUT", "EXPECTED_NODE_MISSING"
                )
            # Official envelope carries one base64 certificate. Never parse DocContent/PDF.
            root = _xml(
                base64.b64decode("".join((containers[0].text or "").split()), validate=True)
            )
        if root.tag != "Certificate":
            return rejected("PROVIDER_RESPONSE_INVALID", "ROOT", "UNEXPECTED_ROOT")
        if root.get("type") != doctype:
            return rejected(
                "PROVIDER_RESPONSE_INVALID", "CERTIFICATE_TYPE", "SCHEMA_VERSION_VARIANT"
            )
        persons = root.findall("./IssuedTo/Person")
        if len(persons) != 1:
            return rejected(
                "MISSING_REQUIRED_FIELDS", "PERSON_CARDINALITY", "EXPECTED_NODE_MISSING"
            )
        person = persons[0]
        given, expected = normalize_name(person.get("name")), normalize_name(name)
        try:
            birth = _date(person.get("dob"))
            until = _date(root.get("expiryDate")) if doctype == "DRVLC" else None
            start = _date(root.get("validFromDate"))
        except (ValueError, TypeError):
            return rejected("PROVIDER_RESPONSE_INVALID", "DATE_FORMAT", "ATTRIBUTE_LAYOUT_VARIANT")
        diagnostic.update(_match_diagnostics(given, expected, birth, dob))
        if birth and birth > today:
            return rejected("PROVIDER_RESPONSE_INVALID", "DOB_CURRENTNESS", "OTHER")
        status = root.get("status")
        # Observed HMAC-authenticated DRVLC Certificate variant; no fuzzy status matching.
        active_variant = doctype == "DRVLC" and status == "Active"
        if active_variant:
            diagnostic["structural_category"] = "ATTRIBUTE_LAYOUT_VARIANT"
        if status not in {None, "", "A"} and not active_variant:
            return rejected(
                "PROVIDER_RESPONSE_INVALID", "CERTIFICATE_STATUS", "ATTRIBUTE_LAYOUT_VARIANT", until
            )
        if (until and until < today) or (start and start > today):
            return rejected("PROVIDER_RESPONSE_INVALID", "VALIDITY_CURRENTNESS", "OTHER", until)
        if (given and expected and given != expected) or (birth and dob and birth != dob):
            return Match("MISMATCH", until, diagnostics=diagnostic)
        if given and expected and birth and dob:
            return Match("VERIFIED_MATCH", until, diagnostics=diagnostic)
        if (given and expected) or (birth and dob):
            return Match("PARTIAL_MATCH", until, diagnostics=diagnostic)
        return Match("UNABLE_TO_VERIFY", until, "IDENTITY_FIELDS_NOT_AVAILABLE", diagnostic)
    except (ValueError, TypeError, ParseError, DefusedXmlException, RecursionError):
        return rejected("MALFORMED_XML", "XML_PARSE", "INVALID_XML")
