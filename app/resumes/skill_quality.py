"""Conservative, deterministic resume skill quality rules (not a skill allowlist)."""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Any

AUTO_SELECT_CONFIDENCE = 0.80


def normalize_skill_name(value: str) -> str:
    # Keep technology symbols: C++, C#, .NET, Node.js and CI/CD are distinct.
    return (
        " ".join(unicodedata.normalize("NFKC", value).split())
        .strip(' \t\r\n,;|•·:!?"“”')
        .rstrip(".")
    )


def skill_key(value: str) -> str:
    value = normalize_skill_name(value).casefold()
    value = re.sub(r"\s*(?:,|;|\||•|·)\s*", " ", value)
    value = re.sub(r"(?<=\w)[‐‑–—-](?=\w)", " ", value)
    value = re.sub(r"\s+&\s+", " and ", value)
    return " ".join(value.split())


def skill_rejection_reason(name: str, *, explicitly_listed: bool) -> str | None:
    text = name.casefold()
    if not text or not any(character.isalpha() for character in text):
        return "empty_skill"
    if re.match(r"^(?:and|or|but|also|with|which|where|including)\b", text):
        return "conjunction_fragment"
    if re.search(
        r"\b(?:every|each|per)\s+(?:day|week|month|quarter|year|monday|tuesday|"
        r"wednesday|thursday|friday|saturday|sunday)\b|"
        r"\b(?:on a|on an)\s+(?:daily|weekly|monthly|annual)\s+basis\b|"
        r"\b(?:daily|weekly|monthly|quarterly|annually)\s+(?:updates?|reports?)\b",
        text,
    ):
        return "temporal_prose"
    if re.match(
        r"^(?:i|we|he|she|they)\b|^(?:responsible for|worked on|worked with|"
        r"assisted with|assisted in|helped with|helped to|increased|decreased|"
        r"improved|achieved|delivered|developed|prepared|provided|"
        r"collaborated|maintained|generated|reduced|created)\b",
        text,
    ) or re.search(r"\b(?:was|were|has been|have been)\b|\d\s*%", text):
        return "statement_fragment"
    # An isolated business metric is not an extracted skill. Explicit skill lists
    # retain ambiguous terms for review; no vocabulary allowlist or length cutoff.
    if not explicitly_listed and re.fullmatch(
        r"(?:\w+\s+){1,2}(?:size|volume|amount|target|targets)", text
    ):
        return "context_metric"
    return None


def confident_for_selection(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and AUTO_SELECT_CONFIDENCE <= value <= 1
    )
