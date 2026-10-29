"""Durable DigiLocker verification and Home summary contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from test_digilocker_lifecycle import harness as digilocker_harness  # noqa: F401

from app.db.session import async_session_factory
from app.main import app
from app.models import (
    DigiLockerConnection,
    DigiLockerIdentityVerification,
    Education,
    EducationDocument,
    User,
)
from app.services.digilocker_discovery_service import DigiLockerDiscoveryService
from app.services.digilocker_home_summary import DigiLockerHomeSummaryService
from app.services.education_service import EducationService


@pytest.fixture(name="harness")
async def harness_fixture(digilocker_harness):  # noqa: F811
    yield digilocker_harness


def test_openapi_exposes_durable_verification_and_home_contracts():
    schema = app.openapi()["components"]["schemas"]
    education = schema["EducationResponse"]["properties"]
    assert {"verification_status", "verification_source", "verified_at"} <= set(education)
    dashboard = schema["DashboardResponse"]["properties"]
    assert "digilocker" in dashboard
    summary = schema["DashboardDigiLockerSummary"]["properties"]
    assert {
        "connection_status",
        "verified_records_count",
        "new_records_available_count",
        "needs_review_count",
        "last_synced_at",
        "discovery_status",
    } <= set(summary)


async def _seed_verified_records(harness):
    connection = await harness.activate()
    accepted_at = datetime.now(tz=UTC)
    async with async_session_factory() as session:
        user = await session.get(User, harness.ids[0])
        user.full_name = "Synthetic Candidate"
        user.date_of_birth = date(1990, 1, 1)
        await session.flush()
        session.add(
            DigiLockerIdentityVerification(
                user_id=user.id,
                source_connection_id=connection.id,
                source="digilocker",
                source_type="issued_document",
                document_type="DRVLC",
                issuer_id="synthetic",
                issuer_name="Synthetic Issuer",
                provider_reference_fingerprint="a" * 64,
                consent_purpose="identity_verification",
                consent_version="v1",
                consented_at=accepted_at,
                integrity_result="verified",
                match_result="VERIFIED_MATCH",
                match_reason="NAME_EXACT_MATCH",
                masked_identifier="••••••••1234",
                verified_at=accepted_at,
                document_valid_until=None,
                profile_revision_at=accepted_at,
            )
        )
        education = Education(
            user_id=user.id,
            institution_name="Synthetic School",
            degree="Class X",
            education_level="high_school",
            is_currently_studying=False,
            verification_status="draft",
        )
        session.add(education)
        await session.flush()
        session.add(
            EducationDocument(
                education_id=education.id,
                uploaded_by_user_id=user.id,
                document_type="marksheet",
                object_key=f"test/education/{education.id}/{uuid4()}.xml",
                original_filename="synthetic.xml",
                content_type="application/xml",
                byte_size=10,
                checksum_sha256="b" * 64,
                verification_status="verified",
                verified_at=accepted_at,
                extracted_payload={"digilocker": {"source": "digilocker"}},
            )
        )
        await session.commit()
        return education.id, accepted_at


async def test_legacy_education_projects_durable_digilocker_state(harness):
    education_id, accepted_at = await _seed_verified_records(harness)
    async with async_session_factory() as session:
        education = await session.get(Education, education_id)
        response = await EducationService(session, harness.config).response(education)
    assert response.verification_status == "verified"
    assert response.verification_source == "digilocker"
    assert response.verified_at == accepted_at


async def test_home_summary_counts_canonical_records_and_live_groups(
    harness,
    monkeypatch,
):
    await _seed_verified_records(harness)
    discovered_at = datetime.now(tz=UTC)
    available = AsyncMock(
        return_value={
            "identity": [{"import_status": "available"}],
            "education": [
                {"import_status": "already_added"},
                {"import_status": "needs_review"},
            ],
            "address_candidates": [],
            "counts": {},
            "discovered_at": discovered_at,
        }
    )
    monkeypatch.setattr(DigiLockerDiscoveryService, "available_records", available)
    async with async_session_factory() as session:
        summary = await DigiLockerHomeSummaryService(
            session,
            harness.config,
            harness.redis,
        ).build(harness.ids[0])
    assert summary.connection_status == "connected"
    assert summary.verified_records_count == 2
    assert summary.new_records_available_count == 1
    assert summary.needs_review_count == 1
    assert summary.last_synced_at == discovered_at
    assert summary.discovery_status == "fresh"


async def test_reconnect_required_preserves_verified_count(
    harness,
    monkeypatch,
):
    await _seed_verified_records(harness)
    async with async_session_factory() as session:
        connection = await session.scalar(
            select(DigiLockerConnection).where(
                DigiLockerConnection.user_id == harness.ids[0]
            )
        )
        connection.status = "reconnect_required"
        connection.encrypted_access_token = None
        connection.encrypted_refresh_token = None
        connection.token_expires_at = None
        connection.consent_valid_until = None
        connection.granted_scopes = []
        await session.commit()

    available = AsyncMock()
    monkeypatch.setattr(DigiLockerDiscoveryService, "available_records", available)
    async with async_session_factory() as session:
        summary = await DigiLockerHomeSummaryService(
            session,
            harness.config,
            harness.redis,
        ).build(harness.ids[0])
    assert summary.connection_status == "reconnect_required"
    assert summary.verified_records_count == 2
    assert summary.new_records_available_count is None
    assert summary.needs_review_count is None
    assert summary.discovery_status == "reconnect_required"
    available.assert_not_awaited()
