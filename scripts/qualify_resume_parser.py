#!/usr/bin/env python3
"""Measure the live resume parser against the synthetic Milestone 7G corpus."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.resumes.extraction import parse_resume_date
from app.resumes.providers import build_resume_parser
from app.resumes.review_validation import required_claim_blockers

COLLECTIONS = (
    "employments",
    "education",
    "internships",
    "freelance",
    "gig_platforms",
    "certifications",
    "projects",
)
IDENTITY_FIELDS = {
    "employments": ("company_name", "role_title"),
    "education": ("institution_name", "degree"),
    "internships": ("company_name", "role"),
    "freelance": ("client_name", "project_title"),
    "gig_platforms": ("platform_name", "partner_role"),
    "certifications": ("title", "issuing_organization"),
    "projects": ("title",),
}
FIELD_MAP = {
    "employments": (
        ("company_name", "company_name"),
        ("role_title", "role_title"),
        ("start", "start"),
        ("end", "end"),
        ("is_current", "is_current"),
    ),
    "education": (
        ("institution_name", "institution_name"),
        ("degree", "degree"),
        ("field_of_study", "field_of_study"),
        ("start", "start"),
        ("end", "end"),
        ("is_current", "is_current"),
    ),
    "internships": (
        ("company_name", "company_name"),
        ("role", "role"),
        ("start", "start"),
        ("end", "end"),
        ("is_current", "is_current"),
    ),
    "freelance": (
        ("client_name", "client_name"),
        ("project_title", "project_title"),
        ("start", "start"),
        ("end", "end"),
        ("is_current", "is_current"),
    ),
    "gig_platforms": (
        ("platform_name", "platform_name"),
        ("partner_role", "partner_role"),
        ("start", "start"),
        ("end", "end"),
        ("is_current", "is_current"),
    ),
    "certifications": (
        ("title", "title"),
        ("issuing_organization", "issuing_organization"),
        ("issued", "issued"),
        ("expiry", "expiry"),
    ),
    "projects": (("title", "title"), ("url", "url")),
}
PROFILE_FIELDS = ("full_name", "email", "phone", "professional_headline")


def normalized(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    return re.sub(r"[^\w]+", " ", text).strip()


def similarity(left: Any, right: Any) -> float:
    a, b = normalized(left), normalized(right)
    if not a or not b:
        return 1.0 if not a and not b else 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(a=a, b=b).ratio()


def canonical_date(claim: dict[str, Any], stem: str) -> str | None:
    if stem == "end" and claim.get("is_current") and not claim.get("end_date"):
        return None
    direct_names = {
        "start": ("start_date", "start_date_display"),
        "end": ("end_date", "end_date_display"),
        "issued": ("issued_date",),
        "expiry": ("expiry_date",),
    }[stem]
    for name in direct_names:
        value = claim.get(name)
        if value:
            parsed, display, _, is_current = parse_resume_date(value)
            if is_current:
                return None
            if parsed is not None:
                return parsed.isoformat()
            if display:
                return display
    return None


def value_matches(expected: Any, actual: Any, *, is_date: bool = False) -> bool:
    if expected is None:
        return actual in (None, "")
    if isinstance(expected, bool):
        return actual is True if expected else actual in (False, None)
    if actual is None:
        return False
    if is_date:
        expected_text, actual_text = str(expected), str(actual)
        return actual_text == expected_text or actual_text.startswith(expected_text)
    return similarity(expected, actual) >= 0.92


def record_similarity(collection: str, expected: dict[str, Any], actual: dict[str, Any]) -> float:
    fields = IDENTITY_FIELDS[collection]
    scores = [
        similarity(expected.get(field), actual.get(field))
        for field in fields
        if expected.get(field) is not None
    ]
    return sum(scores) / len(scores) if scores else 0.0


def match_records(
    collection: str,
    expected: list[dict[str, Any]],
    actual: list[dict[str, Any]],
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    candidates: list[tuple[float, int, int]] = []
    for expected_index, expected_item in enumerate(expected):
        for actual_index, actual_item in enumerate(actual):
            score = record_similarity(collection, expected_item, actual_item)
            if score >= 0.6:
                candidates.append((score, expected_index, actual_index))
    matches: list[tuple[int, int]] = []
    used_expected: set[int] = set()
    used_actual: set[int] = set()
    for _, expected_index, actual_index in sorted(candidates, reverse=True):
        if expected_index in used_expected or actual_index in used_actual:
            continue
        used_expected.add(expected_index)
        used_actual.add(actual_index)
        matches.append((expected_index, actual_index))
    return (
        matches,
        [index for index in range(len(expected)) if index not in used_expected],
        [index for index in range(len(actual)) if index not in used_actual],
    )


def duplicate_count(collection: str, records: list[dict[str, Any]]) -> int:
    keys = [
        tuple(normalized(record.get(field)) for field in IDENTITY_FIELDS[collection])
        for record in records
    ]
    counts = Counter(key for key in keys if any(key))
    return sum(count - 1 for count in counts.values() if count > 1)


def importable(collection: str, item: dict[str, Any]) -> bool:
    if collection == "employments":
        return bool(item.get("company_name") and item.get("role_title"))
    if collection == "education":
        return bool(
            item.get("institution_name") and (item.get("degree") or item.get("field_of_study"))
        )
    if collection == "internships":
        return bool(item.get("company_name") or item.get("role"))
    if collection == "freelance":
        return bool(item.get("client_name") or item.get("project_title"))
    if collection == "gig_platforms":
        return bool(item.get("platform_name") or item.get("partner_role"))
    if collection == "certifications":
        return bool(item.get("title") and item.get("issuing_organization"))
    if collection == "projects":
        return bool(item.get("title"))
    return True


def unsafe_import_acceptance(collection: str, item: dict[str, Any]) -> bool:
    claim_type = {
        "employments": "employment",
        "education": "education",
        "internships": "internship",
        "freelance": "freelance",
        "gig_platforms": "gig_platform",
        "certifications": "certification",
        "projects": "project",
    }[collection]
    return not importable(collection, item) and not required_claim_blockers(claim_type, item)


@dataclass
class Totals:
    expected_records: Counter
    predicted_records: Counter
    matched_records: Counter
    hallucinated_records: int = 0
    omitted_records: int = 0
    duplicate_records: int = 0
    predicted_claims: int = 0
    invalid_import_claims: int = 0
    field_total: Counter = None  # type: ignore[assignment]
    field_correct: Counter = None  # type: ignore[assignment]
    banned_leaks: int = 0
    catastrophic_failures: int = 0

    def __post_init__(self) -> None:
        self.field_total = Counter()
        self.field_correct = Counter()


def score_fixture(
    fixture: dict[str, Any],
    parsed: dict[str, Any],
    totals: Totals,
) -> dict[str, Any]:
    expected = fixture["expected"]
    fixture_result: dict[str, Any] = {"id": fixture["id"], "status": "scored", "collections": {}}
    profile = parsed.get("candidate_profile") or {}
    for field in PROFILE_FIELDS:
        if field not in expected.get("profile", {}):
            continue
        totals.field_total[f"profile.{field}"] += 1
        if value_matches(expected["profile"].get(field), profile.get(field)):
            totals.field_correct[f"profile.{field}"] += 1

    for collection in COLLECTIONS:
        expected_records = list(expected.get(collection, []))
        actual_records = list(parsed.get(collection, []))
        matches, omitted, hallucinated = match_records(collection, expected_records, actual_records)
        totals.expected_records[collection] += len(expected_records)
        totals.predicted_records[collection] += len(actual_records)
        totals.matched_records[collection] += len(matches)
        totals.omitted_records += len(omitted)
        totals.hallucinated_records += len(hallucinated)
        totals.duplicate_records += duplicate_count(collection, actual_records)
        totals.predicted_claims += len(actual_records)
        totals.invalid_import_claims += sum(
            unsafe_import_acceptance(collection, item) for item in actual_records
        )
        fixture_result["collections"][collection] = {
            "expected": len(expected_records),
            "predicted": len(actual_records),
            "matched": len(matches),
            "omitted": len(omitted),
            "hallucinated": len(hallucinated),
        }
        for expected_index, actual_index in matches:
            expected_item = expected_records[expected_index]
            actual_item = actual_records[actual_index]
            for expected_field, actual_field in FIELD_MAP[collection]:
                if expected_field not in expected_item:
                    continue
                metric = f"{collection}.{expected_field}"
                actual_value = (
                    canonical_date(actual_item, actual_field)
                    if actual_field in {"start", "end", "issued", "expiry"}
                    else actual_item.get(actual_field)
                )
                totals.field_total[metric] += 1
                if value_matches(
                    expected_item.get(expected_field),
                    actual_value,
                    is_date=actual_field in {"start", "end", "issued", "expiry"},
                ):
                    totals.field_correct[metric] += 1

    expected_skills = list(expected.get("skills", []))
    actual_skills = [
        item.get("name")
        for item in parsed.get("skills", [])
        if isinstance(item, dict) and item.get("name")
    ]
    expected_skill_keys = {normalized(item) for item in expected_skills}
    actual_skill_keys = [normalized(item) for item in actual_skills]
    matched_skills = sum(item in expected_skill_keys for item in set(actual_skill_keys))
    totals.expected_records["skills"] += len(expected_skill_keys)
    totals.predicted_records["skills"] += len(actual_skill_keys)
    totals.matched_records["skills"] += matched_skills
    totals.omitted_records += max(0, len(expected_skill_keys) - matched_skills)
    totals.hallucinated_records += sum(
        item not in expected_skill_keys for item in actual_skill_keys
    )
    totals.duplicate_records += len(actual_skill_keys) - len(set(actual_skill_keys))
    totals.predicted_claims += len(actual_skill_keys)
    totals.invalid_import_claims += sum(not item for item in actual_skill_keys)
    fixture_result["collections"]["skills"] = {
        "expected": len(expected_skill_keys),
        "predicted": len(actual_skill_keys),
        "matched": matched_skills,
        "omitted": max(0, len(expected_skill_keys) - matched_skills),
        "hallucinated": sum(item not in expected_skill_keys for item in actual_skill_keys),
    }

    protected_values: list[Any] = []
    protected_values.extend(profile.get(field) for field in PROFILE_FIELDS)
    for collection in COLLECTIONS:
        for item in parsed.get(collection, []):
            protected_values.extend(item.get(field) for field in IDENTITY_FIELDS[collection])
            if collection == "projects":
                protected_values.append(item.get("url"))
    protected_values.extend(actual_skills)
    serialized = json.dumps(protected_values, ensure_ascii=False).casefold()
    leaked = [
        value
        for value in expected.get("must_not_contain", [])
        if str(value).casefold() in serialized
    ]
    fixture_result["banned_value_leaks"] = len(leaked)
    totals.banned_leaks += len(leaked)
    return fixture_result


def percentage(numerator: int, denominator: int) -> float:
    return round(100.0 * numerator / denominator, 2) if denominator else 100.0


def build_report(
    fixtures: list[dict[str, Any]],
    totals: Totals,
    fixture_results: list[dict[str, Any]],
    *,
    provider: str,
    model_id: str,
) -> dict[str, Any]:
    all_collections = (*COLLECTIONS, "skills")
    record_metrics = {}
    for collection in all_collections:
        expected = totals.expected_records[collection]
        predicted = totals.predicted_records[collection]
        matched = totals.matched_records[collection]
        record_metrics[collection] = {
            "expected": expected,
            "predicted": predicted,
            "matched": matched,
            "recall_pct": percentage(matched, expected),
            "precision_pct": percentage(matched, predicted),
        }
    fields = {
        name: {
            "correct": totals.field_correct[name],
            "total": count,
            "accuracy_pct": percentage(totals.field_correct[name], count),
        }
        for name, count in sorted(totals.field_total.items())
    }
    expected_total = sum(totals.expected_records.values())
    predicted_total = sum(totals.predicted_records.values())
    matched_total = sum(totals.matched_records.values())
    date_keys = [
        key for key in fields if key.rsplit(".", 1)[-1] in {"start", "end", "issued", "expiry"}
    ]
    date_correct = sum(totals.field_correct[key] for key in date_keys)
    date_total = sum(totals.field_total[key] for key in date_keys)
    return {
        "corpus": {
            "fixture_count": len(fixtures),
            "synthetic_only": True,
            "formats_declared": sorted({fmt for fixture in fixtures for fmt in fixture["formats"]}),
        },
        "runtime": {"provider": provider, "model_id": model_id},
        "record_metrics": record_metrics,
        "overall": {
            "record_recall_pct": percentage(matched_total, expected_total),
            "record_precision_pct": percentage(matched_total, predicted_total),
            "date_accuracy_pct": percentage(date_correct, date_total),
            "hallucination_rate_pct": percentage(totals.hallucinated_records, predicted_total),
            "duplicate_rate_pct": percentage(totals.duplicate_records, predicted_total),
            "omission_rate_pct": percentage(totals.omitted_records, expected_total),
            "invalid_import_rate_pct": percentage(
                totals.invalid_import_claims, totals.predicted_claims
            ),
            "catastrophic_failure_rate_pct": percentage(
                totals.catastrophic_failures, len(fixtures)
            ),
            "banned_value_leaks": totals.banned_leaks,
        },
        "field_metrics": fields,
        "fixture_results": fixture_results,
    }


async def run(args: argparse.Namespace) -> int:
    fixtures = json.loads(args.corpus.read_text())
    if args.fixture_id:
        selected = set(args.fixture_id)
        fixtures = [fixture for fixture in fixtures if fixture["id"] in selected]
    existing_outputs = json.loads(args.reuse_raw.read_text()) if args.reuse_raw else {}
    parser = None
    if not args.reuse_raw:
        settings = SimpleNamespace(
            aws_region=args.region,
            bedrock_model_id=args.model_id,
            resume_parser_provider=args.provider,
            bedrock_timeout_seconds=args.timeout,
        )
        parser = build_resume_parser(settings)
    totals = Totals(Counter(), Counter(), Counter())
    fixture_results: list[dict[str, Any]] = []
    raw_outputs: dict[str, Any] = {}
    for index, fixture in enumerate(fixtures, 1):
        print(
            json.dumps({"fixture": fixture["id"], "position": index, "total": len(fixtures)}),
            flush=True,
        )
        try:
            if args.reuse_raw:
                payload = existing_outputs[fixture["id"]]
            else:
                assert parser is not None
                parsed = await parser.parse(fixture["text"])
                payload = parsed.model_dump(mode="json")
            raw_outputs[fixture["id"]] = payload
            fixture_results.append(score_fixture(fixture, payload, totals))
        except Exception as exc:
            totals.catastrophic_failures += 1
            fixture_results.append(
                {
                    "id": fixture["id"],
                    "status": "catastrophic_failure",
                    "error_type": type(exc).__name__,
                    "error_detail": str(exc),
                }
            )
    report = build_report(
        fixtures,
        totals,
        fixture_results,
        provider=args.provider,
        model_id=args.model_id,
    )
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if args.raw_output:
        args.raw_output.write_text(json.dumps(raw_outputs, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"complete": True, **report["overall"]}, sort_keys=True), flush=True)
    return 0 if math.isclose(report["overall"]["catastrophic_failure_rate_pct"], 0.0) else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-output", type=Path)
    parser.add_argument("--reuse-raw", type=Path)
    parser.add_argument("--provider", choices=("nova", "anthropic"), default="nova")
    parser.add_argument("--model-id", default="us.amazon.nova-2-lite-v1:0")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--fixture-id", action="append")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
