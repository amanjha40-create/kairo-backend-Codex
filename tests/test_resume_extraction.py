from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from app.resumes.extraction import (
    enrich_employment_claims,
    enrich_explicit_skills,
    normalize_extracted_payload,
    parse_resume_date,
    reconcile_pdf_education_blocks,
    reconcile_pdf_employment_dates,
    reconcile_pdf_source_associations,
)
from app.resumes.providers import TextractDocumentExtractor, extract_pdf_embedded_text
from app.resumes.schemas import ParsedResumeResult
from app.resumes.stage_diagnostics import (
    PrivacySafeResumeStageDiagnostics,
    append_lifecycle_diagnostic_stage,
    import_payload_fingerprints,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "resume_golden"


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
        ("0ct 2021", "2021-10", "month"),
    ],
)
def test_partial_resume_dates_preserve_precision(raw: str, display: str, precision: str) -> None:
    parsed, actual_display, actual_precision, current = parse_resume_date(raw)

    assert parsed is None
    assert actual_display == display
    assert actual_precision == precision
    assert current is False


@pytest.mark.parametrize(
    "raw", ["Current", "Present", "Till Date", "Ongoing", "Now", "Current Role"]
)
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
        {
            "candidate_profile": {
                "profile_links": [f"https://example.com/{index}" for index in range(25)]
            }
        }
    )
    assert len(result["candidate_profile"]["profile_links"]) == 20


def test_nullable_model_collections_and_claim_metadata_are_normalized_safely() -> None:
    result = normalize_extracted_payload(
        {
            "candidate_profile": {"profile_links": None},
            "employments": [
                {
                    "company_name": "Synthetic Company",
                    "role_title": "Engineer",
                    "warnings": None,
                    "source_type": None,
                    "selected_for_import": True,
                }
            ],
            "education": None,
            "skills": None,
            "warnings": None,
        }
    )

    assert result["candidate_profile"]["profile_links"] == []
    assert result["education"] == []
    assert result["skills"] == []
    assert result["warnings"] == []
    assert result["employments"][0]["warnings"] == []
    assert result["employments"][0]["source_type"] == "resume"
    assert result["employments"][0]["selected_for_import"] is False


def test_unsupported_long_skill_is_rejected_not_truncated_into_a_claim() -> None:
    result = normalize_extracted_payload({"skills": [{"name": "x" * 200}]})
    assert result["skills"] == []
    assert "skill_rejected_unsupported_inference" in result["warnings"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("SKILLS\nPython, FastAPI, PostgreSQL", ["Python", "FastAPI", "PostgreSQL"]),
        (
            "My core skills are Customer Onboarding, Account Management, and Salesforce.",
            ["Customer Onboarding", "Account Management", "Salesforce"],
        ),
        (
            "Technical Skills: Machine Learning; Data Analysis • Cloud Security | Python",
            ["Machine Learning", "Data Analysis", "Cloud Security", "Python"],
        ),
    ],
)
def test_explicit_section_and_narrative_skill_lists_are_preserved(
    text: str,
    expected: list[str],
) -> None:
    result = enrich_explicit_skills({"skills": []}, text)

    assert [item["name"] for item in result["skills"]] == expected


def test_explicit_skills_are_case_insensitively_deduplicated() -> None:
    result = enrich_explicit_skills(
        {"skills": [{"name": "python"}]},
        "Skills: Python, PYTHON, FastAPI",
    )

    assert [item["name"] for item in result["skills"]] == ["python", "FastAPI"]


