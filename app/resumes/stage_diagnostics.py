from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from collections import Counter
from typing import Any

CATEGORY_KEYS = (
    "employments",
    "education",
    "internships",
    "freelance",
    "gig_platforms",
    "certifications",
    "projects",
    "skills",
    "portfolio_links",
)

SAFE_REASON_CODES = {
    "conflicting_education_source_blocks",
    "education_model_pair_preserved_from_source_reference",
    "education_recovered_from_source_block",
    "education_source_association_uncertain",
    "education_source_model_omission",
    "employment_source_association_uncertain",
    "professional_candidacy_not_earned",
    "professional_candidacy_reclassified_for_review",
    "professional_candidacy_requires_review",
}

CLAIM_CATEGORY_KEYS = {
    "employment": "employments",
    "education": "education",
    "internship": "internships",
    "freelance": "freelance",
    "gig_platform": "gig_platforms",
    "certification": "certifications",
    "project": "projects",
    "skill": "skills",
    "portfolio": "portfolio_links",
}

SAFE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{20}$")


def _safe_code(value: Any, fallback: str) -> str:
    if isinstance(value, str) and SAFE_CODE_PATTERN.fullmatch(value):
        return value
    return fallback


def import_payload_fingerprints(parser_metadata: dict[str, Any]) -> dict[str, list[str]]:
    diagnostics = parser_metadata.get("stage_diagnostics") or {}
    stages = diagnostics.get("stages") or []
    final_stage = next(
        (stage for stage in reversed(stages) if stage.get("stage") == "import_payload"),
        None,
    )
    if not isinstance(final_stage, dict):
        return {}
    items = final_stage.get("items") or {}
    return {
        claim_type: [
            str(item.get("fingerprint"))
            for item in items.get(category, [])
            if isinstance(item, dict) and item.get("fingerprint")
        ]
        for claim_type, category in CLAIM_CATEGORY_KEYS.items()
    }


def append_lifecycle_diagnostic_stage(
    parser_metadata: dict[str, Any],
    stage: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return copied metadata with a PII-free review/import lifecycle stage."""
    metadata = dict(parser_metadata)
    diagnostics = dict(metadata.get("stage_diagnostics") or {})
    lifecycle = list(diagnostics.get("lifecycle_stages") or [])
    safe_items: list[dict[str, Any]] = []
    for item in items:
        raw_reasons = item.get("reasons") or []
        reasons = sorted({_safe_code(reason, "other_reason") for reason in raw_reasons})
        fingerprint = str(item.get("fingerprint") or "")
        safe_items.append(
            {
                "source_claim_id": str(item["source_claim_id"]),
                "fingerprint": (
                    fingerprint if FINGERPRINT_PATTERN.fullmatch(fingerprint) else "unavailable"
                ),
                "category": _safe_code(item.get("category"), "other_category"),
                "outcome": _safe_code(item.get("outcome"), "other_outcome"),
                "reasons": reasons or ["none"],
            }
        )
    lifecycle.append(
        {
            "stage": stage,
            "counts": dict(sorted(Counter(item["outcome"] for item in safe_items).items())),
            "items": safe_items,
        }
    )
    diagnostics["lifecycle_stages"] = lifecycle
    metadata["stage_diagnostics"] = diagnostics
    return metadata


class PrivacySafeResumeStageDiagnostics:
    """Compare one parse in memory and export only redacted, run-local evidence."""

    def __init__(self) -> None:
        self._key = secrets.token_bytes(32)
        self._stages: list[dict[str, Any]] = []

    def record(self, stage: str, payload: dict[str, Any]) -> None:
        categories: dict[str, list[dict[str, str]]] = {}
        for category in CATEGORY_KEYS:
            values = payload.get(category) or []
            if not isinstance(values, list):
                values = []
            categories[category] = [self._redacted_item(category, value) for value in values]
        self._stages.append(
            {
                "stage": stage,
                "counts": {key: len(values) for key, values in categories.items()},
                "items": categories,
            }
        )

    def export(self) -> dict[str, Any]:
        transitions = [
            self._transition(before, after)
            for before, after in zip(self._stages, self._stages[1:], strict=False)
        ]
        return {
            "schema_version": "resume-stage-diagnostics-v1",
            "privacy": "run_local_hmac_no_raw_values",
            "stages": self._stages,
            "transitions": transitions,
        }

    def _redacted_item(self, category: str, value: Any) -> dict[str, str]:
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        fingerprint = hmac.new(self._key, canonical.encode(), hashlib.sha256).hexdigest()[:20]
        warnings = value.get("warnings", []) if isinstance(value, dict) else []
        reason_codes = sorted(
            {
                warning if warning in SAFE_REASON_CODES else "other_warning"
                for warning in warnings
                if isinstance(warning, str) and warning
            }
        )
        disposition = (
            "held"
            if any(
                warning
                in {
                    "education_recovered_from_source_block",
                    "education_source_model_omission",
                    "education_source_association_uncertain",
                    "employment_source_association_uncertain",
                    "professional_candidacy_not_earned",
                    "professional_candidacy_requires_review",
                }
                for warning in reason_codes
            )
            else "available"
        )
        return {
            "fingerprint": fingerprint,
            "disposition": disposition,
            "reason": ",".join(reason_codes) if reason_codes else "none",
        }

    @staticmethod
    def _transition(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        outcomes: Counter[str] = Counter()
        changes: list[dict[str, str]] = []
        for category in CATEGORY_KEYS:
            previous = {item["fingerprint"]: item for item in before["items"][category]}
            current = {item["fingerprint"]: item for item in after["items"][category]}
            for fingerprint in sorted(previous.keys() - current.keys()):
                outcomes["removed_or_transformed"] += 1
                changes.append(
                    {
                        "category": category,
                        "fingerprint": fingerprint,
                        "outcome": "removed_or_transformed",
                        "reason": f"not_present_after_{after['stage']}",
                    }
                )
            for fingerprint in sorted(current.keys() - previous.keys()):
                item = current[fingerprint]
                outcome = "held" if item["disposition"] == "held" else "added_or_transformed"
                outcomes[outcome] += 1
                changes.append(
                    {
                        "category": category,
                        "fingerprint": fingerprint,
                        "outcome": outcome,
                        "reason": (
                            item["reason"]
                            if item["reason"] != "none"
                            else f"introduced_by_{after['stage']}"
                        ),
                    }
                )
        return {
            "from": before["stage"],
            "to": after["stage"],
            "outcomes": dict(sorted(outcomes.items())),
            "changes": changes,
        }
