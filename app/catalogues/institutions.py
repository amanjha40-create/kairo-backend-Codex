"""Optional India higher-education suggestions, never an identity registry."""

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "institutions_india_v1.json"
CATALOGUE_VERSION = "india-he-v1"
CATALOGUE_PROVENANCE = {
    "source_name": "Ministry of Education, Department of Higher Education, Government of India - List of colleges (AISHE Survey)",
    "source_url": "https://data.gov.in/catalog/list-colleges-aishe-survey",
    "licence_name": "Government Open Data License - India (GODL-India)",
    "licence_url": "https://data.gov.in/Godl",
    "attribution": "Institution catalogue source: Ministry of Education, Department of Higher Education, Government of India — List of colleges (AISHE Survey), Open Government Data Platform India. Published under the Government Open Data License – India.",
    "non_endorsement": "KairoID is not affiliated with or endorsed by the Ministry of Education or data.gov.in.",
}
COMMON_WORDS = {
    word.upper(): word for word in (
        "College", "University", "Institute", "Institution", "Government", "Arts",
        "Science", "Commerce", "Engineering", "Technology", "Management", "Medical",
        "Polytechnic", "Education", "of", "and", "for", "the",
    )
}


def clean_text(value: str) -> str:
    value = " ".join(unicodedata.normalize("NFKC", value).split())
    value = re.sub(r"\s+([,;])", r"\1", value)
    value = re.sub(r"([,;])(?=\w)", r"\1 ", value)
    # Avoid title-casing proper names, initials and acronyms such as IIT or AIIMS.
    if value.isupper():
        value = re.sub(r"\b[A-Z]+\b", lambda m: COMMON_WORDS.get(m[0], m[0]), value)
    return value


def search_key(value: str) -> str:
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", value).casefold()))


@lru_cache(maxsize=1)
def load_catalogue() -> tuple[dict, tuple[dict, ...]]:
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    assert data["version"] == CATALOGUE_VERSION
    rows = data["institutions"]
    if not rows or len({r["id"] for r in rows}) != len(rows):
        raise ValueError("Invalid catalogue identifiers")
    for row in rows:
        if not row["name"] or not all(isinstance(row[k], str) for k in
                                      ("id", "name", "state", "district", "city")):
            raise ValueError("Invalid catalogue record")
    return data["provenance"], tuple(rows)


@lru_cache(maxsize=1)
def search_index() -> tuple[tuple[dict, str, str], ...]:
    _, rows = load_catalogue()
    return tuple((r, search_key(r["name"]), search_key(" ".join(
        r[k] for k in ("name", "state", "district", "city")
    ))) for r in rows)


def search_institutions(query: str, state: str = "", district: str = "",
                        limit: int = 20, offset: int = 0) -> dict:
    result = {
        "provenance": dict(CATALOGUE_PROVENANCE),
        "version": CATALOGUE_VERSION, "scope": "India higher education; incomplete historical snapshot",
        "available": True, "manual_entry_allowed": True,
        "fallback_label": "Institution not listed / Enter manually",
        "items": [], "total": 0, "limit": limit, "offset": offset,
    }
    try:
        index = search_index()
    except (OSError, ValueError, KeyError, TypeError, AssertionError):
        result["available"] = False
        return result
    key = search_key(query)
    if not key:
        return result
    tokens = key.split()
    state_key, district_key = search_key(state), search_key(district)
    matches = [(r, name) for r, name, text in index
               if (not state_key or search_key(r["state"]) == state_key)
               and (not district_key or search_key(r["district"]) == district_key)
               and all(token in text for token in tokens)]
    matches.sort(key=lambda x: (0 if x[1] == key else 1 if x[1].startswith(key) else 2,
                               x[1], x[0]["state"], x[0]["district"], x[0]["id"]))
    result["total"] = len(matches)
    result["items"] = [{k: r[k] for k in ("id", "name", "state", "district", "city")}
                       for r, _ in matches[offset:offset + limit]]
    return result