def test_unlabelled_prose_employers_and_titles_do_not_become_skills() -> None:
    result = enrich_explicit_skills(
        {"skills": []},
        (
            "Skills matter in every role and should be developed over time. "
            "I worked at Skills Cloud as a Skills Engineer."
        ),
    )

    assert result["skills"] == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("SKlLLS\nPython • Spark • SQL", ["Python", "Spark", "SQL"]),
        ("SK1LLS\nMachine Learning / Data Analysis", ["Machine Learning", "Data Analysis"]),
        (
            "SKILLS\nCloud Security\nMachine Learning\nPython\n\nEDUCATION",
            ["Cloud Security", "Machine Learning", "Python"],
        ),
    ],
)
def test_noisy_labelled_skill_lists_use_only_explicit_boundaries(
    text: str,
    expected: list[str],
) -> None:
    result = enrich_explicit_skills({"skills": []}, text)

    assert [item["name"] for item in result["skills"]] == expected


def test_collapsed_model_skill_is_replaced_by_source_backed_explicit_items() -> None:
    result = enrich_explicit_skills(
        {"skills": [{"name": "Machine Learning Data Analysis Python"}], "warnings": []},
        "SKlLLS\nMachine Learning • Data Analysis • Python",
    )

    assert [item["name"] for item in result["skills"]] == [
        "Machine Learning",
        "Data Analysis",
        "Python",
    ]
    assert "collapsed_explicit_skill_list_reconciled" in result["warnings"]


@pytest.mark.parametrize(
    ("model_skill", "source", "expected"),
    [
        (
            "Spark SQL Python",
            "SKILLS\nPython | Spark | SQL",
            ["Python", "Spark", "SQL"],
        ),
        (
            "Python SQL Spark",
            "SKILLS\nPython, SQL, Spark",
            ["Python", "SQL", "Spark"],
        ),
    ],
)
def test_reordered_model_skill_compositions_are_replaced_by_source_backed_items(
    model_skill: str,
    source: str,
    expected: list[str],
) -> None:
    result = enrich_explicit_skills(
        {"skills": [{"name": model_skill}], "warnings": []},
        source,
    )

    assert [item["name"] for item in result["skills"]] == expected
    assert "collapsed_explicit_skill_list_reconciled" in result["warnings"]


@pytest.mark.parametrize("skill", ["Machine Learning", "React Native", "Data Analysis"])
def test_source_backed_multi_word_skills_are_preserved(skill: str) -> None:
    result = enrich_explicit_skills(
        {"skills": [{"name": skill}], "warnings": []},
        f"SKILLS\n{skill}\n\nEDUCATION",
    )

    assert [item["name"] for item in result["skills"]] == [skill]
    assert "collapsed_explicit_skill_list_reconciled" not in result["warnings"]


def test_source_backed_multi_word_skill_survives_alongside_component_skill() -> None:
    result = enrich_explicit_skills(
        {"skills": [{"name": "Machine Learning"}, {"name": "Learning"}], "warnings": []},
        "SKILLS\nMachine Learning\nLearning\n\nEDUCATION",
    )

    assert [item["name"] for item in result["skills"]] == ["Machine Learning", "Learning"]


def test_skill_case_and_benign_punctuation_variants_are_deduplicated() -> None:
    result = enrich_explicit_skills(
        {"skills": [{"name": "python"}, {"name": "SQL;"}]},
        "Skills: Python, SQL",
    )

    assert [item["name"] for item in result["skills"]] == ["python", "SQL"]


def test_explicitly_supported_combined_skill_is_preserved() -> None:
    result = enrich_explicit_skills(
        {"skills": [{"name": "Spark SQL Python"}], "warnings": []},
        "SKILLS\nSpark SQL Python\n\nEDUCATION",
    )

    assert [item["name"] for item in result["skills"]] == ["Spark SQL Python"]
    assert "collapsed_explicit_skill_list_reconciled" not in result["warnings"]


def test_unsupported_combined_skill_is_not_split_without_source_evidence() -> None:
    result = enrich_explicit_skills(
        {"skills": [{"name": "Spark SQL Python"}], "warnings": []},
        "Built reliable data platforms.",
    )

    assert result["skills"] == []


