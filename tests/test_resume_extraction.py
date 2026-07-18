from __future__ import annotations

from datetime import date

import pytest

from app.resumes.extraction import enrich_employment_claims, normalize_extracted_payload, parse_resume_date


@pytest.mark.parametrize(
    ("raw", "display", "precision"),
    [
        ("Jan 2023", "2023-01", "month"),
        ("January 2023", "2023-01", "month"),
        ("01/2023", "2023-01", "month"),
        ("1/2023", "2023-01", "month"),
        ("2023-01", "2023-01", "month"),
        ("2023", "2023", "year"),
        ("Jan'23", "2023-01", "month"),
        ("Jan 23", "2023-01", "month"),
    ],
)
def test_partial_resume_dates_preserve_precision(raw: str, display: str, precision: str) -> None:
    parsed, actual_display, actual_precision, current = parse_resume_date(raw)

    assert parsed is None
    assert actual_display == display
    assert actual_precision == precision
    assert current is False


@pytest.mark.parametrize("raw", ["Current", "Present", "Till Date", "Ongoing", "Now", "Current Role"])
def test_current_resume_dates_are_not_fabricated(raw: str) -> None:
    parsed, display, precision, current = parse_resume_date(raw)

    assert parsed is None
    assert display == raw
    assert precision is None
    assert current is True


def test_exact_date_keeps_day_precision() -> None:
    parsed, display, precision, current = parse_resume_date("2023-01-15")

    assert parsed == date(2023, 1, 15)
    assert display == "2023-01-15"
    assert precision == "day"
    assert current is False


def test_location_alias_preserves_original_display() -> None:
    result = normalize_extracted_payload(
        {"employments": [{"location": {"city": "Bangalore"}}]},
    )

    assert result["employments"][0]["location"] == {"city": "Bengaluru", "display": "Bangalore"}


def test_nearby_employment_text_fills_high_confidence_date_and_location() -> None:
    result = enrich_employment_claims(
        {"employments": [{"company_name": "Northwind Labs", "role_title": "Engineer"}]},
        "Northwind Labs | Engineer | Bangalore | Jan 2023 - Present",
    )

    employment = result["employments"][0]
    assert employment["start_date_display"] == "2023-01"
    assert employment["start_date_precision"] == "month"
    assert employment["end_date_display"] == "Present"
    assert employment["is_current"] is True
    assert employment["location"]["city"] == "Bengaluru"
    assert employment["location"]["display"].endswith("Bangalore | Jan 2023 - Present")


def test_invalid_links_are_removed_without_breaking_parsed_result() -> None:
    result = normalize_extracted_payload(
        {
            "candidate_profile": {"profile_links": ["not-a-url", "https://example.com/profile"]},
            "portfolio_links": ["also-not-a-url"],
        }
    )
    assert result["candidate_profile"]["profile_links"] == ["https://example.com/profile"]
    assert result["portfolio_links"] == []
    assert "invalid_profile_link_removed" in result["warnings"]


def test_profile_links_are_bounded_to_review_schema_limit() -> None:
    result = normalize_extracted_payload(
        {"candidate_profile": {"profile_links": [f"https://example.com/{index}" for index in range(25)]}}
    )
    assert len(result["candidate_profile"]["profile_links"]) == 20
