"""Organization-scoped roster upload, mapping, and preview orchestration."""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import math
import uuid
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.models.organization import Organization
from app.models.organization_person import OrganizationPerson
from app.models.organization_person_identifier import OrganizationPersonIdentifier
from app.models.organization_person_roster_profile import OrganizationPersonRosterProfile
from app.models.organization_roster_import import OrganizationRosterImport
from app.models.organization_roster_import import (
    OrganizationRosterImportAuditEvent,
    OrganizationRosterImportRow,
)
from app.organization_people.enums import OrganizationPersonIdentifierType
from app.organization_roster_import.application import (
    EMPLOYEE_PROFILE_FIELDS,
    STUDENT_PROFILE_FIELDS,
    RosterRowApplicationError,
    apply_person_values,
    apply_profile_values,
    csv_safe,
    registry_identifiers,
    relationship_for_row,
    roster_identity_fields,
)
from app.organization_roster_import.constants import PARSER_ERROR_CODES
from app.organization_roster_import.enums import (
    OrganizationRosterAuditAction,
    OrganizationRosterImportState,
    OrganizationRosterRowApplicationStatus,
    OrganizationRosterRowDisposition,
    OrganizationRosterType,
)
from app.organization_roster_import.headers import (
    analyze_mapping,
    apply_manual_mapping,
)
from app.organization_roster_import.parsing import parse_roster_file
from app.organization_roster_import.preview import PreviewResult, build_preview
from app.organization_roster_import.storage import (
    RosterSourceStorage,
    S3RosterSourceStorage,
    build_roster_source_key,
)
from app.organization_roster_import.types import (
    MappingAnalysis,
    ParsedRosterFile,
    ParsedSourceRow,
    RowIssue,
    SourceColumn,
)
from app.repositories.organization_roster_import import OrganizationRosterImportRepository
from app.schemas.organization_roster_import import (
    OrganizationRosterListQueryParams,
    OrganizationRosterListResponse,
    OrganizationRosterPersonResponse,
    OrganizationRosterPreviewResponse,
    RosterAuditEventResponse,
    RosterImportListQueryParams,
    RosterImportListResponse,
    RosterImportSummaryResponse,
    RosterMappingResponse,
    RosterMappingUpdateRequest,
    RosterPreviewCountsResponse,
    RosterPreviewRowResponse,
    RosterRowListQueryParams,
    RosterRowListResponse,
    RosterSourceColumnResponse,
    RosterUploaderResponse,
)
from app.services.organization_service import OrganizationService

logger = logging.getLogger(__name__)

_TERMINAL_IMPORT_STATES = {
    OrganizationRosterImportState.COMPLETED.value,
    OrganizationRosterImportState.COMPLETED_WITH_ERRORS.value,
    OrganizationRosterImportState.FAILED.value,
}


