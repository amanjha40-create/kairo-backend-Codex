"""Privacy-safe parsing and deterministic resolution data for Education documents."""

from __future__ import annotations

import base64
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from xml.etree.ElementTree import Element, ParseError

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring

from app.integrations.digilocker.identity import MAX_XML_BYTES
from app.integrations.digilocker.registry import DocumentRoute


@dataclass(frozen=True, slots=True, repr=False)
class ParsedEducation:
    institution_name: str | None
    qualification: str | None
    field_of_study: str | None
    completion_year: int | None
    education_level: str
    parser_status: str


@dataclass(frozen=True, slots=True, repr=False)
class ParsedAddress:
    address_line_1: str
    address_line_2: str | None
    locality: str | None
    city: str
    state: str
    postal_code: str
    country: str = "IN"


def _clean(value: object, limit: int = 512) -> str:
    if not isinstance(value, str):
        return ""
    value = unicodedata.normalize("NFKC", value).strip()
    if len(value) > limit or any(ord(char) < 32 for char in value):
        return ""
    return re.sub(r"\s+", " ", value)


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _certificate(content: bytes) -> Element:
    if not content or len(content) > MAX_XML_BYTES:
        raise ValueError()
    root = fromstring(content, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    if sum(1 for _ in root.iter()) > 500:
        raise ValueError()
    for node in root.iter():
        node.tag = node.tag.rsplit("}", 1)[-1]
    if root.tag == "PullDocResponse":
        statuses = root.findall("ResponseStatus")
        containers = root.findall("./DocDetails/DataContent")
        if len(statuses) != 1 or statuses[0].get("status") != "1" or len(containers) != 1:
            raise ValueError()
        encoded = "".join((containers[0].text or "").split())
        return _certificate(base64.b64decode(encoded, validate=True))
    if root.tag != "Certificate":
        raise ValueError()
    return root


def _attributes(root: Element) -> dict[str, str]:
    values: dict[str, str] = {}
    for node in root.iter():
        for name, value in node.attrib.items():
            normalized = _clean(value)
            if normalized:
                values.setdefault(_key(name), normalized)
    return values


def _first(values: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = values.get(_key(key))
        if value:
            return value
    return None


def _year(values: dict[str, str]) -> int | None:
    for key in ("year", "passingYear", "completionYear", "issueDate", "date"):
        value = _first(values, key)
        if not value:
            continue
        match = re.search(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", value)
        if match:
            year = int(match.group(1))
            if 1950 <= year <= date.today().year + 1:
                return year
    return None


def parse_education_xml(
    content: bytes,
    *,
    doctype: str,
    route: DocumentRoute,
    issuer_name: str | None,
) -> ParsedEducation:
    try:
        root = _certificate(content)
        if root.get("type") not in {None, "", doctype}:
            raise ValueError()
        values = _attributes(root)
        institution = _first(
            values,
            "institutionName",
            "universityName",
            "university",
            "collegeName",
            "schoolName",
            "boardName",
            "board",
            "instituteName",
        ) or _clean(issuer_name)
        if route.group_strategy == "class_x":
            qualification, level = "Class X", "high_school"
        elif route.group_strategy == "class_xii":
            qualification, level = "Class XII", "high_school"
        else:
            qualification = _first(
                values,
                "qualification",
                "qualificationName",
                "degree",
                "degreeName",
                "course",
                "courseName",
                "programme",
                "programName",
            )
            level = "diploma" if route.record_type == "diploma" else "other"
        specialization = _first(
            values, "specialization", "specialisation", "stream", "branch", "fieldOfStudy"
        )
        parsed = bool(institution and qualification)
        return ParsedEducation(
            institution_name=institution or None,
            qualification=qualification,
            field_of_study=specialization,
            completion_year=_year(values),
            education_level=level,
            parser_status="parsed" if parsed else "needs_review",
        )
    except (ValueError, TypeError, ParseError, DefusedXmlException, RecursionError):
        return ParsedEducation(None, None, None, None, "other", "parse_failed")


def parse_driving_licence_address(content: bytes) -> ParsedAddress | None:
    try:
        root = _certificate(content)
        if root.get("type") != "DRVLC":
            return None
        values = _attributes(root)
        line1 = _first(
            values,
            "addressLine1",
            "address",
            "permanentAddress",
            "house",
            "premise",
        )
        line2 = _first(values, "addressLine2", "street", "road")
        locality = _first(values, "locality", "village", "town", "subDistrict")
        city = _first(values, "city", "district")
        state = _first(values, "state", "stateName")
        postal = _first(values, "pincode", "pin", "postalCode")
        country = (_first(values, "country", "countryCode") or "IN").upper()
        if not (
            line1
            and city
            and state
            and postal
            and re.fullmatch(r"[1-9][0-9]{5}", postal)
            and country in {"IN", "IND", "INDIA"}
        ):
            return None
        return ParsedAddress(
            address_line_1=line1[:160],
            address_line_2=line2[:160] if line2 else None,
            locality=locality[:100] if locality else None,
            city=city[:100],
            state=state[:100],
            postal_code=postal,
        )
    except (ValueError, TypeError, ParseError, DefusedXmlException, RecursionError):
        return None