def test_ocr_text_repairs_are_source_backed_and_do_not_rewrite_alphanumeric_brands() -> None:
    result = normalize_extracted_payload(
        {
            "candidate_profile": {"professional_headline": "Data Eng1neer"},
            "employments": [
                {"company_name": "Moonlit R1ver Data", "role_title": "Data Engineer"},
                {"company_name": "F1Soft", "role_title": "Platform Engineer"},
            ],
        },
        "DATA ENG1NEER\nMoonlit R1ver Data\nData Engineer\nF1Soft\nPlatform Engineer",
    )

    assert result["candidate_profile"]["professional_headline"] == "Data Engineer"
    assert result["employments"][0]["company_name"] == "Moonlit River Data"
    assert result["employments"][1]["company_name"] == "F1Soft"
    assert "source_corroborated_ocr_text_normalized" in result["warnings"]


def test_sanitized_live_textract_shape_reconstructs_and_normalizes_without_hallucination() -> None:
    fixture = json.loads((FIXTURE_ROOT / "textract_ocr_noise_blocks.json").read_text())
    extracted_text = TextractDocumentExtractor._lines({"Blocks": fixture["blocks"]})
    result = normalize_extracted_payload(fixture["model_payload"], extracted_text)
    expected = fixture["expected"]

    assert extracted_text.splitlines()[-2:] == ["SKlLLS", "Python | Spark | SQL"]
    assert result["candidate_profile"]["full_name"] == expected["profile_name"]
    assert result["candidate_profile"]["professional_headline"] == expected["profile_headline"]
    assert len(result["employments"]) == 1
    employment = result["employments"][0]
    assert employment["company_name"] == expected["employer"]
    assert employment["role_title"] == expected["role_title"]
    assert employment["start_date_display"] == expected["employment_start"]
    assert employment["is_current"] is expected["employment_current"]
    assert len(result["education"]) == expected["education_count"]
    assert result["certifications"] == []
    assert result["projects"] == []
    assert [item["name"] for item in result["skills"]] == expected["skills"]


def _employment_payload(*claims: dict[str, object]) -> dict[str, object]:
    return {"employments": list(claims)}


def test_ocr_fixture_embedded_text_recovers_explicit_omitted_employment_date() -> None:
    fixture = json.loads((FIXTURE_ROOT / "textract_ocr_noise_blocks.json").read_text())
    embedded = extract_pdf_embedded_text((FIXTURE_ROOT / "documents/ocr_noise.pdf").read_bytes())
    normalized = normalize_extracted_payload(
        fixture["model_payload"],
        TextractDocumentExtractor._lines({"Blocks": fixture["blocks"]}),
    )
    result = reconcile_pdf_employment_dates(
        normalized,
        "Moonlit R1ver Data\nData Engineer\nBuilt batch and streaming pipelines.",
        embedded,
    )

    employment = result["employments"][0]
    assert employment["company_name"] == fixture["expected"]["employer"]
    assert employment["start_date"] is None
    assert employment["start_date_display"] == "2021-10"
    assert employment["start_date_precision"] == "month"
    assert employment["end_date"] is None
    assert employment["end_date_display"] == "Present"
    assert employment["is_current"] is True
    assert len(result["education"]) == 1
    assert [item["name"] for item in result["skills"]] == ["Python", "Spark", "SQL"]


def test_matching_textract_and_embedded_dates_produce_one_canonical_value() -> None:
    result = reconcile_pdf_employment_dates(
        _employment_payload(
            {
                "company_name": "Northwind Labs",
                "role_title": "Engineer",
                "start_date": "2020-01-01",
            }
        ),
        "Northwind Labs\nEngineer\nOct 2021 - Present",
        "Northwind Labs\nEngineer\nOctober 2021 - Present",
    )

    employment = result["employments"][0]
    assert employment["start_date"] is None
    assert employment["start_date_display"] == "2021-10"
    assert employment["start_date_precision"] == "month"
    assert employment["is_current"] is True