class OrganizationRosterImportService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        repository: OrganizationRosterImportRepository | None = None,
        organizations: OrganizationService | None = None,
        storage: RosterSourceStorage | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._repository = repository or OrganizationRosterImportRepository(session)
        self._organizations = organizations or OrganizationService(session)
        self._storage = storage or S3RosterSourceStorage(settings)

    async def upload_preview(
        self,
        *,
        actor_user_id: UUID,
        org_public_id: UUID,
        roster_type: OrganizationRosterType,
        filename: str,
        content_type: str | None,
        content: bytes,
    ) -> OrganizationRosterPreviewResponse:
        organization = await self._require_manager(actor_user_id, org_public_id)
        safe_filename, parsed = await asyncio.to_thread(
            parse_roster_file,
            filename=filename,
            content_type=content_type,
            content=content,
        )
        mapping = analyze_mapping(roster_type, parsed.columns)
        preview = await self._build_preview(organization.id, roster_type, parsed, mapping)
        import_id = uuid.uuid4()
        public_id = uuid.uuid4()
        storage_key = build_roster_source_key(
            settings=self._settings,
            organization_id=organization.id,
            import_public_id=public_id,
            filename=safe_filename,
        )
        effective_mime = content_type or (
            "text/csv"
            if parsed.source_format == "csv"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        storage_attempted = False
        try:
            storage_attempted = True
            await self._storage.put_private(
                object_key=storage_key,
                content=content,
                content_type=effective_mime,
            )
            roster_import = OrganizationRosterImport(
                id=import_id,
                public_id=public_id,
                organization_id=organization.id,
                uploaded_by_user_id=actor_user_id,
                roster_type=roster_type.value,
                source_format=parsed.source_format,
                original_filename=safe_filename,
                source_storage_key=storage_key,
                state=self._state_for(mapping).value,
                source_sheet_name=parsed.sheet_name,
                source_sheet_warning="; ".join(parsed.warnings) or None,
                column_mapping=self._mapping_envelope(parsed, mapping),
                warnings=[*parsed.warnings, *mapping.warnings],
                parsed_at=datetime.now(tz=UTC),
            )
            self._apply_counts(roster_import, preview)
            await self._repository.create(roster_import, preview.rows)
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            if storage_attempted:
                await self._storage.delete_best_effort(object_key=storage_key)
            raise
        persisted = await self._repository.get_by_public_id_for_organization(
            organization.id, public_id
        )
        if persisted is None:
            raise NotFoundError("Roster preview not found")
        return self._to_response(persisted)

    async def authorize_upload(self, *, actor_user_id: UUID, org_public_id: UUID) -> None:
        """Authorize the tenant before the route reads the multipart body."""

        await self._require_manager(actor_user_id, org_public_id)

    async def get_preview(
        self,
        *,
        actor_user_id: UUID,
        org_public_id: UUID,
        import_public_id: UUID,
    ) -> OrganizationRosterPreviewResponse:
        organization = await self._require_manager(actor_user_id, org_public_id)
        roster_import = await self._require_import(organization.id, import_public_id)
        return self._to_response(roster_import)

    async def update_mapping(
        self,
        *,
        actor_user_id: UUID,
        org_public_id: UUID,
        import_public_id: UUID,
        payload: RosterMappingUpdateRequest,
    ) -> OrganizationRosterPreviewResponse:
        organization = await self._require_manager(actor_user_id, org_public_id)
        roster_import = await self._require_import(organization.id, import_public_id)
        if roster_import.state not in {
            OrganizationRosterImportState.MAPPING_REQUIRED.value,
            OrganizationRosterImportState.READY_FOR_REVIEW.value,
        }:
            raise ConflictError("Roster mapping can no longer be changed")

        parsed, current_mapping = self._restore_preview_source(roster_import)
        mapping = apply_manual_mapping(
            OrganizationRosterType(roster_import.roster_type),
            parsed.columns,
            current_mapping,
            ((item.source_column, item.canonical_field) for item in payload.assignments),
        )
        preview = await self._build_preview(
            organization.id,
            OrganizationRosterType(roster_import.roster_type),
            parsed,
            mapping,
        )
        roster_import.column_mapping = self._mapping_envelope(parsed, mapping)
        roster_import.state = self._state_for(mapping).value
        roster_import.warnings = [*parsed.warnings, *mapping.warnings]
        roster_import.parsed_at = datetime.now(tz=UTC)
        self._apply_counts(roster_import, preview)
        await self._repository.replace_preview_rows(roster_import, preview.rows)
        await self._session.commit()
        refreshed = await self._repository.get_by_public_id_for_organization(
            organization.id, import_public_id
        )
        if refreshed is None:
            raise NotFoundError("Roster preview not found")
        return self._to_response(refreshed)

    async def confirm_import(
        self,
        *,
        actor_user_id: UUID,
        org_public_id: UUID,
        import_public_id: UUID,
    ) -> OrganizationRosterPreviewResponse:
        organization = await self._require_manager(actor_user_id, org_public_id)
        organization_id = organization.id
        try:
            roster_import = await self._repository.lock_by_public_id_for_organization(
                organization_id, import_public_id
            )
            if roster_import is None:
                raise NotFoundError("Roster preview not found")
            if roster_import.state in _TERMINAL_IMPORT_STATES:
                response = self._to_response(roster_import)
                await self._session.rollback()
                return response
            if roster_import.state != OrganizationRosterImportState.READY_FOR_REVIEW.value:
                raise ConflictError("Roster import is not ready for confirmation")

            now = datetime.now(tz=UTC)
            roster_import.state = OrganizationRosterImportState.IMPORTING.value
            roster_import.confirmed_at = now
            roster_import.failure_code = None
            roster_import.failure_message = None
            await self._append_audit(
                roster_import,
                actor_user_id=actor_user_id,
                action=OrganizationRosterAuditAction.IMPORT_CONFIRMED,
                dedupe_suffix="confirmed",
                metadata={"state": OrganizationRosterImportState.IMPORTING.value},
            )

            created = 0
            updated = 0
            failed = 0
            for row in sorted(roster_import.rows, key=lambda item: item.original_row_number):
                if row.disposition not in {
                    OrganizationRosterRowDisposition.VALID_NEW.value,
                    OrganizationRosterRowDisposition.VALID_UPDATE.value,
                }:
                    row.application_status = OrganizationRosterRowApplicationStatus.IGNORED.value
                    row.application_errors = []
                    row.applied_at = now
                    continue
                try:
                    async with self._session.begin_nested():
                        person, outcome = await self._apply_row(
                            roster_import,
                            row,
                            actor_user_id=actor_user_id,
                            now=now,
                        )
                        row.result_organization_person_id = person.id
                        row.application_status = outcome.value
                        row.application_errors = []
                        row.applied_at = now
                        action = (
                            OrganizationRosterAuditAction.PERSON_CREATED
                            if outcome is OrganizationRosterRowApplicationStatus.CREATED
                            else OrganizationRosterAuditAction.PERSON_UPDATED
                        )
                        await self._append_audit(
                            roster_import,
                            actor_user_id=actor_user_id,
                            action=action,
                            dedupe_suffix=f"row:{row.id}:{outcome.value}",
                            organization_person_id=person.id,
                            row_id=row.id,
                            metadata={
                                "row_number": row.original_row_number,
                                "outcome": outcome.value,
                            },
                        )
                    if outcome is OrganizationRosterRowApplicationStatus.CREATED:
                        created += 1
                    else:
                        updated += 1
                except RosterRowApplicationError as exc:
                    failed += 1
                    self._mark_row_failed(row, exc.code, exc.message)
                except IntegrityError:
                    failed += 1
                    self._mark_row_failed(
                        row,
                        "identifier_conflict",
                        "An organization identifier is already assigned to another person",
                    )
                except Exception:
                    logger.exception(
                        "organization_roster_row_application_failed",
                        extra={
                            "organization_id": str(organization_id),
                            "import_id": str(roster_import.id),
                            "row_id": str(row.id),
                        },
                    )
                    failed += 1
                    self._mark_row_failed(
                        row,
                        "row_application_failed",
                        "The row could not be applied safely",
                    )

            roster_import.created_count = created
            roster_import.updated_count = updated
            roster_import.failed_count = failed
            roster_import.completed_at = datetime.now(tz=UTC)
            successful = created + updated
            attention_required = any(
                (
                    roster_import.invalid_count,
                    roster_import.duplicate_count,
                    roster_import.skipped_count,
                    failed,
                )
            )
            if successful == 0:
                roster_import.state = OrganizationRosterImportState.FAILED.value
                roster_import.failure_code = "no_rows_applied"
                roster_import.failure_message = "No applicable roster rows were imported"
                terminal_action = OrganizationRosterAuditAction.IMPORT_FAILED
            elif attention_required:
                roster_import.state = OrganizationRosterImportState.COMPLETED_WITH_ERRORS.value
                terminal_action = OrganizationRosterAuditAction.IMPORT_COMPLETED
            else:
                roster_import.state = OrganizationRosterImportState.COMPLETED.value
                terminal_action = OrganizationRosterAuditAction.IMPORT_COMPLETED
            await self._append_audit(
                roster_import,
                actor_user_id=actor_user_id,
                action=terminal_action,
                dedupe_suffix="terminal",
                metadata=self._safe_import_metadata(roster_import),
            )
            await self._session.commit()
        except (ConflictError, NotFoundError):
            await self._session.rollback()
            raise
        except Exception:
            await self._session.rollback()
            await self._record_unexpected_confirmation_failure(
                organization_id=organization_id,
                import_public_id=import_public_id,
                actor_user_id=actor_user_id,
            )
            raise

        refreshed = await self._repository.get_by_public_id_for_organization(
            organization_id, import_public_id
        )
        if refreshed is None:
            raise NotFoundError("Roster import not found after confirmation")
        return self._to_response(refreshed)

    async def list_imports(
        self,
        *,
        actor_user_id: UUID,
        org_public_id: UUID,
        params: RosterImportListQueryParams,
    ) -> RosterImportListResponse:
        organization = await self._require_manager(actor_user_id, org_public_id)
        items, total = await self._repository.list_imports(
            organization.id,
            offset=params.offset or 0,
            limit=params.limit or 20,
            state=params.state.value if params.state else None,
            roster_type=params.roster_type.value if params.roster_type else None,
        )
        return RosterImportListResponse(
            items=[self._to_summary(item) for item in items],
            **self._page_metadata(total, params),
        )

    async def list_import_rows(
        self,
        *,
        actor_user_id: UUID,
        org_public_id: UUID,
        import_public_id: UUID,
        params: RosterRowListQueryParams,
    ) -> RosterRowListResponse:
        organization = await self._require_manager(actor_user_id, org_public_id)
        roster_import = await self._require_import(organization.id, import_public_id)
        rows, total = await self._repository.list_rows(
            roster_import.id,
            offset=params.offset or 0,
            limit=params.limit or 20,
            disposition=params.disposition.value if params.disposition else None,
            application_status=(
                params.application_status.value if params.application_status else None
            ),
        )
        return RosterRowListResponse(
            items=[self._to_row_response(row) for row in rows],
            **self._page_metadata(total, params),
        )

    async def build_error_report(
        self,
        *,
        actor_user_id: UUID,
        org_public_id: UUID,
        import_public_id: UUID,
    ) -> tuple[str, str]:
        organization = await self._require_manager(actor_user_id, org_public_id)
        roster_import = await self._require_import(organization.id, import_public_id)
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(
            ["row_number", "primary_identifier", "disposition", "error_code", "error_message"]
        )
        for row in sorted(roster_import.rows, key=lambda item: item.original_row_number):
            issues = [*(row.validation_errors or []), *(row.application_errors or [])]
            if not issues and row.disposition in {
                OrganizationRosterRowDisposition.VALID_NEW.value,
                OrganizationRosterRowDisposition.VALID_UPDATE.value,
            }:
                continue
            if not issues:
                issues = [
                    {
                        "code": row.disposition,
                        "message": "Row was not eligible for import",
                    }
                ]
            for issue in issues:
                writer.writerow(
                    [
                        row.original_row_number,
                        csv_safe(row.primary_identifier),
                        row.disposition,
                        csv_safe(issue.get("code")),
                        csv_safe(issue.get("message")),
                    ]
                )
        filename = f"roster-import-{roster_import.public_id}-errors.csv"
        return filename, output.getvalue()

    async def list_roster(
        self,
        *,
        actor_user_id: UUID,
        org_public_id: UUID,
        roster_type: OrganizationRosterType,
        params: OrganizationRosterListQueryParams,
    ) -> OrganizationRosterListResponse:
        organization = await self._require_manager(actor_user_id, org_public_id)
        rows, total = await self._repository.list_roster_people(
            organization.id,
            roster_type,
            offset=params.offset or 0,
            limit=params.limit or 20,
            search=params.search,
        )
        items = [
            self._to_roster_person(profile, person, source_import_public_id)
            for profile, person, source_import_public_id in rows
        ]
        return OrganizationRosterListResponse(
            items=items,
            **self._page_metadata(total, params),
        )

    async def _require_manager(self, actor_user_id: UUID, org_public_id: UUID) -> Organization:
        organization, membership = await self._organizations.require_org_manager(
            actor_user_id, org_public_id
        )
        if membership.suspended_at is not None or organization.suspended_at is not None:
            raise ForbiddenError("Organization roster access is suspended")
        return organization

    async def _require_import(
        self, organization_id: UUID, import_public_id: UUID
    ) -> OrganizationRosterImport:
        roster_import = await self._repository.get_by_public_id_for_organization(
            organization_id, import_public_id
        )
        if roster_import is None:
            raise NotFoundError("Roster preview not found")
        return roster_import

    async def _build_preview(
        self,
        organization_id: UUID,
        roster_type: OrganizationRosterType,
        parsed: ParsedRosterFile,
        mapping: MappingAnalysis,
    ) -> PreviewResult:
        async def registry_batch_matcher(values: tuple[dict[str, object], ...]):
            return await self._repository.match_registry_batch(organization_id, roster_type, values)

        return await build_preview(
            parsed,
            mapping,
            roster_type,
            registry_batch_matcher=registry_batch_matcher,
        )

    async def _apply_row(
        self,
        roster_import: OrganizationRosterImport,
        row: OrganizationRosterImportRow,
        *,
        actor_user_id: UUID,
        now: datetime,
    ) -> tuple[OrganizationPerson, OrganizationRosterRowApplicationStatus]:
        roster_type = OrganizationRosterType(roster_import.roster_type)
        values = dict(row.normalized_values or {})
        identity_fields = roster_identity_fields(roster_type, values)
        registry_aliases = registry_identifiers(roster_type, values)
        if not identity_fields and not registry_aliases:
            raise RosterRowApplicationError(
                "identifier_required",
                "At least one supported organization identifier is required",
            )
        current_match = await self._repository.match_registry(
            roster_import.organization_id, roster_type, values
        )
        if current_match.is_conflict:
            raise RosterRowApplicationError(
                "identifier_conflict",
                "Identifiers resolve to different organization people",
            )

        if row.disposition == OrganizationRosterRowDisposition.VALID_NEW.value:
            if current_match.person_id is not None:
                raise RosterRowApplicationError(
                    "identifier_conflict",
                    "A matching organization person was created after preview",
                )
            await self._ensure_identifiers_available(
                roster_import.organization_id,
                roster_type,
                values,
                person_id=None,
            )
            person = OrganizationPerson(
                organization_id=roster_import.organization_id,
                full_name=str(values["full_name"]),
                primary_email=self._email_value(roster_type, values),
                primary_phone=str(values["phone"]) if values.get("phone") else None,
                relationship=relationship_for_row(roster_type, values),
                added_by_user_id=actor_user_id,
                added_at=now,
                last_activity_at=now,
                resolution_state="unresolved",
                resolution_method="organization_import",
                resolution_metadata={"source_import_id": str(roster_import.public_id)},
            )
            await self._repository.create_person(person)
            outcome = OrganizationRosterRowApplicationStatus.CREATED
        else:
            expected_person_id = row.matched_organization_person_id
            if expected_person_id is None:
                raise RosterRowApplicationError(
                    "matched_person_missing",
                    "The previewed organization person is unavailable",
                )
            person = await self._repository.get_person_for_update(
                roster_import.organization_id, expected_person_id
            )
            if person is None:
                raise RosterRowApplicationError(
                    "matched_person_missing",
                    "The previewed organization person is unavailable",
                )
            if current_match.person_id != expected_person_id:
                raise RosterRowApplicationError(
                    "matched_person_changed",
                    "Identifiers no longer resolve to the previewed organization person",
                )
            await self._ensure_identifiers_available(
                roster_import.organization_id,
                roster_type,
                values,
                person_id=person.id,
            )
            apply_person_values(person, values, roster_type=roster_type)
            person.last_activity_at = now
            outcome = OrganizationRosterRowApplicationStatus.UPDATED

        profile = (
            None
            if outcome is OrganizationRosterRowApplicationStatus.CREATED
            else person.roster_profile
        )
        if profile is not None and profile.roster_type != roster_type.value:
            raise RosterRowApplicationError(
                "roster_type_conflict",
                "The organization person already belongs to another roster type",
            )
        if profile is None:
            profile = OrganizationPersonRosterProfile(
                organization_id=roster_import.organization_id,
                organization_person_id=person.id,
                roster_type=roster_type.value,
                source="organization_import",
                source_import_id=roster_import.id,
                source_row_number=row.original_row_number,
                imported_by_user_id=actor_user_id,
                imported_at=now,
            )
            await self._repository.create_profile(profile)
        apply_profile_values(profile, values, roster_type=roster_type)
        profile.source = "organization_import"
        profile.source_import_id = roster_import.id
        profile.source_row_number = row.original_row_number
        profile.imported_by_user_id = actor_user_id
        profile.imported_at = now
        await self._ensure_registry_identifiers(
            roster_import.organization_id,
            person,
            roster_type,
            values,
            existing_identifiers=(
                tuple(person.identifiers)
                if outcome is OrganizationRosterRowApplicationStatus.UPDATED
                else ()
            ),
        )
        await self._session.flush()
        return person, outcome

    async def _ensure_identifiers_available(
        self,
        organization_id: UUID,
        roster_type: OrganizationRosterType,
        values: dict[str, Any],
        *,
        person_id: UUID | None,
    ) -> None:
        for field, value in roster_identity_fields(roster_type, values):
            owner = await self._repository.find_profile_identity_owner(
                organization_id, field, value
            )
            self._reject_other_owner(owner, person_id)
        for identifier_type, value in registry_identifiers(roster_type, values):
            owner = await self._repository.find_identifier_owner(
                organization_id, identifier_type, value
            )
            self._reject_other_owner(owner, person_id)
            primary_field = (
                "primary_email"
                if identifier_type is OrganizationPersonIdentifierType.EMAIL
                else "primary_phone"
            )
            primary_owner = await self._repository.find_primary_owner(
                organization_id, primary_field, value
            )
            self._reject_other_owner(primary_owner, person_id)

    async def _ensure_registry_identifiers(
        self,
        organization_id: UUID,
        person: OrganizationPerson,
        roster_type: OrganizationRosterType,
        values: dict[str, Any],
        existing_identifiers: tuple[OrganizationPersonIdentifier, ...],
    ) -> None:
        for identifier_type, value in registry_identifiers(roster_type, values):
            same_type = [
                identifier
                for identifier in existing_identifiers
                if str(identifier.identifier_type) == identifier_type.value
            ]
            for identifier in same_type:
                identifier.is_primary = identifier.normalized_value == value
            owner = await self._repository.find_identifier_owner(
                organization_id, identifier_type, value
            )
            self._reject_other_owner(owner, person.id)
            if owner is None:
                await self._repository.create_identifier(
                    OrganizationPersonIdentifier(
                        organization_person_id=person.id,
                        organization_id=organization_id,
                        identifier_type=identifier_type,
                        normalized_value=value,
                        raw_value=value,
                        is_primary=True,
                    )
                )
            else:
                for identifier in same_type:
                    if identifier.normalized_value == value:
                        identifier.is_primary = True

    async def _append_audit(
        self,
        roster_import: OrganizationRosterImport,
        *,
        actor_user_id: UUID,
        action: OrganizationRosterAuditAction,
        dedupe_suffix: str,
        metadata: dict[str, Any],
        organization_person_id: UUID | None = None,
        row_id: UUID | None = None,
    ) -> None:
        event = OrganizationRosterImportAuditEvent(
            roster_import=roster_import,
            organization_id=roster_import.organization_id,
            actor_user_id=actor_user_id,
            organization_person_id=organization_person_id,
            row_id=row_id,
            action=action.value,
            dedupe_key=f"roster:{roster_import.id}:{dedupe_suffix}",
            metadata_payload={
                "import_id": str(roster_import.public_id),
                "organization_id": str(roster_import.organization_id),
                "roster_type": roster_import.roster_type,
                **metadata,
            },
        )
        await self._repository.append_audit(event)

    async def _record_unexpected_confirmation_failure(
        self,
        *,
        organization_id: UUID,
        import_public_id: UUID,
        actor_user_id: UUID,
    ) -> None:
        try:
            roster_import = await self._repository.lock_by_public_id_for_organization(
                organization_id, import_public_id
            )
            if roster_import is None or roster_import.state in _TERMINAL_IMPORT_STATES:
                await self._session.rollback()
                return
            roster_import.state = OrganizationRosterImportState.FAILED.value
            roster_import.failure_code = "confirmation_failed"
            roster_import.failure_message = "Roster confirmation could not be completed safely"
            roster_import.completed_at = datetime.now(tz=UTC)
            await self._append_audit(
                roster_import,
                actor_user_id=actor_user_id,
                action=OrganizationRosterAuditAction.IMPORT_FAILED,
                dedupe_suffix="terminal",
                metadata=self._safe_import_metadata(roster_import),
            )
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            logger.exception(
                "organization_roster_confirmation_failure_state_not_persisted",
                extra={
                    "organization_id": str(organization_id),
                    "import_public_id": str(import_public_id),
                },
            )

    @staticmethod
    def _reject_other_owner(owner: UUID | None, person_id: UUID | None) -> None:
        if owner is not None and owner != person_id:
            raise RosterRowApplicationError(
                "identifier_conflict",
                "An organization identifier is already assigned to another person",
            )

    @staticmethod
    def _email_value(roster_type: OrganizationRosterType, values: dict[str, Any]) -> str | None:
        field = (
            "work_email"
            if roster_type is OrganizationRosterType.EMPLOYEE
            else "institutional_email"
        )
        return str(values[field]) if values.get(field) else None

    @staticmethod
    def _mark_row_failed(
        row: OrganizationRosterImportRow,
        code: str,
        message: str,
    ) -> None:
        row.result_organization_person_id = None
        row.application_status = OrganizationRosterRowApplicationStatus.FAILED.value
        row.application_errors = [
            {
                "code": code,
                "field": None,
                "message": message,
                "row_number": row.original_row_number,
            }
        ]
        row.applied_at = datetime.now(tz=UTC)

    @staticmethod
    def _safe_import_metadata(roster_import: OrganizationRosterImport) -> dict[str, Any]:
        return {
            "state": roster_import.state,
            "counts": {
                "created": roster_import.created_count,
                "updated": roster_import.updated_count,
                "failed": roster_import.failed_count,
                "invalid": roster_import.invalid_count,
                "duplicate": roster_import.duplicate_count,
                "skipped": roster_import.skipped_count,
            },
        }

    @staticmethod
    def _page_metadata(total: int, params: Any) -> dict[str, int]:
        page_size = params.page_size or 20
        return {
            "total": total,
            "page": params.page or 1,
            "page_size": page_size,
            "total_pages": math.ceil(total / page_size) if total else 0,
            "offset": params.offset or 0,
            "limit": params.limit or page_size,
        }

    @staticmethod
    def _state_for(mapping: MappingAnalysis) -> OrganizationRosterImportState:
        if mapping.requires_manual_mapping:
            return OrganizationRosterImportState.MAPPING_REQUIRED
        return OrganizationRosterImportState.READY_FOR_REVIEW

    @staticmethod
    def _mapping_envelope(parsed: ParsedRosterFile, mapping: MappingAnalysis) -> dict[str, Any]:
        return {
            "version": 1,
            "source_columns": [
                {"original": column.original, "normalized": column.normalized}
                for column in parsed.columns
            ],
            "mappings": dict(mapping.mappings),
            "unmapped_source_columns": list(mapping.unmapped_source_columns),
            "missing_required_mappings": list(mapping.missing_required_mappings),
            "ambiguous_mappings": list(mapping.ambiguous_mappings),
            "warnings": list(mapping.warnings),
            "source_warnings": list(parsed.warnings),
        }

    @staticmethod
    def _restore_preview_source(
        roster_import: OrganizationRosterImport,
    ) -> tuple[ParsedRosterFile, dict[str, str]]:
        envelope = roster_import.column_mapping or {}
        columns = tuple(
            SourceColumn(original=item["original"], normalized=item["normalized"])
            for item in envelope.get("source_columns", [])
        )
        if not columns:
            raise ConflictError("Roster source mapping metadata is unavailable")
        rows = []
        for stored in sorted(roster_import.rows, key=lambda item: item.original_row_number):
            parser_issues = tuple(
                RowIssue(
                    code=issue["code"],
                    field=issue.get("field"),
                    message=issue["message"],
                    row_number=stored.original_row_number,
                )
                for issue in stored.validation_errors
                if issue.get("code") in PARSER_ERROR_CODES
            )
            rows.append(
                ParsedSourceRow(
                    row_number=stored.original_row_number,
                    raw_values=stored.source_values,
                    parser_issues=parser_issues,
                    skipped=stored.disposition == "skipped",
                )
            )
        parsed = ParsedRosterFile(
            source_format=roster_import.source_format,
            columns=columns,
            rows=tuple(rows),
            sheet_name=roster_import.source_sheet_name,
            warnings=tuple(envelope.get("source_warnings", [])),
        )
        return parsed, dict(envelope.get("mappings", {}))

    @staticmethod
    def _apply_counts(roster_import: OrganizationRosterImport, preview: PreviewResult) -> None:
        roster_import.total_rows = preview.total_rows
        roster_import.valid_new_count = preview.valid_new_count
        roster_import.valid_update_count = preview.valid_update_count
        roster_import.duplicate_count = preview.duplicate_count
        roster_import.invalid_count = preview.invalid_count
        roster_import.skipped_count = preview.skipped_count
        roster_import.created_count = 0
        roster_import.updated_count = 0
        roster_import.failed_count = 0

    @staticmethod
    def _to_row_response(row: OrganizationRosterImportRow) -> RosterPreviewRowResponse:
        return RosterPreviewRowResponse(
            row_number=row.original_row_number,
            raw_values=row.source_values,
            normalized_values=row.normalized_values,
            disposition=row.disposition,
            validation_errors=row.validation_errors or [],
            primary_identifier=row.primary_identifier,
            matched_organization_person_id=row.matched_organization_person_id,
            result_organization_person_id=row.result_organization_person_id,
            application_status=(
                row.application_status or OrganizationRosterRowApplicationStatus.PENDING.value
            ),
            application_errors=row.application_errors or [],
            applied_at=row.applied_at,
        )

    @staticmethod
    def _to_uploader(roster_import: OrganizationRosterImport) -> RosterUploaderResponse | None:
        uploader = roster_import.__dict__.get("uploaded_by")
        if uploader is None:
            return None
        return RosterUploaderResponse(
            user_id=uploader.id,
            display_name=uploader.full_name or uploader.email,
            email=uploader.email,
        )

    @classmethod
    def _to_summary(cls, roster_import: OrganizationRosterImport) -> RosterImportSummaryResponse:
        uploader = cls._to_uploader(roster_import)
        if uploader is None:
            raise RuntimeError("Roster import uploader was not loaded")
        return RosterImportSummaryResponse(
            import_id=roster_import.public_id,
            roster_type=OrganizationRosterType(roster_import.roster_type),
            source_format=roster_import.source_format,
            original_filename=roster_import.original_filename,
            state=OrganizationRosterImportState(roster_import.state),
            counts=RosterPreviewCountsResponse(
                total_rows=roster_import.total_rows,
                valid_new=roster_import.valid_new_count,
                valid_update=roster_import.valid_update_count,
                duplicate=roster_import.duplicate_count,
                invalid=roster_import.invalid_count,
                skipped=roster_import.skipped_count,
                created=roster_import.created_count,
                updated=roster_import.updated_count,
                failed=roster_import.failed_count,
            ),
            uploader=uploader,
            parsed_at=roster_import.parsed_at,
            confirmed_at=roster_import.confirmed_at,
            completed_at=roster_import.completed_at,
            created_at=roster_import.created_at,
        )

    @staticmethod
    def _to_roster_person(
        profile: OrganizationPersonRosterProfile,
        person: OrganizationPerson,
        source_import_public_id: UUID | None,
    ) -> OrganizationRosterPersonResponse:
        roster_type = OrganizationRosterType(profile.roster_type)
        fields = (
            EMPLOYEE_PROFILE_FIELDS
            if roster_type is OrganizationRosterType.EMPLOYEE
            else STUDENT_PROFILE_FIELDS
        )
        roster_data: dict[str, Any] = {}
        for field in sorted(fields):
            value = getattr(profile, field)
            if value is not None:
                roster_data[field] = value.isoformat() if isinstance(value, date) else value
        return OrganizationRosterPersonResponse(
            organization_person_id=person.public_id,
            roster_type=roster_type,
            full_name=person.full_name,
            email=person.primary_email,
            phone=person.primary_phone,
            roster_data=roster_data,
            source_import_id=source_import_public_id,
            source_row_number=profile.source_row_number,
            imported_by_user_id=profile.imported_by_user_id,
            imported_at=profile.imported_at,
        )

    @staticmethod
    def _to_response(
        roster_import: OrganizationRosterImport,
    ) -> OrganizationRosterPreviewResponse:
        envelope = roster_import.column_mapping or {}
        rows = sorted(roster_import.rows, key=lambda item: item.original_row_number)
        return OrganizationRosterPreviewResponse(
            import_id=roster_import.public_id,
            roster_type=OrganizationRosterType(roster_import.roster_type),
            source_format=roster_import.source_format,
            original_filename=roster_import.original_filename,
            state=OrganizationRosterImportState(roster_import.state),
            selected_sheet_name=roster_import.source_sheet_name,
            selected_sheet_warning=roster_import.source_sheet_warning,
            mapping=RosterMappingResponse(
                source_columns=[
                    RosterSourceColumnResponse(**item)
                    for item in envelope.get("source_columns", [])
                ],
                mappings=envelope.get("mappings", {}),
                unmapped_source_columns=envelope.get("unmapped_source_columns", []),
                missing_required_mappings=envelope.get("missing_required_mappings", []),
                ambiguous_mappings=envelope.get("ambiguous_mappings", []),
                warnings=envelope.get("warnings", []),
            ),
            counts=RosterPreviewCountsResponse(
                total_rows=roster_import.total_rows,
                valid_new=roster_import.valid_new_count,
                valid_update=roster_import.valid_update_count,
                duplicate=roster_import.duplicate_count,
                invalid=roster_import.invalid_count,
                skipped=roster_import.skipped_count,
                created=roster_import.created_count,
                updated=roster_import.updated_count,
                failed=roster_import.failed_count,
            ),
            rows=[OrganizationRosterImportService._to_row_response(row) for row in rows],
            uploader=OrganizationRosterImportService._to_uploader(roster_import),
            audit_events=[
                RosterAuditEventResponse(
                    event_id=event.public_id,
                    action=event.action,
                    organization_person_id=event.organization_person_id,
                    row_id=event.row_id,
                    metadata=event.metadata_payload,
                    created_at=event.created_at,
                )
                for event in roster_import.__dict__.get("audit_events", [])
            ],
            confirmed_at=roster_import.confirmed_at,
            completed_at=roster_import.completed_at,
            failure_code=roster_import.failure_code,
            failure_message=roster_import.failure_message,
            parsed_at=roster_import.parsed_at,
            created_at=roster_import.created_at,
        )
