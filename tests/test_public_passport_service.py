"""Focused service tests for public Trust Passport privacy filtering."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.education import Education
from app.models.employment import Employment
from app.schemas.passport_share import PassportSharePermissions
from app.services.public_passport_service import PublicPassportService


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _ExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _ScalarResult(self._rows)


class _FakeSession:
    def __init__(self, *, employments=None, educations=None):
        self._employments = list(employments or [])
        self._educations = list(educations or [])

    async def execute(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if entity is Employment:
            rows = self._employments
            for criterion in statement._where_criteria:
                if str(criterion.left).endswith("verification_status"):
                    right = getattr(criterion.right, "value", None)
                    if right is None:
                        continue
                    allowed = (
                        set(right)
                        if isinstance(right, (tuple, list, set, frozenset))
                        else {right}
                    )
                    rows = [row for row in rows if row.verification_status in allowed]
            return _ExecuteResult(rows)
        if entity is Education:
            rows = self._educations
            for criterion in statement._where_criteria:
                if str(criterion.left).endswith("verification_status"):
                    right = getattr(criterion.right, "value", None)
                    if right is None:
                        continue
                    allowed = (
                        set(right)
                        if isinstance(right, (tuple, list, set, frozenset))
                        else {right}
                    )
                    rows = [row for row in rows if row.verification_status in allowed]
            return _ExecuteResult(rows)
        raise AssertionError(f"Unexpected entity query: {entity}")


def _service(session: _FakeSession) -> PublicPassportService:
    return PublicPassportService(session, SimpleNamespace())


def _employment(*, status: str, employer: str) -> Employment:
    return Employment(
        id=uuid4(),
        created_by_user_id=uuid4(),
        subject_full_name="Candidate User",
        employer_legal_name=employer,
        job_title="Analyst",
        start_date=date(2024, 1, 1),
        verification_status=status,
        verification_method="document",
    )


def _education(*, status: str, institution: str) -> Education:
    return Education(
        id=uuid4(),
        user_id=uuid4(),
        institution_name=institution,
        degree="BBA",
        field_of_study="Finance",
        start_date=date(2020, 6, 1),
        end_date=date(2024, 5, 31),
        is_currently_studying=False,
        verification_status=status,
    )


@pytest.mark.asyncio
async def test_public_vault_filters_employment_and_education_to_trusted_records_only() -> None:
    session = _FakeSession(
        employments=[
            _employment(status="approved", employer="Verified Employer"),
            _employment(status="verified", employer="Verified Legacy Employer"),
            _employment(status="draft", employer="Draft Employer"),
            _employment(status="submitted", employer="Pending Employer"),
            _employment(status="rejected", employer="Rejected Employer"),
        ],
        educations=[
            _education(status="verified", institution="Verified University"),
            _education(status="draft", institution="Draft College"),
            _education(status="pending", institution="Pending Institute"),
            _education(status="unable_to_verify", institution="Unable Institute"),
        ],
    )
    service = _service(session)

    vault = await service.build_vault_for_user(
        uuid4(),
        PassportSharePermissions(
            include_employments=True,
            include_educations=True,
            include_internships=False,
            include_freelance=False,
            include_gig_platforms=False,
            include_portfolio=False,
            include_certifications=False,
            include_skills=False,
            include_projects=False,
            include_user_documents=False,
            show_employer_names=False,
            show_documents=False,
        ),
        public_only=True,
    )

    assert [row.verification_status for row in vault.employments] == ["approved", "verified"]
    assert [row.employer_legal_name for row in vault.employments] == [None, None]
    assert [row.verification_status for row in vault.educations] == ["verified"]
    assert [row.institution_name for row in vault.educations] == ["Verified University"]


@pytest.mark.asyncio
async def test_owner_vault_keeps_full_career_history() -> None:
    session = _FakeSession(
        employments=[
            _employment(status="approved", employer="Verified Employer"),
            _employment(status="verified", employer="Verified Legacy Employer"),
            _employment(status="draft", employer="Draft Employer"),
            _employment(status="submitted", employer="Pending Employer"),
        ],
        educations=[
            _education(status="verified", institution="Verified University"),
            _education(status="draft", institution="Draft College"),
            _education(status="pending", institution="Pending Institute"),
        ],
    )
    service = _service(session)

    vault = await service.build_vault_for_user(
        uuid4(),
        PassportSharePermissions(
            include_employments=True,
            include_educations=True,
            include_internships=False,
            include_freelance=False,
            include_gig_platforms=False,
            include_portfolio=False,
            include_certifications=False,
            include_skills=False,
            include_projects=False,
            include_user_documents=False,
            show_employer_names=True,
            show_documents=False,
        ),
        public_only=False,
    )

    assert [row.verification_status for row in vault.employments] == [
        "approved",
        "verified",
        "draft",
        "submitted",
    ]
    assert [row.employer_legal_name for row in vault.employments] == [
        "Verified Employer",
        "Verified Legacy Employer",
        "Draft Employer",
        "Pending Employer",
    ]
    assert [row.verification_status for row in vault.educations] == ["verified", "draft", "pending"]
