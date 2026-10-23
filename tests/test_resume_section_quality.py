import copy
import json
from pathlib import Path

import pytest

from app.resumes.extraction import normalize_extracted_payload
from app.resumes.providers import TextractDocumentExtractor
from app.resumes.schemas import ParsedResumeResult
from app.resumes.skill_sections import grounded_section, section_lines
from app.services.resume_review_service import ResumeReviewService

FIXTURE = json.loads((Path(__file__).parent / "fixtures/resume_section_quality.json").read_text())


def test_real_cv_structure_rejects_leakage_and_preserves_other_claims():
    payload = {
        "employments": [{"company_name": f"Synthetic Company {i}"} for i in range(4)],
        "education": [{"institution_name": "Synthetic College"}],
        "certifications": [{"name": "Synthetic Certificate"}],
        "projects": [{"name": "Synthetic Dashboard"}],
        "skills": [
            {"name": name, "confidence": 0.99} for name in FIXTURE["junk"] + ["SQL", "Python"]
        ],
    }
    original = copy.deepcopy(payload)
    result = normalize_extracted_payload(payload, FIXTURE["text"])
    assert {s["name"] for s in result["skills"]} == set(FIXTURE["explicit"] + ["SQL", "Python"])
    assert {s["source_section"] for s in result["skills"]} == {"skills", "experience", "summary"}
    for kind in ("employments", "education", "certifications", "projects"):
        assert len(result[kind]) == len(original[kind])
        for before, after in zip(original[kind], result[kind], strict=True):
            assert all(after[key] == value for key, value in before.items())
    ParsedResumeResult.model_validate(result)


@pytest.mark.parametrize(
    "heading",
    [
        "PROFESSIONAL EXPERIENCE",
        "Work Experience",
        "Employment History",
        "EDUCATION",
        "Personal Information",
        "EDUCATION PERSONAL INFORMATION",
    ],
)
def test_explicit_list_does_not_spill_at_section_boundary(heading):
    result = normalize_extracted_payload(
        {}, f"CORE COMPETENCIES\nSQL\n\nPython\n{heading}\nA company in a region"
    )
    assert [s["name"] for s in result["skills"]] == ["SQL", "Python"]


@pytest.mark.parametrize("name", ["SQL", "Python", "C++", "C#", ".NET", "Financial Modeling"])
def test_recognized_source_grounded_inference_without_explicit_section(name):
    result = normalize_extracted_payload(
        {"skills": [{"name": name, "confidence": 0.95, "source_section": "skills"}]},
        f"WORK EXPERIENCE\nUsed {name} to build a synthetic project.",
    )
    assert len(result["skills"]) == 1
    assert result["skills"][0]["source_section"] == "experience"


@pytest.mark.parametrize("confidence", [None, 0.2, 0.79, True, 1.1])
def test_inference_requires_high_confidence(confidence):
    result = normalize_extracted_payload(
        {"skills": [{"name": "SQL", "confidence": confidence}]}, "EXPERIENCE\nUsed SQL."
    )
    assert result["skills"] == []


def test_source_evidence_not_model_attribution_controls_inference():
    result = normalize_extracted_payload(
        {
            "skills": [
                {
                    "name": "Python",
                    "confidence": 0.99,
                    "source_section": "skills",
                    "source_text_reference": "Python",
                }
            ]
        },
        "EXPERIENCE\nUsed spreadsheets.",
    )
    assert result["skills"] == []
    assert grounded_section("SQL", section_lines("Used NoSQL")) is None
    assert grounded_section("C", section_lines("Used C++")) is None


def test_ocr_words_on_one_line_are_ordered_horizontally_not_by_glyph_top():
    words = []
    for index, (text, left, top, width) in enumerate(
        [
            ("Financial", 0.1, 0.2000, 0.08),
            ("Analysis", 0.19, 0.2003, 0.07),
            ("&", 0.27, 0.2001, 0.01),
            ("Reporting", 0.29, 0.2002, 0.08),
        ]
    ):
        words.append(
            {
                "BlockType": "WORD",
                "Id": str(index),
                "Text": text,
                "Geometry": {"BoundingBox": {"Top": top, "Left": left, "Width": width}},
            }
        )
    blocks = [
        {"BlockType": "LINE", "Text": "SKILLS", "Geometry": {"BoundingBox": {"Top": 0.1}}},
        {
            "BlockType": "LINE",
            "Text": "Financial Analysis & Reporting",
            "Geometry": {"BoundingBox": {"Top": 0.2}},
            "Relationships": [{"Type": "CHILD", "Ids": [w["Id"] for w in words]}],
        },
        *words,
    ]
    assert (
        TextractDocumentExtractor._lines({"Blocks": blocks})
        == "SKILLS\nFinancial Analysis & Reporting"
    )


def test_source_section_is_retained_in_result_but_not_imported_as_career_field():
    result = ParsedResumeResult.model_validate(normalize_extracted_payload({}, "SKILLS\nSQL"))
    raw = result.skills[0].model_dump(mode="json")
    assert raw["source_section"] == "skills"
    assert "source_section" not in ResumeReviewService._review_payload("skill", raw)
