"""Persistence and read-only registry matching for roster previews."""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.organization_person import OrganizationPerson
from app.models.organization_person_identifier import OrganizationPersonIdentifier
from app.models.organization_person_roster_profile import OrganizationPersonRosterProfile
from app.models.organization_roster_import import (
    OrganizationRosterImport,
    OrganizationRosterImportRow,
)
from app.organization_people.enums import OrganizationPersonIdentifierType
from app.organization_roster_import.enums import OrganizationRosterType
from app.organization_roster_import.types import PreviewRow, RegistryMatch


class OrganizationRosterImportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        roster_import: OrganizationRosterImport,
        rows: tuple[PreviewRow, ...],
    ) -> OrganizationRosterImport:
        roster_import.rows = [self._to_model(roster_import.id, row) for row in rows]
        self._session.add(roster_import)
        await self._session.flush()
        return roster_import

    async def get_by_public_id_for_organization(
        self,
        organization_id: UUID,
        import_public_id: UUID,
    ) -> OrganizationRosterImport | None:
        statement = (
            select(OrganizationRosterImport)
            .options(selectinload(OrganizationRosterImport.rows))
            .where(
                OrganizationRosterImport.organization_id == organization_id,
                OrganizationRosterImport.public_id == import_public_id,
            )
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def replace_preview_rows(
        self,
        roster_import: OrganizationRosterImport,
        rows: tuple[PreviewRow, ...],
    ) -> None:
        roster_import.rows.clear()
        await self._session.flush()
        roster_import.rows.extend(self._to_model(roster_import.id, row) for row in rows)
        await self._session.flush()

    async def match_registry(
        self,
        organization_id: UUID,
        roster_type: OrganizationRosterType,
        values: dict[str, object],
    ) -> RegistryMatch:
        return (await self.match_registry_batch(organization_id, roster_type, (values,)))[0]

    async def match_registry_batch(
        self,
        organization_id: UUID,
        roster_type: OrganizationRosterType,
        rows: tuple[dict[str, object], ...],
    ) -> tuple[RegistryMatch, ...]:
        lookups: dict[str, dict[str, set[UUID]]] = defaultdict(lambda: defaultdict(set))
        profile_fields = (
            ("employee_id",)
            if roster_type is OrganizationRosterType.EMPLOYEE
            else ("student_id", "roll_number")
        )
        for field in profile_fields:
            values = {str(row[field]) for row in rows if row.get(field)}
            if values:
                lookups[field] = await self._profile_match_map(organization_id, field, values)

        email_field = (
            "work_email"
            if roster_type is OrganizationRosterType.EMPLOYEE
            else "institutional_email"
        )
        emails = {str(row[email_field]) for row in rows if row.get(email_field)}
        if emails:
            identifier_matches = await self._identifier_match_map(
                organization_id,
                OrganizationPersonIdentifierType.EMAIL,
                emails,
            )
            primary_matches = await self._person_primary_match_map(
                organization_id, "primary_email", emails
            )
            lookups[email_field] = _merge_match_maps(identifier_matches, primary_matches)

        phones = {str(row["phone"]) for row in rows if row.get("phone")}
        if phones:
            identifier_matches = await self._identifier_match_map(
                organization_id,
                OrganizationPersonIdentifierType.PHONE,
                phones,
            )
            primary_matches = await self._person_primary_match_map(
                organization_id, "primary_phone", phones
            )
            lookups["phone"] = _merge_match_maps(identifier_matches, primary_matches)

        return tuple(self._resolve_registry_match(row, lookups) for row in rows)

    async def _profile_match_map(
        self, organization_id: UUID, field: str, values: set[str]
    ) -> dict[str, set[UUID]]:
        column = getattr(OrganizationPersonRosterProfile, field)
        statement = select(column, OrganizationPersonRosterProfile.organization_person_id).where(
            OrganizationPersonRosterProfile.organization_id == organization_id,
            column.in_(values),
        )
        result: dict[str, set[UUID]] = defaultdict(set)
        for value, person_id in (await self._session.execute(statement)).all():
            result[str(value)].add(person_id)
        return result

    async def _identifier_match_map(
        self,
        organization_id: UUID,
        identifier_type: OrganizationPersonIdentifierType,
        values: set[str],
    ) -> dict[str, set[UUID]]:
        statement = select(
            OrganizationPersonIdentifier.normalized_value,
            OrganizationPersonIdentifier.organization_person_id,
        ).where(
            OrganizationPersonIdentifier.organization_id == organization_id,
            OrganizationPersonIdentifier.identifier_type == identifier_type,
            OrganizationPersonIdentifier.normalized_value.in_(values),
        )
        result: dict[str, set[UUID]] = defaultdict(set)
        for value, person_id in (await self._session.execute(statement)).all():
            result[value].add(person_id)
        return result

    async def _person_primary_match_map(
        self, organization_id: UUID, field: str, values: set[str]
    ) -> dict[str, set[UUID]]:
        column = getattr(OrganizationPerson, field)
        statement = select(column, OrganizationPerson.id).where(
            OrganizationPerson.organization_id == organization_id,
            column.in_(values),
        )
        result: dict[str, set[UUID]] = defaultdict(set)
        for value, person_id in (await self._session.execute(statement)).all():
            result[str(value)].add(person_id)
        return result

    @staticmethod
    def _resolve_registry_match(
        values: dict[str, object],
        lookups: dict[str, dict[str, set[UUID]]],
    ) -> RegistryMatch:
        matches: dict[str, set[UUID]] = defaultdict(set)
        for field, value_lookup in lookups.items():
            value = values.get(field)
            if value:
                matches[field].update(value_lookup.get(str(value), set()))
        all_people = set().union(*matches.values()) if matches else set()
        conflicting_fields = tuple(
            sorted(field for field, person_ids in matches.items() if len(person_ids) > 1)
        )
        if len(all_people) > 1:
            conflicting_fields = tuple(sorted(matches))
        if conflicting_fields:
            return RegistryMatch(conflicting_fields=conflicting_fields)
        return RegistryMatch(person_id=next(iter(all_people), None))

    @staticmethod
    def _to_model(import_id: UUID, row: PreviewRow) -> OrganizationRosterImportRow:
        return OrganizationRosterImportRow(
            import_id=import_id,
            original_row_number=row.row_number,
            source_values=row.raw_values,
            normalized_values=row.normalized_values,
            disposition=row.disposition,
            validation_errors=[issue.as_dict() for issue in row.validation_errors],
            primary_identifier=row.primary_identifier,
            matched_organization_person_id=row.matched_organization_person_id,
            result_organization_person_id=None,
        )


def _merge_match_maps(*match_maps: dict[str, set[UUID]]) -> dict[str, set[UUID]]:
    merged: dict[str, set[UUID]] = defaultdict(set)
    for match_map in match_maps:
        for value, person_ids in match_map.items():
            merged[value].update(person_ids)
    return merged
