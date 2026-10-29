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

# Some boards list the Class X passing certificate as SPCER while the signed
# certificate uses the generic SSCER schema type. Keep the alias one-way so an
# unrelated document type can never be accepted for another route.
_DOCTYPE_ROOT_ALIASES: dict[str, frozenset[str]] = {
    "SPCER": frozenset({"SSCER"}),
}


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


@dataclass(frozen=True, slots=True, repr=False)
class AddressParseResult:
    address: ParsedAddress | None
    reason: str
    address_node_count: int = 0
    selected_type: str | None = None
    missing_fields: tuple[str, ...] = ()


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


def _local_name(node: Element) -> str:
    return node.tag.rsplit("}", 1)[-1] if isinstance(node.tag, str) else ""


def _person_address_nodes(root: Element) -> list[Element]:
    """Return Candidate addresses only; never consider IssuedBy organization data."""
    addresses: list[Element] = []
    address_tags = {
        "address",
        "permanentaddress",
        "presentaddress",
        "currentaddress",
        "postaladdress",
    }
    address_keys = {
        _key(name)
        for name in (
            "line1",
            "addressLine1",
            "address",
            "permanentAddress",
            "house",
            "houseNo",
            "houseNumber",
            "premise",
            "building",
            "street",
            "road",
            "vtc",
            "city",
            "district",
            "pin",
            "pincode",
            "postalCode",
            "state",
            "stateName",
            "country",
            "countryCode",
        )
    }
    for issued_to in root.iter():
        if _key(_local_name(issued_to)) != "issuedto":
            continue
        for person in issued_to.iter():
            if _key(_local_name(person)) != "person":
                continue
            person_addresses = [
                node
                for node in person.iter()
                if node is not person
                and (
                    _key(_local_name(node)) in address_tags
                    or _key(_local_name(node)).endswith("address")
                )
            ]
            if person_addresses:
                addresses.extend(person_addresses)
            elif address_keys & {_key(name) for name in person.attrib}:
                # Some older issuer variants place address attributes on Person.
                addresses.append(person)
    return addresses


def _address_type(node: Element) -> str | None:
    values = {_key(name): _clean(value) for name, value in node.attrib.items()}
    raw = _first(values, "addressType", "addrType", "residenceType", "type")
    if not raw:
        tag = _key(_local_name(node))
        if tag == "permanentaddress":
            return "permanent"
        if tag in {"presentaddress", "currentaddress"}:
            return "present"
        return None
    normalized = _key(raw)
    if normalized in {"permanent", "perm", "p"}:
        return "permanent"
    if normalized in {
        "present",
        "current",
        "mailing",
        "official",
        "correspondence",
    }:
        return "present_or_current"
    return "other"


def _select_address_node(nodes: list[Element]) -> tuple[Element | None, str, str | None]:
    if not nodes:
        return None, "ADDRESS_NODE_NOT_FOUND", None
    typed = [(node, _address_type(node)) for node in nodes]
    permanent = [node for node, address_type in typed if address_type == "permanent"]
    if len(permanent) == 1:
        return permanent[0], "COMPLETE", "permanent"
    if len(permanent) > 1:
        return None, "ADDRESS_AMBIGUOUS", None
    if len(typed) == 1 and typed[0][1] is None:
        return typed[0][0], "COMPLETE", "untyped"
    if len(typed) == 1:
        return None, "ADDRESS_TYPE_UNSUPPORTED", typed[0][1]
    return None, "ADDRESS_AMBIGUOUS", None


def _parts(*values: str | None, limit: int) -> str | None:
    parts: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _clean(value)
        normalized = _key(cleaned)
        if cleaned and normalized and normalized not in seen:
            parts.append(cleaned)
            seen.add(normalized)
    combined = ", ".join(parts)
    return combined[:limit].rstrip(" ,") or None


def parse_education_xml(
    content: bytes,
    *,
    doctype: str,
    route: DocumentRoute,
    issuer_name: str | None,
) -> ParsedEducation:
    try:
        root = _certificate(content)
        if root.get("type") not in {
            None,
            "",
            doctype,
            *_DOCTYPE_ROOT_ALIASES.get(doctype, ()),
        }:
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


def parse_driving_licence_address_result(content: bytes) -> AddressParseResult:
    try:
        root = _certificate(content)
        if root.get("type") != "DRVLC":
            return AddressParseResult(None, "DOCUMENT_TYPE_MISMATCH")
        nodes = _person_address_nodes(root)
        selected, reason, selected_type = _select_address_node(nodes)
        if selected is None:
            return AddressParseResult(
                None,
                reason,
                address_node_count=len(nodes),
                selected_type=selected_type,
            )
        values = _attributes(selected)
        line1 = _parts(
            _first(values, "house", "houseNo", "houseNumber", "premise", "building"),
            _first(values, "line1", "addressLine1", "address", "permanentAddress"),
            _first(values, "street", "road"),
            limit=160,
        )
        line2 = _parts(
            _first(values, "line2", "addressLine2"),
            _first(values, "landmark"),
            limit=160,
        )
        vtc = _first(values, "vtc", "village", "town", "subDistrict")
        locality = _first(values, "locality") or vtc
        city = _first(values, "city") or vtc or _first(values, "district")
        state = _first(values, "state", "stateName")
        postal = _first(values, "pincode", "pin", "postalCode")
        country = _first(values, "country", "countryCode")
        missing = tuple(
            name
            for name, value in (
                ("address_line_1", line1),
                ("city", city),
                ("state", state),
                ("postal_code", postal),
                ("country", country),
            )
            if not value
        )
        if missing:
            return AddressParseResult(
                None,
                "REQUIRED_FIELD_MISSING",
                address_node_count=len(nodes),
                selected_type=selected_type,
                missing_fields=missing,
            )
        if not re.fullmatch(r"[1-9][0-9]{5}", postal):
            return AddressParseResult(
                None,
                "PIN_INVALID",
                address_node_count=len(nodes),
                selected_type=selected_type,
            )
        if _key(country) not in {"in", "ind", "india"}:
            return AddressParseResult(
                None,
                "COUNTRY_UNSUPPORTED",
                address_node_count=len(nodes),
                selected_type=selected_type,
            )
        return AddressParseResult(
            ParsedAddress(
                address_line_1=line1,
                address_line_2=line2,
                locality=locality[:100] if locality else None,
                city=city[:100],
                state=state[:100],
                postal_code=postal,
            ),
            "COMPLETE",
            address_node_count=len(nodes),
            selected_type=selected_type,
        )
    except (ValueError, TypeError, ParseError, DefusedXmlException, RecursionError):
        return AddressParseResult(None, "MALFORMED_XML")


def parse_driving_licence_address(content: bytes) -> ParsedAddress | None:
    return parse_driving_licence_address_result(content).address