def test_textract_date_is_preserved_when_embedded_text_is_absent() -> None:
    result = reconcile_pdf_employment_dates(
        _employment_payload({"company_name": "Northwind Labs", "role_title": "Engineer"}),
        "Northwind Labs\nEngineer\n10/2021 - Present",
        "",
    )

    employment = result["employments"][0]
    assert employment["start_date_display"] == "2021-10"
    assert employment["is_current"] is True


def test_image_only_pdf_without_ocr_date_preserves_unknown_instead_of_model_inference() -> None:
    result = reconcile_pdf_employment_dates(
        _employment_payload(
            {
                "company_name": "Northwind Labs",
                "role_title": "Engineer",
                "start_date": "2020-01-01",
                "start_date_display": "2020-01-01",
                "start_date_precision": "day",
            }
        ),
        "Northwind Labs\nEngineer\nBuilt systems.",
        "",
    )

    employment = result["employments"][0]
    assert employment["start_date"] is None
    assert employment["start_date_display"] is None
    assert employment["start_date_precision"] is None


def test_conflicting_textract_and_embedded_dates_remain_unknown() -> None:
    result = reconcile_pdf_employment_dates(
        _employment_payload({"company_name": "Northwind Labs", "role_title": "Engineer"}),
        "Northwind Labs\nEngineer\nSep 2021 - Present",
        "Northwind Labs\nEngineer\nOct 2021 - Present",
    )

    employment = result["employments"][0]
    assert employment["start_date"] is None
    assert employment["start_date_display"] is None
    assert employment["start_date_precision"] is None
    assert "conflicting_start_date_pdf_evidence" in employment["warnings"]
    assert employment["is_current"] is True


def test_multiple_employment_dates_attach_to_their_unique_claims() -> None:
    payload = _employment_payload(
        {"company_name": "Northwind Labs", "role_title": "Engineer"},
        {"company_name": "Contoso Systems", "role_title": "Developer"},
    )
    text = (
        "EXPERIENCE\n"
        "Northwind Labs\nEngineer\nJan 2022 - Present\n"
        "Contoso Systems\nDeveloper\nMar 2019 - Dec 2021"
    )
    result = reconcile_pdf_employment_dates(payload, text, text)

    current, historical = result["employments"]
    assert current["start_date_display"] == "2022-01"
    assert current["end_date_display"] == "Present"
    assert current["is_current"] is True
    assert historical["start_date_display"] == "2019-03"
    assert historical["end_date_display"] == "2021-12"
    assert historical.get("is_current") is not True


def test_redacted_quality_fixture_preserves_source_truth_field_by_field() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/resume_extraction_quality.json").read_text()
    )
    normalized = normalize_extracted_payload(fixture["model_payload"], fixture["text"])
    result = reconcile_pdf_employment_dates(normalized, fixture["text"], fixture["text"])

    assert [item["name"] for item in result["skills"]] == fixture["expected"]["skills"]
    assert [
        [item["start_date_display"], item["end_date_display"]]
        for item in result["employments"]
    ] == fixture["expected"]["employment_dates"]
    assert all(item["start_date_precision"] == "month" for item in result["employments"])
    assert all(item["end_date_precision"] == "month" for item in result["employments"])
    assert len(result["education"]) == fixture["expected"]["education_count"]
    candidacy = result["certifications"][0]
    assert candidacy["title"] == fixture["expected"]["candidacy_title"]
    assert candidacy["issuing_organization"] is None
    assert candidacy["issued_date"] is None
    assert candidacy["selected_for_import"] is False
    assert "professional_candidacy_not_earned" in candidacy["warnings"]
    assert "professional_candidacy_requires_review" in candidacy["warnings"]
    ParsedResumeResult.model_validate(result)


