"""Canonical DigiLocker document routing metadata for dynamic discovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Domain = Literal["identity", "education"]


@dataclass(frozen=True, slots=True)
class DocumentRoute:
    doctype: str
    domain: Domain
    record_type: str
    display_type: str
    parser_strategy: str
    evidence_type: str | None = None
    group_strategy: str | None = None
    secondary_uses: tuple[str, ...] = ()


def _education(
    doctype: str,
    record_type: str,
    display_type: str,
    evidence_type: str,
    *,
    parser_strategy: str = "education_certificate",
    group_strategy: str = "qualification",
) -> DocumentRoute:
    return DocumentRoute(
        doctype=doctype,
        domain="education",
        record_type=record_type,
        display_type=display_type,
        parser_strategy=parser_strategy,
        evidence_type=evidence_type,
        group_strategy=group_strategy,
    )


DOCUMENT_ROUTES: dict[str, DocumentRoute] = {
    "PANCR": DocumentRoute("PANCR", "identity", "pan", "PAN", "identity_certificate"),
    "DRVLC": DocumentRoute(
        "DRVLC",
        "identity",
        "driving_licence",
        "Driving Licence",
        "identity_certificate",
        secondary_uses=("permanent_address_candidate",),
    ),
    "SSCER": _education(
        "SSCER", "class_x", "Class X Marksheet", "marksheet", group_strategy="class_x"
    ),
    "SPCER": _education(
        "SPCER",
        "class_x",
        "Class X Passing Certificate",
        "passing_certificate",
        group_strategy="class_x",
    ),
    "SSMGR": _education(
        "SSMGR",
        "class_x",
        "Class X Migration Certificate",
        "migration_certificate",
        group_strategy="class_x",
    ),
    "HSCER": _education(
        "HSCER", "class_xii", "Class XII Marksheet", "marksheet", group_strategy="class_xii"
    ),
    "HPCER": _education(
        "HPCER",
        "class_xii",
        "Class XII Passing Certificate",
        "passing_certificate",
        group_strategy="class_xii",
    ),
    "HSMGR": _education(
        "HSMGR",
        "class_xii",
        "Class XII Migration Certificate",
        "migration_certificate",
        group_strategy="class_xii",
    ),
    "PACER": _education("PACER", "qualification", "Passing Certificate", "passing_certificate"),
    "DGCER": _education("DGCER", "degree", "Degree / Diploma Certificate", "degree_certificate"),
    "DGMST": _education("DGMST", "degree", "Degree / Diploma Marksheet", "marksheet"),
    "DIPCR": _education("DIPCR", "diploma", "Diploma Certificate", "degree_certificate"),
    "PRVCR": _education("PRVCR", "degree", "Provisional Degree Certificate", "degree_certificate"),
    "PVCER": _education("PVCER", "qualification", "Provisional Certificate", "degree_certificate"),
    "TRTMP": _education("TRTMP", "qualification", "Transcript", "transcript"),
    "MICER": _education("MICER", "qualification", "Migration Certificate", "migration_certificate"),
}


SUPPORTED_DOCTYPES = frozenset(DOCUMENT_ROUTES)
IDENTITY_DOCTYPES = frozenset(
    doctype for doctype, route in DOCUMENT_ROUTES.items() if route.domain == "identity"
)
EDUCATION_DOCTYPES = frozenset(
    doctype for doctype, route in DOCUMENT_ROUTES.items() if route.domain == "education"
)


def route_for(doctype: str) -> DocumentRoute | None:
    return DOCUMENT_ROUTES.get(doctype)
