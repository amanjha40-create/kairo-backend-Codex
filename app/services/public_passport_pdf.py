"""Recipient PDF: render only the canonical, permission-filtered public DTO.

No owner engine, storage reads, remote resources, IDs or token-bearing links.
Documents retain the public page's metadata-only disclosure contract.
"""

from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import CondPageBreak, Image, Paragraph, SimpleDocTemplate, Spacer

from app.schemas.public_passport import PublicPassportResponse
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
_LOGO = (
    Path(__file__).resolve().parents[1]
    / "integrations/email/reference_assets/kairoid-logo-primary.png"
)


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
    image_width, image_height = ImageReader(str(_LOGO)).getSize()
    logo = Image(str(_LOGO), width=52 * mm, height=52 * mm * image_height / image_width)
    logo.hAlign = "LEFT"
    story = [logo, Spacer(1, 5 * mm), Paragraph("Shared Trust Passport", styles["document_title"])]
    # Owner attribution is part of the existing public contract even without profile sharing.
    if passport.profile.full_name:
        story.append(Paragraph(_safe(passport.profile.full_name), styles["candidate_name"]))
    permissions = passport.share.permissions
    if permissions.include_profile:
        for value in (passport.profile.headline, passport.profile.location):
            if value:
                story.append(Paragraph(_safe(value), styles["body"]))
    generated = datetime.now(UTC).strftime("%d %b %Y, %H:%M UTC")
    story.extend(
        [
            Spacer(1, 3 * mm),
            Paragraph(f"Generated {generated}", styles["caption"]),
            Paragraph(
                "Only information allowed by this share is included. "
                "A downloaded copy cannot be recalled after revocation.",
                styles["caption"],
            ),
            Spacer(1, 6 * mm),
        ]
    )
    if permissions.show_trust_score and passport.trust_score is not None:
        score = passport.trust_score
        if score.overall is not None and score.status != "consent_required":
            story.extend(
                [
                    Paragraph("Trust Score", styles["section_title"]),
                    Paragraph(f"{score.overall} / 100", styles["record_title"]),
                    Paragraph(
                        "Derived account-wide aggregate; not verification of each shared record.",
                        styles["caption"],
                    ),
                    Spacer(1, 5 * mm),
                ]
            )
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
            for field in fields:
                if field == "employer_legal_name" and not permissions.show_employer_names:
                    continue
                value = getattr(record, field)
                if value is None or value == "" or value == []:
                    continue
                precision = getattr(record, f"{field}_precision", None)
                label = field.replace("_", " ").capitalize()
                story.append(
                    Paragraph(f"<b>{label}:</b> {_safe(_value(value, precision))}", styles["body"])
                )
            story.append(Paragraph(_status(record.verification_status), styles["status"]))
            if section == "employments" and permissions.show_documents:
                for evidence in record.documents:
                    story.append(
                        Paragraph(
                            f"Shared document: {_safe(evidence.original_filename)} "
                            f"({_safe(evidence.document_type)})",
                            styles["body"],
                        )
                    )
            story.append(Spacer(1, 5 * mm))
    if permissions.show_documents:
        story.append(
            Paragraph(
                "Shared documents are listed as metadata only. "
                "An uploaded file is not itself proof of verification.",
                styles["caption"],
            )
        )

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("KairoSans", 8)
        canvas.drawString(20 * mm, 12 * mm, "KairoID | Consent-based shared Passport")
        canvas.drawRightString(A4[0] - 20 * mm, 12 * mm, f"Page {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