def test_actual_layout_regression_keeps_source_blocks_when_model_order_is_wrong() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/resume_source_association_quality.json").read_text()
    )
    normalized = normalize_extracted_payload(fixture["model_payload"], fixture["text"])
    result = reconcile_pdf_source_associations(normalized, fixture["text"], fixture["text"])

    employment_by_company = {
        item["company_name"]: [
            item["start_date_display"],
            item["end_date_display"],
            item["is_current"],
        ]
        for item in result["employments"]
    }
    assert employment_by_company == fixture["expected"]["employment_by_company"]
    assert {
        item["degree"]: item["institution_name"] for item in result["education"]
    } == fixture["expected"]["education_by_degree"]
    candidacy = next(
        item
        for item in result["certifications"]
        if item["title"] == fixture["expected"]["candidacy_title"]
    )
    assert candidacy["issued_date"] is None
    assert candidacy["selected_for_import"] is False
    assert "professional_candidacy_not_earned" in candidacy["warnings"]


def test_observed_replay_layout_preserves_date_and_model_source_pairs() -> None:
    fixture = json.loads(
        (
            Path(__file__).parent
            / "fixtures/resume_source_association_observed_failure.json"
        ).read_text()
    )
    normalized = normalize_extracted_payload(fixture["model_payload"], fixture["text"])
    result = reconcile_pdf_source_associations(normalized, fixture["text"], fixture["text"])

    employment_a = next(
        item for item in result["employments"] if item["company_name"] == "Employer Alpha"
    )
    assert [
        employment_a["start_date_display"],
        employment_a["end_date_display"],
        employment_a["is_current"],
    ] == fixture["expected"]["employment_a_dates"]
    assert "employment_source_association_uncertain" not in employment_a["warnings"]

    assert {
        item["degree"]: item["institution_name"] for item in result["education"]
    } == fixture["expected"]["education_by_degree"]
    assert all(
        "education_model_pair_preserved_from_source_reference" in item["warnings"]
        for item in result["education"]
    )
    assert [item["name"] for item in result["skills"]] == [
        "Explicit Skill One",
        "Explicit Skill Two",
    ]
    candidacy = result["certifications"][0]
    assert candidacy["selected_for_import"] is False
    assert "professional_candidacy_not_earned" in candidacy["warnings"]


def test_observed_two_of_three_education_is_recovered_as_held_source_claim() -> None:
    fixture = json.loads(
        (
            Path(__file__).parent
            / "fixtures/resume_education_observed_two_of_three.json"
        ).read_text()
    )
    normalized = normalize_extracted_payload(fixture["model_payload"], fixture["text"])
    assert len(normalized["education"]) == 2

    result = reconcile_pdf_source_associations(normalized, fixture["text"], fixture["text"])

    assert {
        item["degree"]: item["institution_name"] for item in result["education"]
    } == fixture["expected"]["education_by_degree"]
    recovered = next(
        item
        for item in result["education"]
        if item["degree"] == fixture["expected"]["recovered_degree"]
    )
    assert recovered["selected_for_import"] is False
    assert "education_recovered_from_source_block" in recovered["warnings"]
    assert "education_source_model_omission" in recovered["warnings"]
    assert "education_source_association_uncertain" in recovered["warnings"]
    ParsedResumeResult.model_validate(result)


def test_education_recovery_does_not_fabricate_unpaired_source_text() -> None:
    result = reconcile_pdf_education_blocks(
        {"education": []},
        "EDUCATION\nLearning programme\nInstitute Alpha\nProfessional Level 1 Candidate",
        "",
    )

    assert result["education"] == []


