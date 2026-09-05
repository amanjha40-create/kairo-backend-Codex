from __future__ import annotations

import json
from pathlib import Path

import pytest
from pypdf import PdfReader

from app.resumes.providers import DeterministicDocxExtractor

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "resume_golden"


def load_json(name: str) -> object:
    return json.loads((FIXTURE_ROOT / name).read_text())


def test_golden_corpus_is_synthetic_and_covers_required_layouts() -> None:
    corpus = load_json("corpus.json")
    assert isinstance(corpus, list)
    assert len(corpus) >= 25
    assert all("@gmail.com" not in fixture["text"] for fixture in corpus)
    assert all("@kairoid.com" not in fixture["text"] for fixture in corpus)
    tags = {tag for fixture in corpus for tag in fixture["tags"]}
    assert {
        "standard",
        "two_column",
        "multi_page",
        "narrative",
        "partial_dates",
        "current_role",
        "missing_dates",
        "unusual_headings",
        "format_noise",
        "prompt_injection",
        "privacy",
    } <= tags


def test_generated_document_manifest_matches_corpus() -> None:
    corpus = load_json("corpus.json")
    manifest = load_json("documents/manifest.json")
    assert manifest["synthetic_only"] is True
    assert manifest["fixture_count"] == len(corpus)
    assert manifest["document_count"] == sum(len(fixture["formats"]) for fixture in corpus)
    assert all(
        (FIXTURE_ROOT / "documents" / item["path"]).stat().st_size == item["byte_size"]
        for item in manifest["files"]
    )


@pytest.mark.asyncio
async def test_generated_docx_files_round_trip_to_golden_text() -> None:
    corpus = load_json("corpus.json")
    extractor = DeterministicDocxExtractor()
    for fixture in corpus:
        if "docx" not in fixture["formats"]:
            continue
        path = FIXTURE_ROOT / "documents" / f"{fixture['id']}.docx"
        actual = await extractor.extract(
            path.read_bytes(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        expected = "\n".join(line.strip() for line in fixture["text"].splitlines() if line.strip())
        assert actual == expected


def test_generated_pdfs_are_readable_and_long_fixture_has_three_pages() -> None:
    corpus = load_json("corpus.json")
    for fixture in corpus:
        if "pdf" not in fixture["formats"]:
            continue
        path = FIXTURE_ROOT / "documents" / f"{fixture['id']}.pdf"
        reader = PdfReader(path)
        assert reader.pages
        assert any((page.extract_text() or "").strip() for page in reader.pages)
        if fixture["id"] == "multi_page_long":
            assert len(reader.pages) == 3


def test_postfix_quality_metrics_meet_7g_thresholds() -> None:
    metrics = load_json("postfix_metrics.json")
    records = metrics["record_metrics"]
    overall = metrics["overall"]

    assert records["employments"]["recall_pct"] >= 95
    assert records["education"]["recall_pct"] >= 95
    assert records["certifications"]["recall_pct"] >= 90
    assert records["projects"]["recall_pct"] >= 90
    assert records["skills"]["precision_pct"] >= 95
    assert overall["date_accuracy_pct"] >= 90
    assert overall["hallucination_rate_pct"] <= 1
    assert overall["duplicate_rate_pct"] <= 1
    assert overall["catastrophic_failure_rate_pct"] <= 2
    assert overall["invalid_import_rate_pct"] == 0
    assert overall["banned_value_leaks"] == 0
