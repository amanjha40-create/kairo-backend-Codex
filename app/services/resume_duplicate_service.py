from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.certification import Certification
from app.models.education import Education
from app.models.employment import Employment
from app.models.freelance_contract import FreelanceContract
from app.models.gig_platform import GigPlatform
from app.models.internship import Internship
from app.models.portfolio import PortfolioItem
from app.models.verification_request import VerificationRequest
from app.resumes.normalization import date_ranges_overlap, normalize_text, normalize_url


@dataclass(frozen=True)
class DuplicateAssessment:
    status: str
    candidates: list[dict[str, Any]]
    warnings: list[str]


def classify_match(*, primary_equal: bool, secondary_equal: bool, exact_dates: bool, ranges_overlap: bool, url_equal: bool) -> tuple[str | None, list[str]]:
    if (primary_equal and secondary_equal and exact_dates) or (url_equal and primary_equal):
        return "exact_match", ["normalized_identity_and_dates_match"]
    if primary_equal and (secondary_equal or ranges_overlap):
        return "probable_match", ["normalized_identity_match"]
    if primary_equal or url_equal:
        return "possible_match", ["partial_identity_match"]
    return None, []


class ResumeDuplicateService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def assess(self, user_id: UUID, claim_type: str, payload: dict[str, Any]) -> DuplicateAssessment:
        if claim_type in {"profile", "project", "skill"}:
            return DuplicateAssessment("no_match", [], ["unsupported_import_target"] if claim_type in {"project", "skill"} else [])
        model, primary, secondary, start, end, protected = self._spec(claim_type)
        owner_column = model.created_by_user_id if claim_type == "employment" else model.user_id
        rows = (await self.session.scalars(select(model).where(owner_column == user_id, model.deleted_at.is_(None)))).all()
        active_employment_ids: set[UUID] = set()
        if claim_type == "employment" and rows:
            terminal = {"verified", "rejected", "cancelled", "expired"}
            active_employment_ids = set((await self.session.scalars(select(VerificationRequest.employment_id).where(
                VerificationRequest.employment_id.in_([row.id for row in rows]),
                VerificationRequest.subject_user_id == user_id,
                VerificationRequest.status.not_in(terminal),
            ))).all())
        candidates: list[dict[str, Any]] = []
        requested_primary = normalize_text(payload.get(primary))
        requested_secondary = normalize_text(payload.get(secondary)) if secondary else ""
        requested_url = normalize_url(payload.get("url") or payload.get("credential_url"))
        for row in rows:
            row_primary = normalize_text(getattr(row, primary, None))
            row_secondary = normalize_text(getattr(row, secondary, None)) if secondary else ""
            row_url = normalize_url(getattr(row, "url", None) or getattr(row, "credential_url", None))
            primary_equal = bool(requested_primary and requested_primary == row_primary)
            secondary_equal = bool(not secondary or (requested_secondary and requested_secondary == row_secondary))
            url_equal = bool(requested_url and requested_url == row_url)
            row_start = getattr(row, start, None) if start else None
            row_end = getattr(row, end, None) if end else None
            ranges_overlap = date_ranges_overlap(payload.get("start_date"), payload.get("end_date"), row_start, row_end)
            exact_dates = bool(payload.get("start_date") and payload.get("start_date") == row_start and payload.get("end_date") == row_end)
            classification, reasons = classify_match(
                primary_equal=primary_equal,
                secondary_equal=secondary_equal,
                exact_dates=exact_dates,
                ranges_overlap=ranges_overlap,
                url_equal=url_equal,
            )
            if classification:
                is_protected = self._is_protected(row, protected) or row.id in active_employment_ids
                candidates.append({
                    "record_id": str(row.id),
                    "classification": "conflict" if is_protected and classification != "exact_match" else classification,
                    "reasons": reasons,
                    "protected": is_protected,
                    "safety_recommendation": "link_without_mutation" if classification == "exact_match" else "candidate_review_required",
                })
        order = {"conflict": 5, "exact_match": 4, "probable_match": 3, "possible_match": 2, "no_match": 1}
        status = max((candidate["classification"] for candidate in candidates), key=lambda value: order[value], default="no_match")
        return DuplicateAssessment(status, candidates, ["protected_record_match"] if status == "conflict" else [])

    @staticmethod
    def _is_protected(row: Any, statuses: set[str]) -> bool:
        return getattr(row, "verification_status", None) in statuses or getattr(row, "verified_at", None) is not None

    @staticmethod
    def _spec(claim_type: str) -> tuple[Any, str, str | None, str | None, str | None, set[str]]:
        specs = {
            "employment": (Employment, "employer_legal_name", "job_title", "start_date", "end_date", {"submitted", "under_review", "approved"}),
            "education": (Education, "institution_name", "degree", "start_date", "end_date", {"submitted", "under_review", "verified"}),
            "internship": (Internship, "company_name", "role", "start_date", "end_date", {"submitted", "under_review", "verified"}),
            "freelance": (FreelanceContract, "client_name", "project_title", "start_date", "end_date", {"submitted", "under_review", "verified"}),
            "gig_platform": (GigPlatform, "platform_name", "partner_role", "started_at", "ended_at", {"submitted", "under_review", "verified"}),
            "certification": (Certification, "title", "issuing_organization", "issued_date", "expiry_date", {"submitted", "under_review", "verified"}),
            "portfolio": (PortfolioItem, "title", None, None, None, {"submitted", "under_review", "verified"}),
        }
        return specs[claim_type]