def test_stage_diagnostics_export_only_redacted_counts_fingerprints_and_reasons() -> None:
    diagnostics = PrivacySafeResumeStageDiagnostics()
    diagnostics.record(
        "model_output",
        {
            "education": [
                {
                    "degree": "Sensitive Degree",
                    "institution_name": "Sensitive Institution",
                }
            ]
        },
    )
    diagnostics.record(
        "import_payload",
        {
            "education": [
                {
                    "degree": "Sensitive Degree",
                    "institution_name": "Sensitive Institution",
                    "warnings": ["education_source_association_uncertain", "private prose"],
                }
            ]
        },
    )

    exported = diagnostics.export()
    serialized = json.dumps(exported)
    assert exported["stages"][0]["counts"]["education"] == 1
    assert "education_source_association_uncertain" in serialized
    assert "other_warning" in serialized
    assert "Sensitive Degree" not in serialized
    assert "Sensitive Institution" not in serialized
    assert "private prose" not in serialized


def test_lifecycle_diagnostics_link_redacted_fingerprints_to_import_outcomes() -> None:
    diagnostics = PrivacySafeResumeStageDiagnostics()
    diagnostics.record(
        "import_payload",
        {"education": [{"degree": "Sensitive", "institution_name": "Private"}]},
    )
    parser_metadata = {"stage_diagnostics": diagnostics.export()}
    fingerprints = import_payload_fingerprints(parser_metadata)

    updated = append_lifecycle_diagnostic_stage(
        parser_metadata,
        "import",
        [
            {
                "source_claim_id": "a" * 64,
                "fingerprint": fingerprints["education"][0],
                "category": "education",
                "outcome": "skipped",
                "reasons": ["unusable_record", "Education at Private Institute"],
            }
        ],
    )

    serialized = json.dumps(updated)
    lifecycle = updated["stage_diagnostics"]["lifecycle_stages"][0]
    assert lifecycle["counts"] == {"skipped": 1}
    assert lifecycle["items"][0]["reasons"] == ["other_reason", "unusable_record"]
    assert lifecycle["items"][0]["fingerprint"] == fingerprints["education"][0]
    assert "Sensitive" not in serialized
    assert "Private Institute" not in serialized


def test_lifecycle_diagnostics_reject_non_opaque_fingerprints_and_labels() -> None:
    updated = append_lifecycle_diagnostic_stage(
        {"stage_diagnostics": {}},
        "review",
        [
            {
                "source_claim_id": "b" * 64,
                "fingerprint": "raw institution name",
                "category": "education/private",
                "outcome": "held because of private text",
                "reasons": [],
            }
        ],
    )

    item = updated["stage_diagnostics"]["lifecycle_stages"][0]["items"][0]
    assert item["fingerprint"] == "unavailable"
    assert item["category"] == "other_category"
    assert item["outcome"] == "other_outcome"


def test_conflicting_positional_education_recovery_is_held_not_reassigned() -> None:
    payload = {
        "education": [
            {
                "degree": "Qualification One",
                "institution_name": "Institute Alpha",
                "source_text_reference": "Qualification One",
            }
        ]
    }
    primary = "EDUCATION\nQualification One\nInstitute Beta - 2021\nInstitute Alpha"
    supplemental = "EDUCATION\nQualification One\nInstitute Gamma - 2021\nInstitute Alpha"

    result = reconcile_pdf_education_blocks(payload, primary, supplemental)

    education = result["education"][0]
    assert education["institution_name"] is None
    assert "education_source_association_uncertain" in education["warnings"]


def test_repeated_role_title_never_overrides_missing_employer_anchor() -> None:
    payload = _employment_payload(
        {
            "company_name": "Unsupported Employer",
            "role_title": "Investor Relations Associate",
            "start_date": "2024-01",
            "is_current": True,
        },
        {
            "company_name": "Employer Beta",
            "role_title": "Investor Relations Associate",
        },
    )
    text = (
        "EXPERIENCE\n"
        "Jan 2025 - Jun 2025Employer Alpha | Investor Relations Associate\n"
        "Apr 2023 - Jan 2024Employer Beta | Investor Relations Associate"
    )

    result = reconcile_pdf_employment_dates(payload, text, text)

    unsupported, grounded = result["employments"]
    assert unsupported["start_date_display"] is None
    assert unsupported["end_date_display"] is None
    assert unsupported["is_current"] is None
    assert "employment_source_association_uncertain" in unsupported["warnings"]
    assert grounded["start_date_display"] == "2023-04"
    assert grounded["end_date_display"] == "2024-01"
    assert grounded["is_current"] is False


