"""Deterministic matching of bounded XML certificates; never OCR or infer identity."""

import base64
import re
import unicodedata
from dataclasses import dataclass
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
    try:
        if doctype not in {"PANCR", "DRVLC"} or document.mime not in {
            "application/xml",
            "text/xml",
        }:
            return Match("UNABLE_TO_VERIFY", category="UNSUPPORTED_MIME")
        root = _xml(document.content)
        if root.tag == "PullDocResponse":
            statuses = root.findall("ResponseStatus")
            containers = root.findall("./DocDetails/DataContent")
            if len(statuses) != 1 or statuses[0].get("status") != "1" or len(containers) != 1:
                return Match("UNABLE_TO_VERIFY", category="PROVIDER_RESPONSE_INVALID")
            # Official envelope carries one base64 certificate. Never parse DocContent/PDF.
            root = _xml(
                base64.b64decode("".join((containers[0].text or "").split()), validate=True)
            )
        if root.tag != "Certificate" or root.get("type") != doctype:
            return Match("UNABLE_TO_VERIFY", category="PROVIDER_RESPONSE_INVALID")
        persons = root.findall("./IssuedTo/Person")
        if len(persons) != 1:
            return Match("UNABLE_TO_VERIFY", category="MISSING_REQUIRED_FIELDS")
        person = persons[0]
        given, expected = normalize_name(person.get("name")), normalize_name(name)
        try:
            birth = _date(person.get("dob"))
            until = _date(root.get("expiryDate")) if doctype == "DRVLC" else None
            start = _date(root.get("validFromDate"))
        except (ValueError, TypeError):
            return Match("UNABLE_TO_VERIFY", category="PROVIDER_RESPONSE_INVALID")
        if birth and birth > today:
            return Match("UNABLE_TO_VERIFY", category="PROVIDER_RESPONSE_INVALID")
        if (
            root.get("status") not in {None, "", "A"}
            or (until and until < today)
            or (start and start > today)
        ):
            return Match("UNABLE_TO_VERIFY", until, "PROVIDER_RESPONSE_INVALID")
        if (given and expected and given != expected) or (birth and dob and birth != dob):
            return Match("MISMATCH", until)
        if given and expected and birth and dob:
            return Match("VERIFIED_MATCH", until)
        if (given and expected) or (birth and dob):
            return Match("PARTIAL_MATCH", until)
        return Match("UNABLE_TO_VERIFY", until, "IDENTITY_FIELDS_NOT_AVAILABLE")
    except (ValueError, TypeError, ParseError, DefusedXmlException, RecursionError):
        return Match("UNABLE_TO_VERIFY", category="MALFORMED_XML")
