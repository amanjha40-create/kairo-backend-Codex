from __future__ import annotations

from typing import Any


def required_claim_blockers(claim_type: str, payload: dict[str, Any]) -> list[str]:
    """Return structural blockers that make a parsed claim unsafe to import."""
    required = {
        "education": ("institution_name",),
        "certification": ("title",),
        "portfolio": ("title",),
        "project": ("title",),
        "skill": ("name",),
    }
    blockers = [
        f"missing_{field}" for field in required.get(claim_type, ()) if not payload.get(field)
    ]
    if claim_type == "education" and not any(
        payload.get(field) for field in ("degree", "field_of_study")
    ):
        blockers.append("missing_education_qualification")
    if claim_type == "internship" and not any(
        payload.get(field) for field in ("company_name", "role")
    ):
        blockers.append("missing_internship_identity")
    if claim_type == "freelance" and not any(
        payload.get(field) for field in ("client_name", "project_title")
    ):
        blockers.append("missing_freelance_identity")
    if claim_type == "gig_platform" and not any(
        payload.get(field) for field in ("platform_name", "partner_role")
    ):
        blockers.append("missing_gig_identity")
    if claim_type == "employment":
        if not payload.get("company_name"):
            blockers.append("missing_company_name")
        if not payload.get("role_title"):
            blockers.append("missing_role_title")
    return blockers
