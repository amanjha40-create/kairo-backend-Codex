from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.models.resume_review_item import ResumeReviewItem
from app.resumes.extraction import normalize_extracted_payload
from app.resumes.schemas import ParsedResumeResult
from app.resumes.skill_quality import confident_for_selection, skill_key, skill_rejection_reason
from app.services.resume_duplicate_service import DuplicateAssessment, ResumeDuplicateService
from app.services.resume_review_service import ResumeReviewService

FIXTURE = json.loads((Path(__file__).parent / "fixtures/resume_skill_quality.json").read_text())


def normalized():
    return normalize_extracted_payload(copy.deepcopy(FIXTURE["payload"]), FIXTURE["text"])


def test_sanitized_over_extraction_reduces_claim_count_without_losing_core_claims():
    result = normalized()
    skills = result["skills"]
    assert len(FIXTURE["payload"]["skills"]) == 18
    assert len(skills) == 7
    assert [item["name"] for item in skills] == [
        "Financial Modeling",
        "Portfolio Management",
        "Data Analysis",
        "C++",
        "C#",
        ".NET",
        "Node.js",
    ]
    for kind in ("employments", "education", "certifications", "projects"):
        assert len(result[kind]) == len(FIXTURE["payload"][kind])
        for original, actual in zip(FIXTURE["payload"][kind], result[kind], strict=True):
            for key, value in original.items():
                assert actual[key] == value
    assert sum(len(result[k]) for k in FIXTURE["payload"]) == 13
    ParsedResumeResult.model_validate(result)


@pytest.mark.parametrize(
    "name",
    [
        "and regional inputs",
        "or additional duties",
        "revenue updates every Monday",
        "weekly reports",
        "Worked with customers",
        "Improved retention by 12%",
        "We managed the regional office",
        "Provided client updates",
    ],
)
def test_obvious_prose_rejected_even_if_high_confidence_or_in_skills_section(name):
    assert skill_rejection_reason(name, explicitly_listed=True)
    result = normalize_extracted_payload(
        {"skills": [{"name": name, "confidence": 0.99}]}, f"SKILLS\n{name}"
    )
    assert result["skills"] == []


@pytest.mark.parametrize(
    "name",
    [
        "Financial Modeling",
        "Portfolio Management",
        "Data Analysis",
        "Research and Development",
        "Real-time Distributed Systems Design and Implementation",
        "Daily Living Skills",
        "Managed Services",
        "C",
        "C++",
        "C#",
        ".NET",
        "Node.js",
        "CI/CD",
        "ISO 27001",
    ],
)
def test_genuine_skill_concepts_have_no_length_or_vocabulary_gate(name):
    assert skill_rejection_reason(name, explicitly_listed=False) is None


def test_normalization_is_conservative_and_idempotent():
    assert skill_key(" Data–Analysis! ") == skill_key("data analysis.")
    assert skill_key("Research & Development") == skill_key("research and development")
    assert len({skill_key(n) for n in ["C", "C++", "C#", ".NET", "NET", "Node.js", "Nodejs"]}) == 7
    assert skill_key("Data Analysis") != skill_key("Data Engineering")
    assert skill_key(skill_key("Financial-Modeling!")) == skill_key("Financial-Modeling!")


def test_narrative_skill_list_stops_before_following_sentence():
    result = normalize_extracted_payload({}, "Skills: Python, SQL. I worked with regional teams.")
    assert [s["name"] for s in result["skills"]] == ["Python", "SQL"]


def test_ambiguous_metric_is_not_inferred_from_experience():
    assert skill_rejection_reason("transaction volume", explicitly_listed=False) == "context_metric"
    assert skill_rejection_reason("transaction volume", explicitly_listed=True) is None


def test_explicit_list_keeps_dotnet_and_long_skill_without_word_count_cutoff():
    result = normalize_extracted_payload(
        {},
        "Skills: .NET; C++; C#; Node.js; Real-time Distributed Systems Design and Implementation",
    )
    assert [s["name"] for s in result["skills"]] == [
        ".NET",
        "C++",
        "C#",
        "Node.js",
        "Real-time Distributed Systems Design and Implementation",
    ]


@pytest.mark.parametrize(
    ("confidence", "selected"),
    [
        (None, False),
        (0, False),
        (0.79, False),
        (0.80, True),
        (0.95, True),
        (1.0, True),
        (1.1, False),
        (float("nan"), False),
        (True, False),
        ("0.9", False),
    ],
)
def test_confidence_boundary(confidence, selected):
    assert confident_for_selection(confidence) is selected


@pytest.mark.asyncio
@pytest.mark.parametrize("duplicate_status", ["no_match", "exact_match"])
async def test_real_review_creation_preserves_uncertain_claims_but_does_not_select_them(
    duplicate_status,
):
    parsed = SimpleNamespace(id=uuid4(), schema_version="1", structured_result=normalized())
    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[SimpleNamespace(id=uuid4()), parsed, None]),
        flush=AsyncMock(),
        commit=AsyncMock(),
    )
    captured = []
    session.add = captured.append
    service = ResumeReviewService(session)
    service._owned_resume = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    service._session_response = AsyncMock(side_effect=lambda review: review)
    service.duplicates.assess = AsyncMock(
        return_value=DuplicateAssessment(duplicate_status, [], [])
    )
    await service.create(uuid4(), uuid4())
    items = [item for item in captured if isinstance(item, ResumeReviewItem)]
    assert len(items) == 13
    for item in items:
        expected = confident_for_selection(item.confidence) and (
            duplicate_status == "no_match" or item.claim_type == "employment"
        )
        assert item.selected is expected
        assert item.review_status == ("selected" if expected else "deselected")
    assert sum(item.selected for item in items) == (11 if duplicate_status == "no_match" else 1)
    assert {item.claim_type for item in items if not confident_for_selection(item.confidence)} == {
        "employment",
        "education",
    }


@pytest.mark.asyncio
async def test_existing_skill_dedup_does_not_merge_technology_symbols():
    existing = [SimpleNamespace(id=uuid4(), name=name) for name in ["C++", "C#", "Data Analysis"]]
    session = SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: existing)))
    service = ResumeDuplicateService(session)
    assert (await service.assess(uuid4(), "skill", {"name": "C"})).status == "no_match"
    result = await service.assess(uuid4(), "skill", {"name": " data-analysis! "})
    assert result.status == "exact_match"
    assert result.candidates[0]["record_id"] == str(existing[2].id)
