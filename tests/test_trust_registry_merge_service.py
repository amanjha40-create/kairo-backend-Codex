"""Integration coverage for Trust Registry merge behavior."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401
from app.models.organization import Organization
from app.models.trust_registry_merge_history import TrustRegistryMergeHistory
from app.models.trust_registry_record import TrustRegistryRecord
from app.models.user import User
from app.models.verification_request import VerificationRequest
from app.organization.enums import OrganizationType
from app.schemas.trust_registry import (
    TrustRegistryAliasCreateRequest,
    TrustRegistryDomainCreateRequest,
    TrustRegistryIdentifierCreateRequest,
    TrustRegistryMergeRequest,
    TrustRegistryRecordCapabilityCreateRequest,
    TrustRegistryRecordCreateRequest,
    TrustRegistryRelationshipCreateRequest,
)
from app.services.trust_registry_resolution_service import TrustRegistryResolutionService
from app.services.trust_registry_service import TrustRegistryService
from app.trust_registry.enums import (
    TrustRegistryAliasType,
    TrustRegistryRelationshipType,
    TrustRegistrySourceType,
)
from app.verification_requests.enums import (
    VerificationRequestOriginType,
    VerificationRequestStatus,
    VerificationRequestType,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]
TEST_DATABASE_URL = os.environ["DATABASE_URL"]

TRUNCATE_TABLES = [
    "verification_request_events",
    "verification_request_evidence",
    "verification_request_reviews",
    "verification_connector_runs",
    "verification_contacts",
    "verification_requests",
    "organization_person_passport_access",
    "organization_person_notes",
    "organization_person_identifiers",
    "organization_people",
    "organization_members",
    "organization_invitations",
    "trust_invitations",
    "organizations",
    "trust_registry_merge_history",
    "trust_registry_relationships",
    "trust_registry_record_capabilities",
    "trust_registry_capabilities",
    "trust_registry_identifiers",
    "trust_registry_aliases",
    "trust_registry_domains",
    "trust_registry_records",
    "refresh_tokens",
    "user_social_accounts",
    "users",
]


@pytest.fixture
async def session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True, poolclass=NullPool)
    factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
async def reset_database(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await session.execute(
            text(f'TRUNCATE TABLE {", ".join(TRUNCATE_TABLES)} RESTART IDENTITY CASCADE')
        )
        await session.commit()
    yield
    async with session_factory() as session:
        await session.execute(
            text(f'TRUNCATE TABLE {", ".join(TRUNCATE_TABLES)} RESTART IDENTITY CASCADE')
        )
        await session.commit()


async def _create_admin_user(
    session_factory: async_sessionmaker[AsyncSession],
) -> User:
    async with session_factory() as session:
        actor = User(email=f"admin-{uuid4().hex[:8]}@kairo.test", role="admin", is_active=True)
        session.add(actor)
        await session.commit()
        await session.refresh(actor)
        return actor


async def _create_registry_fixture(
    *,
    actor: User,
    session_factory: async_sessionmaker[AsyncSession],
    with_source_links: bool = True,
    add_duplicate_capability: bool = True,
) -> dict[str, object]:
    async with session_factory() as session:
        registry = TrustRegistryService(session)

        target = await registry.create_record(
            actor.id,
            TrustRegistryRecordCreateRequest(
                legal_name=f"Disposable Target {uuid4().hex[:6]}",
                display_name="Disposable Target",
                organization_type="employer",
                country="IN",
            ),
        )
        source = await registry.create_record(
            actor.id,
            TrustRegistryRecordCreateRequest(
                legal_name=f"Disposable Source {uuid4().hex[:6]}",
                display_name="Disposable Source",
                organization_type="employer",
                country="IN",
            ),
        )

        await registry.add_alias(
            target.public_id,
            TrustRegistryAliasCreateRequest(
                alias_name="Canonical target alias",
                alias_type=TrustRegistryAliasType.ALTERNATE_NAME,
                source_type=TrustRegistrySourceType.MANUAL,
                source_metadata={},
            ),
        )
        await registry.add_alias(
            source.public_id,
            TrustRegistryAliasCreateRequest(
                alias_name="Canonical source alias",
                alias_type=TrustRegistryAliasType.ALTERNATE_NAME,
                source_type=TrustRegistrySourceType.MANUAL,
                source_metadata={},
            ),
        )
        await registry.add_domain(
            target.public_id,
            TrustRegistryDomainCreateRequest(
                domain=f"target-{uuid4().hex[:8]}.test",
                is_primary=True,
                is_verified=True,
                source_type=TrustRegistrySourceType.MANUAL,
                source_metadata={},
            ),
        )
        target_detail = await registry.get_detail(target.public_id)
        target_domain = next(domain.domain for domain in target_detail.domains)
        await registry.add_domain(
            source.public_id,
            TrustRegistryDomainCreateRequest(
                domain=f"source-{uuid4().hex[:8]}.test",
                is_primary=True,
                is_verified=True,
                source_type=TrustRegistrySourceType.MANUAL,
                source_metadata={},
            ),
        )
        source_detail = await registry.get_detail(source.public_id)
        source_domain = next(domain.domain for domain in source_detail.domains)
        await registry.add_identifier(
            target.public_id,
            TrustRegistryIdentifierCreateRequest(
                identifier_type="admin3_target_id",
                identifier_value=f"T-{uuid4().hex[:10]}",
                issuing_country="IN",
                source_type=TrustRegistrySourceType.MANUAL,
                source_metadata={},
            ),
        )
        target_detail = await registry.get_detail(target.public_id)
        target_identifier = next(
            (identifier.identifier_type, identifier.identifier_value)
            for identifier in target_detail.identifiers
        )
        await registry.add_identifier(
            source.public_id,
            TrustRegistryIdentifierCreateRequest(
                identifier_type="admin3_source_id",
                identifier_value=f"S-{uuid4().hex[:10]}",
                issuing_country="IN",
                source_type=TrustRegistrySourceType.MANUAL,
                source_metadata={},
            ),
        )
        source_detail = await registry.get_detail(source.public_id)
        source_identifier = next(
            (identifier.identifier_type, identifier.identifier_value)
            for identifier in source_detail.identifiers
        )
        await registry.add_capability_assignment(
            target.public_id,
            TrustRegistryRecordCapabilityCreateRequest(
                capability_key="employment",
                display_name="Employment",
                source_type=TrustRegistrySourceType.MANUAL,
                source_metadata={},
            ),
        )
        if add_duplicate_capability:
            await registry.add_capability_assignment(
                source.public_id,
                TrustRegistryRecordCapabilityCreateRequest(
                    capability_key="employment",
                    display_name="Employment",
                    source_type=TrustRegistrySourceType.MANUAL,
                    source_metadata={},
                ),
            )
        await registry.add_relationship(
            target.public_id,
            TrustRegistryRelationshipCreateRequest(
                child_registry_record_public_id=source.public_id,
                relationship_type=TrustRegistryRelationshipType.AFFILIATE_OF,
                metadata={},
            ),
        )

        source_record = await registry._require_record(source.public_id)  # noqa: SLF001

        organization = None
        verification_request = None
        unrelated = await registry.create_record(
            actor.id,
            TrustRegistryRecordCreateRequest(
                legal_name=f"Unrelated Registry {uuid4().hex[:6]}",
                display_name="Unrelated Registry",
                organization_type="employer",
                country="IN",
            ),
        )
        unrelated_record = await registry._require_record(unrelated.public_id)  # noqa: SLF001

        if with_source_links:
            organization = Organization(
                created_by_user_id=actor.id,
                name=f"Source-linked Org {uuid4().hex[:6]}",
                organization_type=OrganizationType.EMPLOYER,
                domain=f"org-{uuid4().hex[:8]}.test",
                verification_capabilities=["employment"],
                registry_record_id=source_record.id,
            )
            session.add(organization)
            await session.flush()

            verification_request = VerificationRequest(
                origin_type=VerificationRequestOriginType.ADMIN_CREATED,
                organization_id=organization.id,
                subject_user_id=actor.id,
                subject_name="Merge Subject",
                subject_email=f"subject-{uuid4().hex[:8]}@kairo.test",
                target_organization_name=organization.name,
                request_type=VerificationRequestType.EMPLOYMENT,
                status=VerificationRequestStatus.PENDING_ADMIN_REVIEW,
                requested_by_user_id=actor.id,
                registry_record_id=source_record.id,
                consented_fields=[],
                consented_evidence_scope=[],
            )
            session.add(verification_request)
            await session.commit()
            await session.refresh(organization)
            await session.refresh(verification_request)

        return {
            "target": target,
            "source": source,
            "unrelated": unrelated,
            "organization": organization,
            "verification_request": verification_request,
            "unrelated_record_id": unrelated_record.id,
            "target_domain": target_domain,
            "source_domain": source_domain,
            "target_identifier": target_identifier,
            "source_identifier": source_identifier,
        }


async def test_merge_records_consolidates_child_data_and_links(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _create_admin_user(session_factory)
    fixture = await _create_registry_fixture(actor=actor, session_factory=session_factory)

    async with session_factory() as session:
        resolver = TrustRegistryResolutionService(session)

        result = await resolver.merge_records(
            actor.id,
            fixture["source"].public_id,
            TrustRegistryMergeRequest(
                target_registry_record_public_id=fixture["target"].public_id,
                merge_reason="integration merge",
                metadata={"scope": "test"},
            ),
        )

        assert result.source_registry_record_public_id == fixture["source"].public_id
        assert result.target_registry_record_public_id == fixture["target"].public_id

        target = await resolver._records.get_by_public_id(fixture["target"].public_id)  # noqa: SLF001
        source = await session.execute(
            select(TrustRegistryRecord).where(
                TrustRegistryRecord.public_id == fixture["source"].public_id
            )
        )
        source_record = source.scalar_one()
        organization = await session.get(Organization, fixture["organization"].id)
        verification_request = await session.get(
            VerificationRequest, fixture["verification_request"].id
        )
        merge_history = (
            (
                await session.execute(
                    select(TrustRegistryMergeHistory).where(
                        TrustRegistryMergeHistory.source_registry_record_id == source_record.id,
                        TrustRegistryMergeHistory.target_registry_record_id == target.id,
                    )
                )
            )
            .scalars()
            .all()
        )

        assert target is not None
        assert source_record.deleted_at is not None
        assert source_record.lifecycle_status == "archived"
        assert {alias.alias_name for alias in target.aliases if alias.deleted_at is None} == {
            "Canonical target alias",
            "Canonical source alias",
        }
        assert {domain.domain for domain in target.domains if domain.deleted_at is None} == {
            fixture["target_domain"],
            fixture["source_domain"],
        }
        assert {
            (identifier.identifier_type, identifier.identifier_value)
            for identifier in target.identifiers
            if identifier.deleted_at is None
        } == {
            fixture["target_identifier"],
            fixture["source_identifier"],
        }
        assert {cap.capability.capability_key for cap in target.capabilities} == {"employment"}
        assert all(
            relationship.deleted_at is not None for relationship in target.parent_relationships
        )
        assert organization.registry_record_id == target.id
        assert verification_request.registry_record_id == target.id
        assert len(merge_history) == 1
        assert merge_history[0].source_registry_record_id == source_record.id
        assert merge_history[0].merge_reason == "integration merge"


async def test_merge_records_rolls_back_atomically_when_merge_history_write_fails(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _create_admin_user(session_factory)
    fixture = await _create_registry_fixture(actor=actor, session_factory=session_factory)

    async with session_factory() as session:
        resolver = TrustRegistryResolutionService(session)

        async def fail_create(_merge_event):  # noqa: ANN001
            raise RuntimeError("forced merge-history failure")

        resolver._merges.create = fail_create  # type: ignore[method-assign]  # noqa: SLF001

        with pytest.raises(RuntimeError, match="forced merge-history failure"):
            await resolver.merge_records(
                actor.id,
                fixture["source"].public_id,
                TrustRegistryMergeRequest(
                    target_registry_record_public_id=fixture["target"].public_id,
                    merge_reason="integration merge",
                    metadata={"scope": "test"},
                ),
            )

        await session.rollback()

        target = await resolver._records.get_by_public_id(fixture["target"].public_id)  # noqa: SLF001
        source = await resolver._records.get_by_public_id(fixture["source"].public_id)  # noqa: SLF001
        organization = await session.get(Organization, fixture["organization"].id)
        verification_request = await session.get(
            VerificationRequest, fixture["verification_request"].id
        )
        unrelated = await resolver._records.get_by_public_id(fixture["unrelated"].public_id)  # noqa: SLF001
        merge_history = (
            (await session.execute(select(TrustRegistryMergeHistory))).scalars().all()
        )

        assert target is not None
        assert source is not None
        assert source.deleted_at is None
        assert source.lifecycle_status == "draft"
        assert organization.registry_record_id == source.id
        assert verification_request.registry_record_id == source.id
        assert len(merge_history) == 0
        assert unrelated is not None
        assert unrelated.id == fixture["unrelated_record_id"]
