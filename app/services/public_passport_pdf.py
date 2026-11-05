"""Recipient PDF: render only the canonical, permission-filtered public DTO.

No owner engine, storage reads, remote resources, IDs or token-bearing links.
Documents retain the public page's metadata-only disclosure contract.
"""

from datetime import UTC, date, datetime
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import CondPageBreak, Paragraph, SimpleDocTemplate

from app.schemas.public_passport import PublicPassportResponse
from app.services.passport_pdf_layout import (
    branded_footer,
    branded_header,
    branded_record,
    branded_verification_summary,
)
from app.services.passport_pdf_service import _register_fonts, _safe, _styles

# Explicit field allowlists prevent future DTO additions becoming PDF disclosures.
_FIELDS = {
    "employments": ("job_title", "employer_legal_name", "start_date", "end_date"),
    "educations": (
        "institution_name",
        "degree",
        "field_of_study",
        "education_level",
        "grade",
        "start_date",
        "end_date",
        "is_currently_studying",
    ),
    "certifications": (
        "title",
        "issuing_organization",
        "issued_date",
        "expiry_date",
        "does_not_expire",
        "credential_id",
    ),
    "internships": ("role", "company_name", "description", "start_date", "end_date", "is_ongoing"),
    "freelance": (
        "project_title",
        "client_name",
        "description",
        "start_date",
        "end_date",
        "is_ongoing",
    ),
    "gig_platforms": (
        "platform_name",
        "partner_role",
        "started_at",
        "ended_at",
        "is_active",
        "rating",
    ),
    "projects": (
        "title",
        "role",
        "organization_name",
        "description",
        "start_date",
        "end_date",
        "is_ongoing",
    ),
    "portfolio": ("title", "description", "tags"),
    "skills": ("name",),
    "user_documents": ("original_filename", "document_type", "byte_size", "expires_at"),
}
_TITLES = {
    "employments": "Employment",
    "educations": "Education",
    "certifications": "Certifications",
    "internships": "Internships",
    "freelance": "Client history",
    "gig_platforms": "Platform experience",
    "projects": "Projects",
    "portfolio": "Portfolio",
    "skills": "Skills",
    "user_documents": "Shared documents",
}
def _value(value: object, precision: str | None = None) -> str:
    if isinstance(value, date):
        return value.strftime(
            "%Y" if precision == "year" else "%b %Y" if precision == "month" else "%d %b %Y"
        )
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def _status(status: str) -> str:
    if status == "verified":
        return "Verified"
    if status in {
        "pending",
        "submitted",
        "under_review",
        "additional_info_requested",
        "pending_admin_review",
    }:
        return "Pending verification"
    if status in {"draft", "self_declared", "approved"}:
        return "Candidate-provided"
    return "Not verified"


def render_public_passport_pdf(passport: PublicPassportResponse) -> bytes:
    _register_fonts()
    styles = _styles()
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=22 * mm,
        title="KairoID Shared Trust Passport",
        author="KairoID",
        subject="Permission-limited shared Passport snapshot",
    )
    permissions = passport.share.permissions
    profile_lines = []
    if permissions.include_profile:
        for value in (passport.profile.headline, passport.profile.location):
            if value:
                profile_lines.append(value)
    trust_score = None
    if permissions.show_trust_score and passport.trust_score is not None:
        score = passport.trust_score
        if score.overall is not None and score.status != "consent_required":
            trust_score = (
                score.overall,
                None,
                "Derived account-wide aggregate; not verification of each shared record.",
            )
    story = branded_header(
        title="KairoID Trust Passport",
        # Owner attribution is part of the existing public contract without profile sharing.
        candidate_name=passport.profile.full_name,
        profile_lines=profile_lines,
        generated_at=datetime.now(UTC),
        notice=(
            "Only information allowed by this share is included. "
            "A downloaded copy cannot be recalled after revocation."
        ),
        styles=styles,
        safe=_safe,
        trust_score=trust_score,
    )
    story.extend(branded_verification_summary(metrics=_public_metrics(passport), styles=styles))
    for section, fields in _FIELDS.items():
        if not getattr(permissions, f"include_{section}"):
            continue
        if section == "user_documents" and not permissions.show_documents:
            continue
        records = getattr(passport.vault, section)
        if not records:
            continue
        story.extend([CondPageBreak(30 * mm), Paragraph(_TITLES[section], styles["section_title"])])
        for record in records:
            record_fields: list[tuple[str, str]] = []
            for field in fields:
                if field == "employer_legal_name" and not permissions.show_employer_names:
                    continue
                value = getattr(record, field)
                if value is None or value == "" or value == []:
                    continue
                precision = getattr(record, f"{field}_precision", None)
                label = field.replace("_", " ").capitalize()
                record_fields.append((label, _value(value, precision)))
            if section == "employments" and permissions.show_documents:
                record_fields.extend(
                    (
                        "Shared document",
                        f"{evidence.original_filename} ({evidence.document_type})",
                    )
                    for evidence in record.documents
                )
            story.extend(
                branded_record(
                    fields=record_fields,
                    verification_label=_status(record.verification_status),
                    styles=styles,
                    safe=_safe,
                )
            )
    if permissions.show_documents:
        story.append(
            Paragraph(
                "Shared documents are listed as metadata only. "
                "An uploaded file is not itself proof of verification.",
                styles["caption"],
            )
        )

    footer = branded_footer(
        label="KairoID | Consent-based shared Passport",
        title="KairoID Shared Trust Passport",
        subject="Permission-limited shared Passport snapshot",
    )

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()


def _public_metrics(passport: PublicPassportResponse) -> list[tuple[str, int]]:
    permissions = passport.share.permissions
    records = []
    for section in (
        "employments",
        "educations",
        "certifications",
        "internships",
        "freelance",
        "gig_platforms",
        "projects",
        "portfolio",
        "skills",
    ):
        if getattr(permissions, f"include_{section}"):
            records.extend(getattr(passport.vault, section))
    statuses = [getattr(record, "verification_status", "") for record in records]
    verified = sum(status.strip().lower() == "verified" for status in statuses)
    pending = sum(
        status.strip().lower()
        in {
            "pending",
            "submitted",
            "under_review",
            "additional_info_requested",
            "pending_admin_review",
        }
        for status in statuses
    )
    metrics: list[tuple[str, int]] = []
    if permissions.include_employments:
        metrics.append(("Employment", len(passport.vault.employments)))
    if permissions.include_educations:
        metrics.append(("Education", len(passport.vault.educations)))
    metrics.extend([("Verified", verified), ("Pending", pending)])
    return metrics
