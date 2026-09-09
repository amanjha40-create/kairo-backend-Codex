"""Persistence and read-only registry matching for roster previews."""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.organization_person import OrganizationPerson
from app.models.organization_person_identifier import OrganizationPersonIdentifier
from app.models.organization_person_roster_profile import OrganizationPersonRosterProfile
from app.models.organization_roster_import import (
    OrganizationRosterImport,
    OrganizationRosterImportAuditEvent,
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
            .options(
                selectinload(OrganizationRosterImport.rows),
                selectinload(OrganizationRosterImport.audit_events),
                selectinload(OrganizationRosterImport.uploaded_by),
            )
            .where(
                OrganizationRosterImport.organization_id == organization_id,
                OrganizationRosterImport.public_id == import_public_id,
            )
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def lock_by_public_id_for_organization(
        self,
        organization_id: UUID,
        import_public_id: UUID,
    ) -> OrganizationRosterImport | None:
        statement = (
            select(OrganizationRosterImport)
            .options(
                selectinload(OrganizationRosterImport.rows),
                selectinload(OrganizationRosterImport.audit_events),
                selectinload(OrganizationRosterImport.uploaded_by),
            )
            .where(
                OrganizationRosterImport.organization_id == organization_id,
                OrganizationRosterImport.public_id == import_public_id,
            )
            .with_for_update()
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def list_imports(
        self,
        organization_id: UUID,
        *,
        offset: int,
        limit: int,
        state: str | None,
        roster_type: str | None,
    ) -> tuple[list[OrganizationRosterImport], int]:
        filters = [OrganizationRosterImport.organization_id == organization_id]
        if state is not None:
            filters.append(OrganizationRosterImport.state == state)
        if roster_type is not None:
            filters.append(OrganizationRosterImport.roster_type == roster_type)
        total = int(
            (
                await self._session.execute(
                    select(func.count()).select_from(OrganizationRosterImport).where(*filters)
                )
            ).scalar_one()
        )
        statement = (
            select(OrganizationRosterImport)
            .options(selectinload(OrganizationRosterImport.uploaded_by))
            .where(*filters)
            .order_by(
                OrganizationRosterImport.created_at.desc(), OrganizationRosterImport.id.desc()
            )
            .offset(offset)
            .limit(limit)
        )
        rows = await self._session.execute(statement)
        return list(rows.scalars().all()), total

    async def list_rows(
        self,
        import_id: UUID,
        *,
        offset: int,
        limit: int,
        disposition: str | None,
        application_status: str | None,
    ) -> tuple[list[OrganizationRosterImportRow], int]:
        filters = [OrganizationRosterImportRow.import_id == import_id]
        if disposition is not None:
            filters.append(OrganizationRosterImportRow.disposition == disposition)
        if application_status is not None:
            filters.append(OrganizationRosterImportRow.application_status == application_status)
        total = int(
            (
                await self._session.execute(
                    select(func.count()).select_from(OrganizationRosterImportRow).where(*filters)
                )
            ).scalar_one()
        )
        statement = (
            select(OrganizationRosterImportRow)
            .where(*filters)
            .order_by(OrganizationRosterImportRow.original_row_number.asc())
            .offset(offset)
            .limit(limit)
        )
        rows = await self._session.execute(statement)
        return list(rows.scalars().all()), total

    async def list_roster_people(
        self,
        organization_id: UUID,
        roster_type: OrganizationRosterType,
        *,
        offset: int,
        limit: int,
        search: str | None,
    ) -> tuple[list[tuple[OrganizationPersonRosterProfile, OrganizationPerson, UUID | None]], int]:
        filters = [
            OrganizationPersonRosterProfile.organization_id == organization_id,
            OrganizationPersonRosterProfile.roster_type == roster_type.value,
            OrganizationPerson.organization_id == organization_id,
        ]
        if search:
            pattern = f"%{search.strip()}%"
            filters.append(
                or_(
                    OrganizationPerson.full_name.ilike(pattern),
                    OrganizationPerson.primary_email.ilike(pattern),
                    OrganizationPersonRosterProfile.employee_id.ilike(pattern),
                    OrganizationPersonRosterProfile.student_id.ilike(pattern),
                    OrganizationPersonRosterProfile.roll_number.ilike(pattern),
                )
            )
        join_condition = (
            OrganizationPerson.id == OrganizationPersonRosterProfile.organization_person_id
        )
        total = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(OrganizationPersonRosterProfile)
                    .join(OrganizationPerson, join_condition)
                    .where(*filters)
                )
            ).scalar_one()
        )
        statement = (
            select(
                OrganizationPersonRosterProfile,
                OrganizationPerson,
                OrganizationRosterImport.public_id,
            )
            .join(OrganizationPerson, join_condition)
            .outerjoin(
                OrganizationRosterImport,
                OrganizationRosterImport.id == OrganizationPersonRosterProfile.source_import_id,
            )
            .where(*filters)
            .order_by(OrganizationPerson.full_name.asc(), OrganizationPerson.id.asc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return list(result.tuples().all()), total

    async def replace_preview_rows(
        self,
        roster_import: OrganizationRosterImport,
        rows: tuple[PreviewRow, ...],
    ) -> None:
        roster_import.rows.clear()
        await self._session.flush()
        roster_import.rows.extend(self._to_model(roster_import.id, row) for row in rows)
        await self._session.flush()

    async def get_person_for_update(
        self,
        organization_id: UUID,
        person_id: UUID,
    ) -> OrganizationPerson | None:
        statement = (
            select(OrganizationPerson)
            .options(
                selectinload(OrganizationPerson.identifiers),
                selectinload(OrganizationPerson.roster_profile),
            )
            .where(
                OrganizationPerson.id == person_id,
                OrganizationPerson.organization_id == organization_id,
            )
            .with_for_update()
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def create_person(self, person: OrganizationPerson) -> OrganizationPerson:
        self._session.add(person)
        await self._session.flush()
        return person

    async def create_profile(
        self, profile: OrganizationPersonRosterProfile
    ) -> OrganizationPersonRosterProfile:
        self._session.add(profile)
        await self._session.flush()
        return profile

    async def find_identifier_owner(
        self,
        organization_id: UUID,
        identifier_type: OrganizationPersonIdentifierType,
        normalized_value: str,
    ) -> UUID | None:
        statement = (
            select(OrganizationPersonIdentifier.organization_person_id)
            .where(
                OrganizationPersonIdentifier.organization_id == organization_id,
                OrganizationPersonIdentifier.identifier_type == identifier_type,
                OrganizationPersonIdentifier.normalized_value == normalized_value,
            )
            .with_for_update()
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def find_primary_owner(
        self,
        organization_id: UUID,
        field: str,
        normalized_value: str,
    ) -> UUID | None:
        column = getattr(OrganizationPerson, field)
        statement = (
            select(OrganizationPerson.id)
            .where(
                OrganizationPerson.organization_id == organization_id,
                column == normalized_value,
            )
            .with_for_update()
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def find_profile_identity_owner(
        self,
        organization_id: UUID,
        field: str,
        normalized_value: str,
    ) -> UUID | None:
        column = getattr(OrganizationPersonRosterProfile, field)
        statement = (
            select(OrganizationPersonRosterProfile.organization_person_id)
            .where(
                OrganizationPersonRosterProfile.organization_id == organization_id,
                column == normalized_value,
            )
            .with_for_update()
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def create_identifier(
        self, identifier: OrganizationPersonIdentifier
    ) -> OrganizationPersonIdentifier:
        self._session.add(identifier)
        await self._session.flush()
        return identifier

    async def append_audit(
        self, event: OrganizationRosterImportAuditEvent
    ) -> OrganizationRosterImportAuditEvent:
        self._session.add(event)
        await self._session.flush()
        return event

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
