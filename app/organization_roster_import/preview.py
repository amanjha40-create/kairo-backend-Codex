"""Pure preview classification with optional read-only registry resolution."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.organization_roster_import.enums import (
    OrganizationRosterRowDisposition,
    OrganizationRosterType,
)
from app.organization_roster_import.normalization import (
    flatten_normalized_dates,
    normalize_row_values,
)
from app.organization_roster_import.types import (
    MappingAnalysis,
    ParsedRosterFile,
    PreviewRow,
    RegistryMatch,
    RowIssue,
)

RegistryMatcher = Callable[[dict[str, object]], Awaitable[RegistryMatch]]
RegistryBatchMatcher = Callable[
    [tuple[dict[str, object], ...]], Awaitable[tuple[RegistryMatch, ...]]
]


@dataclass(frozen=True, slots=True)
class PreviewResult:
    rows: tuple[PreviewRow, ...]
    total_rows: int
    valid_new_count: int
    valid_update_count: int
    duplicate_count: int
    invalid_count: int
    skipped_count: int


async def build_preview(
    parsed: ParsedRosterFile,
    mapping: MappingAnalysis,
    roster_type: OrganizationRosterType | str,
    *,
    registry_matcher: RegistryMatcher | None = None,
    registry_batch_matcher: RegistryBatchMatcher | None = None,
) -> PreviewResult:
    parsed_type = OrganizationRosterType(roster_type)
    original_by_normalized = {column.normalized: column.original for column in parsed.columns}
    rows: list[PreviewRow] = []
    for source_row in parsed.rows:
        row = PreviewRow(
            row_number=source_row.row_number,
            raw_values=source_row.raw_values,
            disposition=OrganizationRosterRowDisposition.SKIPPED.value,
            validation_errors=list(source_row.parser_issues),
        )
        if source_row.skipped:
            rows.append(row)
            continue
        mapped_values = {
            target: source_row.raw_values.get(original_by_normalized[source])
            for source, target in mapping.mappings.items()
        }
        normalized, issues = normalize_row_values(
            mapped_values,
            row_number=source_row.row_number,
            roster_type=parsed_type,
        )
        row.normalized_values = flatten_normalized_dates(normalized)
        row.validation_errors.extend(issues)
        row.primary_identifier = _primary_identifier(row.normalized_values, parsed_type)
        if mapping.requires_manual_mapping:
            row.validation_errors.append(
                RowIssue(
                    code="mapping_incomplete",
                    field=None,
                    message="Required column mapping is incomplete",
                    row_number=row.row_number,
                )
            )
        row.disposition = (
            OrganizationRosterRowDisposition.INVALID.value
            if row.validation_errors
            else OrganizationRosterRowDisposition.VALID_NEW.value
        )
        rows.append(row)

    _classify_in_file_duplicates(rows, parsed_type)
    if registry_batch_matcher is not None:
        await _classify_registry_matches_batch(rows, registry_batch_matcher)
    elif registry_matcher is not None:
        await _classify_registry_matches(rows, registry_matcher)
    return _result(rows)


def _classify_in_file_duplicates(
    rows: list[PreviewRow], roster_type: OrganizationRosterType
) -> None:
    key_fields = (
        ("employee_id", "work_email")
        if roster_type is OrganizationRosterType.EMPLOYEE
        else ("student_id", "roll_number", "institutional_email")
    )
    occurrences: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        if row.disposition == OrganizationRosterRowDisposition.INVALID.value:
            continue
        for field in key_fields:
            value = row.normalized_values.get(field)
            if value:
                occurrences[(field, str(value))].append(index)

    conflicting_indexes: set[int] = set()
    duplicate_indexes: set[int] = set()
    for indexes in occurrences.values():
        if len(indexes) < 2:
            continue
        first = rows[indexes[0]]
        for index in indexes[1:]:
            candidate = rows[index]
            if _nonblank_conflict(first.normalized_values, candidate.normalized_values):
                conflicting_indexes.update(indexes)
            else:
                duplicate_indexes.add(index)

    for index in sorted(conflicting_indexes):
        row = rows[index]
        row.disposition = OrganizationRosterRowDisposition.INVALID.value
        row.validation_errors.append(
            RowIssue(
                code="conflicting_duplicate",
                field=None,
                message="Repeated identifiers describe conflicting rows",
                row_number=row.row_number,
            )
        )
    for index in sorted(duplicate_indexes.difference(conflicting_indexes)):
        row = rows[index]
        row.disposition = OrganizationRosterRowDisposition.DUPLICATE.value
        row.validation_errors.append(
            RowIssue(
                code="duplicate_row",
                field=None,
                message="A preceding row already uses this identifier",
                row_number=row.row_number,
            )
        )


def _nonblank_conflict(left: dict[str, object], right: dict[str, object]) -> bool:
    shared = set(left).intersection(right)
    return any(left[field] != right[field] for field in shared)


async def _classify_registry_matches(
    rows: list[PreviewRow], registry_matcher: RegistryMatcher
) -> None:
    for row in rows:
        if row.disposition != OrganizationRosterRowDisposition.VALID_NEW.value:
            continue
        match = await registry_matcher(row.normalized_values)
        if match.is_conflict:
            row.disposition = OrganizationRosterRowDisposition.INVALID.value
            row.validation_errors.append(
                RowIssue(
                    code="registry_identity_conflict",
                    field=None,
                    message="Identifiers match different organization people",
                    row_number=row.row_number,
                )
            )
        elif match.person_id is not None:
            row.matched_organization_person_id = match.person_id
            row.disposition = OrganizationRosterRowDisposition.VALID_UPDATE.value


async def _classify_registry_matches_batch(
    rows: list[PreviewRow], registry_batch_matcher: RegistryBatchMatcher
) -> None:
    candidates = [
        row for row in rows if row.disposition == OrganizationRosterRowDisposition.VALID_NEW.value
    ]
    matches = await registry_batch_matcher(tuple(row.normalized_values for row in candidates))
    if len(matches) != len(candidates):
        raise RuntimeError("Registry batch matcher returned an invalid result count")
    for row, match in zip(candidates, matches, strict=True):
        if match.is_conflict:
            row.disposition = OrganizationRosterRowDisposition.INVALID.value
            row.validation_errors.append(
                RowIssue(
                    code="registry_identity_conflict",
                    field=None,
                    message="Identifiers match different organization people",
                    row_number=row.row_number,
                )
            )
        elif match.person_id is not None:
            row.matched_organization_person_id = match.person_id
            row.disposition = OrganizationRosterRowDisposition.VALID_UPDATE.value


def _primary_identifier(
    values: dict[str, object], roster_type: OrganizationRosterType
) -> str | None:
    fields = (
        ("employee_id", "work_email")
        if roster_type is OrganizationRosterType.EMPLOYEE
        else ("student_id", "roll_number", "institutional_email")
    )
    for field in fields:
        value = values.get(field)
        if value:
            return str(value)
    return None


def _result(rows: list[PreviewRow]) -> PreviewResult:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[row.disposition] += 1
    return PreviewResult(
        rows=tuple(rows),
        total_rows=len(rows),
        valid_new_count=counts[OrganizationRosterRowDisposition.VALID_NEW.value],
        valid_update_count=counts[OrganizationRosterRowDisposition.VALID_UPDATE.value],
        duplicate_count=counts[OrganizationRosterRowDisposition.DUPLICATE.value],
        invalid_count=counts[OrganizationRosterRowDisposition.INVALID.value],
        skipped_count=counts[OrganizationRosterRowDisposition.SKIPPED.value],
    )
