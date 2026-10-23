"""Deterministic source attribution; model-supplied section labels are not trusted."""

from __future__ import annotations

import re

from app.resumes.skill_quality import skill_key

_HEADINGS = {
    "skills": (
        r"(?:(?:core|technical|professional|key)\s+)?sk(?:i|l|1)lls"
        r"(?:\s+(?:&|and)\s+technologies)?|(?:core\s+)?competenc(?:y|ies)"
    ),
    "experience": (
        r"(?:(?:professional|work|relevant|employment)\s+)?experience|"
        r"employment(?:\s+history)?|work\s+history|internships?"
    ),
    "education": (
        r"education(?:\s+(?:and|&)\s+qualifications)?|"
        r"academic\s+(?:background|qualifications)"
    ),
    "certifications": (
        r"(?:professional\s+)?certifications?|"
        r"licenses?(?:\s+(?:and|&)\s+certifications)?"
    ),
    "summary": (
        r"(?:(?:professional|career|personal)\s+)?summary|"
        r"(?:candidate\s+)?profile|(?:career\s+)?objective"
    ),
    "other": (
        r"projects?|portfolio|languages?|awards?|interests?|references?|"
        r"personal\s+information|contact(?:\s+details)?"
    ),
}


def section_heading(line: str) -> str | None:
    text = line.strip().strip(":-–— ")
    for section, pattern in _HEADINGS.items():
        if re.fullmatch(pattern, text, re.IGNORECASE):
            return section
    # Side-by-side OCR headings must terminate a skills list too.
    if re.fullmatch(r"education\s+personal\s+information", text, re.IGNORECASE):
        return "other"
    return None


def section_lines(text: str) -> list[tuple[str, str]]:
    section = "other"
    result = []
    for line in text.splitlines():
        heading = section_heading(line)
        if heading:
            section = heading
            continue
        if line.strip():
            result.append((section, line.strip()))
    return result


def grounded_section(name: str, lines: list[tuple[str, str]]) -> str | None:
    needle = re.escape(skill_key(name))
    # Symbol-aware boundaries prevent C matching C++, and SQL matching NoSQL.
    pattern = re.compile(r"(?<![\w+#.])" + needle + r"(?![\w+#])")
    for section, line in lines:
        if pattern.search(skill_key(line)):
            return section
    return None
