"""Organization-scoped roster upload, mapping, and preview orchestration."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.models.organization import Organization
from app.models.organization_roster_import import OrganizationRosterImport
from app.organization_roster_import.constants import PARSER_ERROR_CODES
from app.organization_roster_import.enums import (
    OrganizationRosterImportState,
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
    OrganizationRosterPreviewResponse,
    RosterMappingResponse,
    RosterMappingUpdateRequest,
    RosterPreviewCountsResponse,
    RosterPreviewRowResponse,
    RosterSourceColumnResponse,
)
from app.services.organization_service import OrganizationService


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
            ),
            rows=[
                RosterPreviewRowResponse(
                    row_number=row.original_row_number,
                    raw_values=row.source_values,
                    normalized_values=row.normalized_values,
                    disposition=row.disposition,
                    validation_errors=row.validation_errors,
                    primary_identifier=row.primary_identifier,
                    matched_organization_person_id=row.matched_organization_person_id,
                )
                for row in rows
            ],
            parsed_at=roster_import.parsed_at,
            created_at=roster_import.created_at,
        )
