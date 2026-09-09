"""Deterministic source-header normalization and alias mapping."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping

from app.exceptions import ValidationAppError
from app.organization_roster_import.constants import EMPLOYEE_FIELDS, STUDENT_FIELDS
from app.organization_roster_import.enums import OrganizationRosterType
from app.organization_roster_import.types import MappingAnalysis, SourceColumn

_HEADER_SEPARATOR_RE = re.compile(r"[^\w]+", re.UNICODE)
_REPEATED_UNDERSCORE_RE = re.compile(r"_+")

EMPLOYEE_TEMPLATE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("Employee ID", "employee_id"),
    ("Full Name", "full_name"),
    ("Work Email", "work_email"),
    ("Phone", "phone"),
    ("Department", "department"),
    ("Designation", "designation"),
    ("Employment Type", "employment_type"),
    ("Joining Date", "joining_date"),
    ("Exit Date", "exit_date"),
    ("Employment Status", "employment_status"),
    ("Location", "location"),
)

STUDENT_TEMPLATE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("Student ID", "student_id"),
    ("Full Name", "full_name"),
    ("Institution Email", "institutional_email"),
    ("Phone", "phone"),
    ("Degree", "degree"),
    ("Program", "program"),
    ("Specialization", "specialization"),
    ("Department", "department"),
    ("Admission Date", "admission_date"),
    ("Graduation Date", "graduation_date"),
    ("Enrollment Status", "enrollment_status"),
    ("Campus", "campus"),
    ("Cohort", "cohort"),
)


def normalize_header(value: str) -> str:
    """Return a stable, punctuation-insensitive source key."""

    normalized = unicodedata.normalize("NFKC", value).replace("\ufeff", "").strip().casefold()
    normalized = _HEADER_SEPARATOR_RE.sub("_", normalized)
    return _REPEATED_UNDERSCORE_RE.sub("_", normalized).strip("_")


def build_source_columns(headers: Iterable[object]) -> tuple[SourceColumn, ...]:
    columns: list[SourceColumn] = []
    seen: dict[str, str] = {}
    for raw in headers:
        original = "" if raw is None else str(raw).strip()
        effective = normalize_header(original)
        if not effective:
            raise ValidationAppError("Header columns must have a name", code="invalid_header")
        if effective in seen:
            raise ValidationAppError(
                f"Duplicate or ambiguous header: {original}",
                code="duplicate_header",
            )
        seen[effective] = original
        columns.append(SourceColumn(original=original, normalized=effective))
    return tuple(columns)


_EMPLOYEE_ALIASES: dict[str, tuple[str, ...]] = {
    "employee_id": ("employee id", "emp id", "employee code", "staff id", "staff code"),
    "full_name": ("full name", "employee name", "name"),
    "first_name": ("first name",),
    "last_name": ("last name", "surname"),
    "work_email": ("work email", "official email", "company email", "corporate email"),
    "phone": ("phone", "mobile", "mobile number", "phone number"),
    "department": ("department", "dept"),
    "designation": ("designation", "job title", "role"),
    "employment_type": ("employment type", "worker type"),
    "joining_date": ("joining date", "date of joining", "doj", "start date"),
    "exit_date": ("exit date", "last working date", "end date"),
    "employment_status": ("employment status", "employee status", "status"),
    "location": ("location", "office location", "work location"),
}

_STUDENT_ALIASES: dict[str, tuple[str, ...]] = {
    "student_id": ("student id", "student code", "registration number", "registration no"),
    "roll_number": ("roll number", "roll no", "roll"),
    "full_name": ("full name", "student name", "name"),
    "first_name": ("first name",),
    "last_name": ("last name", "surname"),
    "institutional_email": (
        "institution email",
        "institutional email",
        "college email",
        "university email",
        "official email",
    ),
    "phone": ("phone", "mobile", "mobile number", "phone number"),
    "degree": ("degree",),
    "program": ("program", "programme", "course"),
    "specialization": ("specialization", "major"),
    "department": ("department", "dept"),
    "admission_date": ("admission date", "date of admission", "start date"),
    "graduation_date": ("graduation date", "passing date", "completion date", "end date"),
    "enrollment_status": ("enrollment status", "student status", "status"),
    "campus": ("campus",),
    "cohort": ("cohort", "batch"),
}


def allowed_fields(roster_type: OrganizationRosterType | str) -> frozenset[str]:
    parsed = OrganizationRosterType(roster_type)
    return EMPLOYEE_FIELDS if parsed is OrganizationRosterType.EMPLOYEE else STUDENT_FIELDS


def template_columns(
    roster_type: OrganizationRosterType | str,
) -> tuple[tuple[str, str], ...]:
    parsed = OrganizationRosterType(roster_type)
    return (
        EMPLOYEE_TEMPLATE_COLUMNS
        if parsed is OrganizationRosterType.EMPLOYEE
        else STUDENT_TEMPLATE_COLUMNS
    )


def alias_dictionary(roster_type: OrganizationRosterType | str) -> dict[str, str]:
    aliases = (
        _EMPLOYEE_ALIASES
        if OrganizationRosterType(roster_type) is OrganizationRosterType.EMPLOYEE
        else _STUDENT_ALIASES
    )
    result: dict[str, str] = {}
    for canonical, names in aliases.items():
        for name in (*names, canonical):
            normalized = normalize_header(name)
            existing = result.get(normalized)
            if existing is not None and existing != canonical:
                raise RuntimeError(f"Ambiguous roster alias configuration: {normalized}")
            result[normalized] = canonical
    for display_name, canonical in template_columns(roster_type):
        normalized = normalize_header(display_name)
        existing = result.get(normalized)
        if existing is not None and existing != canonical:
            raise RuntimeError(f"Ambiguous roster template header: {normalized}")
        result[normalized] = canonical
    return result


def required_mapping_gaps(
    roster_type: OrganizationRosterType | str,
    mappings: Mapping[str, str],
) -> tuple[str, ...]:
    targets = set(mappings.values())
    identity_fields = (
        {"employee_id", "work_email"}
        if OrganizationRosterType(roster_type) is OrganizationRosterType.EMPLOYEE
        else {"student_id", "roll_number", "institutional_email"}
    )
    gaps: list[str] = []
    if not targets.intersection(identity_fields):
        gaps.append("identity")
    if "full_name" not in targets and not targets.intersection({"first_name", "last_name"}):
        gaps.append("name")
    return tuple(gaps)


def analyze_mapping(
    roster_type: OrganizationRosterType | str,
    columns: tuple[SourceColumn, ...],
    mappings: Mapping[str, str] | None = None,
) -> MappingAnalysis:
    alias_lookup = alias_dictionary(roster_type)
    proposed = (
        {
            column.normalized: alias_lookup[column.normalized]
            for column in columns
            if column.normalized in alias_lookup
        }
        if mappings is None
        else dict(mappings)
    )
    target_sources: dict[str, list[str]] = defaultdict(list)
    for source, target in proposed.items():
        target_sources[target].append(source)

    ambiguous: list[str] = []
    accepted = dict(proposed)
    for target, sources in target_sources.items():
        if len(sources) <= 1:
            continue
        ambiguous.append(target)
        for source in sources:
            accepted.pop(source, None)

    source_keys = {column.normalized for column in columns}
    unmapped = tuple(column.normalized for column in columns if column.normalized not in accepted)
    unknown_mapping_sources = set(accepted).difference(source_keys)
    if unknown_mapping_sources:
        raise ValidationAppError("Mapping references an unknown source column")

    return MappingAnalysis(
        mappings=accepted,
        unmapped_source_columns=unmapped,
        missing_required_mappings=required_mapping_gaps(roster_type, accepted),
        ambiguous_mappings=tuple(sorted(ambiguous)),
        warnings=(),
    )


def apply_manual_mapping(
    roster_type: OrganizationRosterType | str,
    columns: tuple[SourceColumn, ...],
    current: Mapping[str, str],
    assignments: Iterable[tuple[str, str | None]],
) -> MappingAnalysis:
    source_lookup = {column.normalized: column for column in columns}
    aliases = alias_dictionary(roster_type)
    allowed = allowed_fields(roster_type)
    updated = dict(current)
    seen_sources: set[str] = set()

    for raw_source, target in assignments:
        source = normalize_header(raw_source)
        if source in seen_sources:
            raise ValidationAppError(
                f"Source column is assigned more than once: {raw_source}",
                code="duplicate_mapping_source",
            )
        seen_sources.add(source)
        if source not in source_lookup:
            raise ValidationAppError(
                f"Unknown source column: {raw_source}", code="unknown_source_column"
            )
        if target is None:
            updated.pop(source, None)
            continue
        if target not in allowed or target.endswith("_precision"):
            raise ValidationAppError(
                f"Canonical field is not available for this roster: {target}",
                code="invalid_mapping_target",
            )
        recognized_target = aliases.get(source)
        if recognized_target is not None and _field_kind(recognized_target) != _field_kind(target):
            raise ValidationAppError(
                f"Source column {raw_source} is incompatible with {target}",
                code="incompatible_mapping",
            )
        updated[source] = target

    duplicates = [target for target, count in _target_counts(updated).items() if count > 1]
    if duplicates:
        raise ValidationAppError(
            f"Multiple source columns map to: {', '.join(sorted(duplicates))}",
            code="duplicate_mapping_target",
        )
    return analyze_mapping(roster_type, columns, updated)


def _target_counts(mappings: Mapping[str, str]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for target in mappings.values():
        counts[target] += 1
    return counts


def _field_kind(field: str) -> str:
    if field.endswith("email"):
        return "email"
    if field == "phone":
        return "phone"
    if field.endswith("_date"):
        return "date"
    if field.endswith("_id") or field == "roll_number":
        return "identifier"
    if field in {"full_name", "first_name", "last_name"}:
        return "name"
    return "text"
