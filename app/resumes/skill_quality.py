"""Conservative quality rules; only inferred skills require a recognized concept."""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Any

AUTO_SELECT_CONFIDENCE = 0.80

# Explicit lists are not vocabulary restricted. Inference is deliberately narrower:
# a recognized concept still needs verbatim source evidence and model confidence.
_INFERRED_CONCEPTS = frozenset(
    {
        "python",
        "sql",
        "c",
        "c++",
        "c#",
        ".net",
        "node.js",
        "javascript",
        "typescript",
        "java",
        "kotlin",
        "swift",
        "rust",
        "golang",
        "react",
        "angular",
        "vue",
        "django",
        "flask",
        "fastapi",
        "spring",
        "docker",
        "kubernetes",
        "terraform",
        "git",
        "linux",
        "aws",
        "azure",
        "gcp",
        "postgresql",
        "mysql",
        "mongodb",
        "redis",
        "ci/cd",
        "excel",
        "power bi",
        "tableau",
        "r",
        "pandas",
        "numpy",
        "pytorch",
        "tensorflow",
        "machine learning",
        "data analysis",
        "data engineering",
        "data visualization",
        "financial analysis",
        "financial modeling",
        "financial modelling",
        "portfolio management",
        "risk analysis",
        "risk management",
        "scenario planning",
        "valuation",
        "due diligence",
        "venture capital",
        "m&a",
        "private equity",
        "private markets research",
        "investor relations",
        "stakeholder engagement",
        "project management",
        "process management",
        "financial reporting",
        "market research",
        "research and development",
        "iso 27001",
    }
)


def recognized_inferred_skill(name: str) -> bool:
    return skill_key(name) in _INFERRED_CONCEPTS


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
    if re.search(r"\b(?:19|20)\d{2}\b|\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", text):
        return "date_metadata"
    if re.search(
        r"\b(?:inc|ltd|llc|pvt|corporation)\b|\b(?:intern|analyst|manager|associate|director|officer|consultant)\s*$",
        text,
    ):
        return "employer_or_title"
    if re.search(r"\d\s*(?:%|percent|million|billion|crore|lakhs?)\b|\d\s*%|\d+\+\s+\w", text):
        return "numeric_metric"
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
    if (
        re.match(
            r"^(?:i|we|he|she|they)\b|^(?:responsible for|worked on|worked with|"
            r"assisted with|assisted in|helped with|helped to|increased|decreased|"
            r"improved|achieved|delivered|developed|prepared|provided|"
            r"collaborated|maintained|generated|reduced|created|conducted|designed|partnered|"
            r"mentored|researched|built|produced|coordinated|optimized|streamlined|led|"
            r"supported|executed|analyzed|analysed|managed|oversaw|organized|organised)\b",
            text,
        )
        and text != "managed services"
    ):
        return "statement_fragment"
    if re.search(r"\b(?:was|were|has been|have been|resulting in|leading to)\b", text):
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
