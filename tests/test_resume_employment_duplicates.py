from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.resume_duplicate_service import ResumeDuplicateService


async def assess(payload, **existing):
    values = dict(
        id=uuid4(),
        employer_legal_name="Futures First Info Services Pvt. Ltd.",
        job_title="Business Analyst",
        start_date=date(2021, 1, 1),
        end_date=date(2023, 12, 31),
        verification_status="verified",
        verified_at=None,
    )
    row = SimpleNamespace(**(values | existing))

    class Session:
        async def scalars(self, statement):
            rows = [row] if "FROM employments" in str(statement) else []
            return SimpleNamespace(all=lambda: rows)

    return await ResumeDuplicateService(Session()).assess(uuid4(), "employment", payload)


@pytest.mark.asyncio
async def test_legal_suffix_duplicate_is_not_treated_as_new():
    result = await assess(
        {
            "company_name": "Futures First Info Services Private Limited",
            "role_title": " business  analyst ",
            "start_date": "2021-01-01",
            "end_date": "2023-12-31",
            "is_current": False,
        }
    )
    assert result.status == "exact_match"


@pytest.mark.parametrize(
    "company",
    [
        "Futures First Info Services Pvt Ltd",
        "FUTURES FIRST INFO SERVICES Private Limited",
        " Futures  First Info Services Ltd. ",
        "Futures First Info Services LLC",
        "Futures First Info Services LLP",
        "Futures First Info Services Inc.",
        "Futures First Info Services Incorporated",
        "Futures First Info Services Corp.",
        "Futures First Info Services Corporation",
    ],
)
@pytest.mark.asyncio
async def test_comparison_only_suffix_variants(company):
    result = await assess(
        {
            "company_name": company,
            "role_title": "Business-Analyst",
            "start_date": "2021-01-01",
            "end_date": "2023-12-31",
        }
    )
    assert result.status == "exact_match"
    assert result.candidates[0]["employer"] == "Futures First Info Services Pvt. Ltd."


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"role_title": "Senior Business Analyst"}, "no_match"),
        ({"role_title": "Software Engineer"}, "no_match"),
        ({"start_date": "2024-01-01", "end_date": "2025-01-01"}, "no_match"),
        ({"start_date": None}, "possible_match"),
        ({"end_date": None}, "possible_match"),
        ({"role_title": "Business Analysis Analyst"}, "possible_match"),
        ({"role_title": "Business Analyist"}, "possible_match"),
        (
            {"start_date_display": "2021", "start_date": None, "start_date_precision": "year"},
            "possible_match",
        ),
        ({"company_name": "Other Company"}, "no_match"),
        ({"company_name": "Futures First Info Services Research Ltd"}, "no_match"),
    ],
)
@pytest.mark.asyncio
async def test_conservative_role_and_date_matching(payload, expected):
    result = await assess(
        {
            "company_name": "Futures First Info Services",
            "role_title": "Business Analyst",
            "start_date": "2021-01-01",
            "end_date": "2023-12-31",
        }
        | payload
    )
    assert result.status == expected


@pytest.mark.asyncio
async def test_current_role_requires_explicit_imported_current_state():
    payload = {
        "company_name": "Futures First Info Services",
        "role_title": "Business Analyst",
        "start_date": "2021-01-01",
        "end_date": None,
    }
    assert (await assess(payload, end_date=None)).status == "possible_match"
    assert (await assess(payload | {"is_current": True}, end_date=None)).status == "exact_match"


@pytest.mark.asyncio
async def test_month_precision_duplicate_uses_display_dates():
    result = await assess(
        {
            "company_name": "Futures First Info Services Pvt Ltd",
            "role_title": "Business Analyst",
            "start_date": None,
            "start_date_display": "Jan 2021",
            "start_date_precision": "month",
            "end_date_display": "Dec 2023",
            "end_date_precision": "month",
            "is_current": False,
        }
    )
    assert result.status == "exact_match"


@pytest.mark.asyncio
async def test_seniority_abbreviation_is_reviewed_not_merged_or_assumed_distinct():
    result = await assess(
        {
            "company_name": "Futures First Info Services",
            "role_title": "Sr. Business Analyst",
            "start_date": "2021-01-01",
            "end_date": "2023-12-31",
        },
        job_title="Senior Business Analyst",
    )
    assert result.status == "possible_match"


@pytest.mark.asyncio
async def test_conflicting_employment_type_reduces_confidence():
    result = await assess(
        {
            "company_name": "Futures First Info Services",
            "role_title": "Business Analyst",
            "start_date": "2021-01-01",
            "end_date": "2023-12-31",
            "employment_type": "contract",
        },
        employment_type="full_time",
    )
    assert result.status == "possible_match"
