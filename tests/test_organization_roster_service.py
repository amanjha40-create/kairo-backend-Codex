"""Service transaction and read-only registry tests for roster M2."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.config import Settings
from app.models.organization import Organization
from app.models.organization_roster_import import (
    OrganizationRosterImport,
    OrganizationRosterImportRow,
)
from app.organization_roster_import.enums import OrganizationRosterType
from app.organization_roster_import.storage import S3RosterSourceStorage
from app.organization_roster_import.types import PreviewRow, RegistryMatch
from app.repositories.organization_roster_import import OrganizationRosterImportRepository
from app.schemas.organization_roster_import import (
    RosterMappingAssignment,
    RosterMappingUpdateRequest,
)
from app.services.organization_roster_import_service import OrganizationRosterImportService


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class FakeStorage:
    def __init__(self, *, fail_put: bool = False) -> None:
        self.puts: list[tuple[str, str, bytes]] = []
        self.deletes: list[str] = []
        self.fail_put = fail_put

    async def put_private(self, *, object_key: str, content: bytes, content_type: str) -> None:
        self.puts.append((object_key, content_type, content))
        if self.fail_put:
            raise RuntimeError("storage failure")

    async def delete_best_effort(self, *, object_key: str) -> None:
        self.deletes.append(object_key)


class FakeOrganizations:
    def __init__(self, organization: Organization) -> None:
        self.organization = organization

    async def require_org_manager(self, actor_user_id: UUID, org_public_id: UUID):  # noqa: ANN202
        assert actor_user_id
        assert org_public_id == self.organization.public_id
        return self.organization, SimpleNamespace(suspended_at=None)


class FakeRepository:
    def __init__(self, *, fail_create: bool = False) -> None:
        self.roster_import: OrganizationRosterImport | None = None
        self.fail_create = fail_create
        self.registry_matches: dict[str, UUID] = {}

    async def create(
        self, roster_import: OrganizationRosterImport, rows: tuple[PreviewRow, ...]
    ) -> OrganizationRosterImport:
        if self.fail_create:
            raise RuntimeError("database failure")
        self.roster_import = roster_import
        roster_import.created_at = datetime.now(tz=UTC)
        roster_import.updated_at = roster_import.created_at
        roster_import.rows = [self._row(roster_import.id, row) for row in rows]
        return roster_import

    async def get_by_public_id_for_organization(
        self, organization_id: UUID, import_public_id: UUID
    ) -> OrganizationRosterImport | None:
        if (
            self.roster_import is not None
            and self.roster_import.organization_id == organization_id
            and self.roster_import.public_id == import_public_id
        ):
            return self.roster_import
        return None

    async def replace_preview_rows(
        self, roster_import: OrganizationRosterImport, rows: tuple[PreviewRow, ...]
    ) -> None:
        roster_import.rows = [self._row(roster_import.id, row) for row in rows]

    async def match_registry(
        self,
        organization_id: UUID,
        roster_type: OrganizationRosterType,
        values: dict[str, object],
    ) -> RegistryMatch:
        del organization_id, roster_type
        identifier = str(values.get("employee_id") or values.get("student_id") or "")
        return RegistryMatch(person_id=self.registry_matches.get(identifier))

    async def match_registry_batch(
        self,
        organization_id: UUID,
        roster_type: OrganizationRosterType,
        rows: tuple[dict[str, object], ...],
    ) -> tuple[RegistryMatch, ...]:
        return tuple([await self.match_registry(organization_id, roster_type, row) for row in rows])

    @staticmethod
    def _row(import_id: UUID, row: PreviewRow) -> OrganizationRosterImportRow:
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


def _service(*, repository: FakeRepository | None = None):  # noqa: ANN202
    session = FakeSession()
    storage = FakeStorage()
    organization = Organization(
        id=uuid4(),
        public_id=uuid4(),
        created_by_user_id=uuid4(),
        name="Roster QA",
        organization_type="employer",
    )
    settings = Settings(
        database_url="postgresql+asyncpg://kairo:kairo@localhost:5432/kairo",
        jwt_secret_key="test-jwt-secret-key-32-chars-minimum!!",
        s3_documents_bucket="private-test-bucket",
        s3_document_key_prefix="private",
    )
    repo = repository or FakeRepository()
    service = OrganizationRosterImportService(
        session,  # type: ignore[arg-type]
        settings,
        repository=repo,  # type: ignore[arg-type]
        organizations=FakeOrganizations(organization),  # type: ignore[arg-type]
        storage=storage,
    )
    return service, session, storage, repo, organization


async def test_upload_persists_private_preview_without_people_mutation() -> None:
    service, session, storage, repository, organization = _service()
    response = await service.upload_preview(
        actor_user_id=uuid4(),
        org_public_id=organization.public_id,
        roster_type=OrganizationRosterType.EMPLOYEE,
        filename="employees.csv",
        content_type="text/csv",
        content=b"Employee ID,Full Name,Work Email\n001,Test Person,test@example.com\n",
    )
    assert response.state.value == "ready_for_review"
    assert response.counts.valid_new == 1
    assert response.counts.created == response.counts.updated == 0
    assert session.commits == 1
    assert len(storage.puts) == 1
    assert f"organizations/{organization.id}/imports/{response.import_id}" in storage.puts[0][0]
    assert repository.roster_import is not None
    assert repository.roster_import.rows[0].result_organization_person_id is None


async def test_manual_mapping_reprocesses_rows_without_stale_results() -> None:
    service, session, _, repository, organization = _service()
    uploaded = await service.upload_preview(
        actor_user_id=uuid4(),
        org_public_id=organization.public_id,
        roster_type=OrganizationRosterType.EMPLOYEE,
        filename="employees.csv",
        content_type="text/csv",
        content=b"Staff Number,Person\n001,Test Person\n",
    )
    assert uploaded.state.value == "mapping_required"
    assert uploaded.counts.invalid == 1
    updated = await service.update_mapping(
        actor_user_id=uuid4(),
        org_public_id=organization.public_id,
        import_public_id=uploaded.import_id,
        payload=RosterMappingUpdateRequest(
            assignments=[
                RosterMappingAssignment(
                    source_column="Staff Number", canonical_field="employee_id"
                ),
                RosterMappingAssignment(source_column="Person", canonical_field="full_name"),
            ]
        ),
    )
    assert updated.state.value == "ready_for_review"
    assert updated.counts.valid_new == 1
    assert len(updated.rows) == 1
    assert updated.rows[0].validation_errors == []
    assert repository.roster_import is not None
    assert len(repository.roster_import.rows) == 1
    assert session.commits == 2


async def test_registry_match_only_sets_preview_match_reference() -> None:
    repository = FakeRepository()
    matched_id = uuid4()
    repository.registry_matches["001"] = matched_id
    service, _, _, _, organization = _service(repository=repository)
    response = await service.upload_preview(
        actor_user_id=uuid4(),
        org_public_id=organization.public_id,
        roster_type=OrganizationRosterType.EMPLOYEE,
        filename="employees.csv",
        content_type="text/csv",
        content=b"Employee ID,Full Name\n001,Existing Person\n",
    )
    assert response.counts.valid_update == 1
    assert response.rows[0].matched_organization_person_id == matched_id
    assert repository.roster_import is not None
    assert repository.roster_import.rows[0].result_organization_person_id is None


async def test_database_failure_rolls_back_and_removes_private_object() -> None:
    service, session, storage, _, organization = _service(
        repository=FakeRepository(fail_create=True)
    )
    with pytest.raises(RuntimeError, match="database failure"):
        await service.upload_preview(
            actor_user_id=uuid4(),
            org_public_id=organization.public_id,
            roster_type=OrganizationRosterType.EMPLOYEE,
            filename="employees.csv",
            content_type="text/csv",
            content=b"Employee ID,Full Name\n001,Test Person\n",
        )
    assert session.rollbacks == 1
    assert storage.deletes == [storage.puts[0][0]]


async def test_uncertain_storage_failure_also_attempts_cleanup() -> None:
    service, session, _, repository, organization = _service()
    storage = FakeStorage(fail_put=True)
    service._storage = storage
    with pytest.raises(RuntimeError, match="storage failure"):
        await service.upload_preview(
            actor_user_id=uuid4(),
            org_public_id=organization.public_id,
            roster_type=OrganizationRosterType.EMPLOYEE,
            filename="employees.csv",
            content_type="text/csv",
            content=b"Employee ID,Full Name\n001,Test Person\n",
        )
    assert repository.roster_import is None
    assert session.rollbacks == 1
    assert storage.deletes == [storage.puts[0][0]]


class FakeScalarResult:
    def __init__(self, values: list[tuple[str, UUID]]) -> None:
        self.values = values

    def all(self) -> list[tuple[str, UUID]]:
        return self.values


class RegistrySession:
    def __init__(self, result_sets: list[list[tuple[str, UUID]]]) -> None:
        self.result_sets = iter(result_sets)
        self.statements = []

    async def execute(self, statement):  # noqa: ANN001, ANN202
        self.statements.append(statement)
        return FakeScalarResult(next(self.result_sets))


async def test_repository_registry_lookup_is_tenant_scoped_and_read_only() -> None:
    person_id = uuid4()
    session = RegistrySession(
        [
            [("001", person_id)],
            [("test@example.com", person_id)],
            [("test@example.com", person_id)],
            [],
            [],
        ]
    )
    repository = OrganizationRosterImportRepository(session)  # type: ignore[arg-type]
    match = await repository.match_registry(
        uuid4(),
        OrganizationRosterType.EMPLOYEE,
        {"employee_id": "001", "work_email": "test@example.com", "phone": "+919999999999"},
    )
    assert match == RegistryMatch(person_id=person_id)
    assert len(session.statements) == 5
    assert all("organization_id" in str(statement) for statement in session.statements)


async def test_registry_lookup_query_count_is_bounded_for_batch() -> None:
    first_id = uuid4()
    second_id = uuid4()
    session = RegistrySession(
        [
            [("001", first_id), ("002", second_id)],
            [],
            [],
        ]
    )
    repository = OrganizationRosterImportRepository(session)  # type: ignore[arg-type]
    matches = await repository.match_registry_batch(
        uuid4(),
        OrganizationRosterType.EMPLOYEE,
        (
            {"employee_id": "001", "work_email": "one@example.com"},
            {"employee_id": "002", "work_email": "two@example.com"},
        ),
    )
    assert matches == (RegistryMatch(person_id=first_id), RegistryMatch(person_id=second_id))
    assert len(session.statements) == 3


async def test_repository_rejects_identifiers_pointing_to_different_people() -> None:
    session = RegistrySession([[("001", uuid4())], [("test@example.com", uuid4())], [], [], []])
    repository = OrganizationRosterImportRepository(session)  # type: ignore[arg-type]
    match = await repository.match_registry(
        uuid4(),
        OrganizationRosterType.EMPLOYEE,
        {"employee_id": "001", "work_email": "test@example.com", "phone": "+919999999999"},
    )
    assert match.person_id is None
    assert match.is_conflict is True


async def test_s3_adapter_uses_private_encrypted_put(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    class FakeClient:
        def put_object(self, **kwargs):  # noqa: ANN003, ANN202
            calls.append(kwargs)

    monkeypatch.setattr(
        "app.organization_roster_import.storage.get_s3_client",
        lambda settings: FakeClient(),
    )
    settings = Settings(
        database_url="postgresql+asyncpg://kairo:kairo@localhost:5432/kairo",
        jwt_secret_key="test-jwt-secret-key-32-chars-minimum!!",
        s3_documents_bucket="private-test-bucket",
    )
    storage = S3RosterSourceStorage(settings)
    await storage.put_private(
        object_key="private/import.csv",
        content=b"data",
        content_type="text/csv",
    )
    assert calls == [
        {
            "Bucket": "private-test-bucket",
            "Key": "private/import.csv",
            "Body": b"data",
            "ContentType": "text/csv",
            "ContentDisposition": "attachment",
            "ServerSideEncryption": "AES256",
            "Metadata": {"retention-days": "30"},
            "Tagging": "data-class=organization-roster&retention-days=30",
        }
    ]
    assert "ACL" not in calls[0]