def test_lost_end_date_never_turns_a_historical_role_into_current() -> None:
    payload = _employment_payload(
        {
            "company_name": "Employer Alpha",
            "role_title": "Analyst",
            "start_date": "2022-01",
            "is_current": True,
        }
    )

    result = reconcile_pdf_employment_dates(
        payload,
        "EXPERIENCE\nEmployer Alpha | Analyst\nJan 2022",
        "",
    )

    employment = result["employments"][0]
    assert employment["start_date_display"] is None
    assert employment["end_date_display"] is None
    assert employment["is_current"] is None
    assert "employment_source_association_uncertain" in employment["warnings"]


def test_conflicting_education_blocks_are_held_instead_of_cross_assigned() -> None:
    payload = {
        "education": [
            {
                "degree": "Bachelor of Science",
                "institution_name": "Model Institution",
            }
        ]
    }

    result = reconcile_pdf_education_blocks(
        payload,
        "EDUCATION\nBachelor of Science\nInstitute Alpha - 2021",
        "EDUCATION\nBachelor of Science\nInstitute Beta - 2021",
    )

    education = result["education"][0]
    assert education["institution_name"] is None
    assert "education_source_association_uncertain" in education["warnings"]
    assert "conflicting_education_source_blocks" in education["warnings"]


def test_split_source_candidacy_is_recovered_as_non_earned_attention_item() -> None:
    result = normalize_extracted_payload(
        {"education": [], "certifications": []},
        "EDUCATION\nCFA Level 1\nCandidate",
    )

    assert len(result["certifications"]) == 1
    candidacy = result["certifications"][0]
    assert candidacy["title"] == "CFA Level 1 Candidate"
    assert candidacy["issued_date"] is None
    assert candidacy["selected_for_import"] is False
    assert "professional_candidacy_not_earned" in candidacy["warnings"]


def test_split_source_candidacy_displaces_model_education_claim() -> None:
    result = normalize_extracted_payload(
        {
            "education": [
                {
                    "degree": "CFA Level 1 Candidate",
                    "institution_name": "Professional Body",
                    "confidence": 0.95,
                }
            ],
            "certifications": [],
        },
        "EDUCATION\nCFA Level 1\nCandidate",
    )

    assert result["education"] == []
    candidacy = result["certifications"][0]
    assert candidacy["title"] == "CFA Level 1 Candidate"
    assert candidacy["issued_date"] is None
    assert candidacy["selected_for_import"] is False
    assert "professional_candidacy_not_earned" in candidacy["warnings"]


def test_order_recovery_stops_when_source_sequence_is_not_complete() -> None:
    payload = _employment_payload(
        {"company_name": "Ungrounded A", "role_title": "Associate"},
        {"company_name": "Northwind Labs", "role_title": "Engineer"},
    )
    text = "EXPERIENCE\nNorthwind Labs\nEngineer\nJan 2022 - Present"

    result = reconcile_pdf_employment_dates(payload, text, text)

    assert result["employments"][0]["start_date_display"] is None
    assert result["employments"][1]["start_date_display"] == "2022-01"


def test_candidacy_with_earned_wording_remains_an_earned_claim() -> None:
    payload = {
        "certifications": [
            {
                "title": "Qualified Financial Analyst",
                "issued_date": "2024-01-01",
                "confidence": 0.96,
            }
        ]
    }
    result = normalize_extracted_payload(payload, "CERTIFICATIONS\nQualified Financial Analyst")

    assert result["certifications"][0]["issued_date"] == "2024-01-01"
    assert "professional_candidacy_not_earned" not in result["certifications"][0]["warnings"]
