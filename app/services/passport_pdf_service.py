"""Canonical owner Trust Passport PDF projection and rendering."""

from __future__ import annotations

import html
import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime
from importlib.resources import files
from io import BytesIO
from uuid import UUID

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    CondPageBreak,
    KeepTogether,
    LongTable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy.exc import NoResultFound

from app.exceptions import NotFoundError, ServiceUnavailableError
from app.schemas.passport_engine import OwnerPassportResponse
from app.schemas.passport_pdf import (
    PassportPDFCertification,
    PassportPDFEducation,
    PassportPDFEmployment,
    PassportPDFProfile,
    PassportPDFProject,
    PassportPDFProjection,
    PassportPDFSkill,
    PassportPDFTrustScore,
)
from app.services.passport_engine_service import PassportEngineService

logger = logging.getLogger(__name__)

PDF_FILENAME = "Kairo-Trust-Passport.pdf"
PDF_MEDIA_TYPE = "application/pdf"

_KAIRO_TEAL = HexColor("#0EA5A4")
_INK = HexColor("#10263D")
_MUTED = HexColor("#526579")
_SURFACE = HexColor("#F3F8F8")
_BORDER = HexColor("#D7E4E6")
_STATUS_SURFACE = HexColor("#E5F7F6")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_FONT_REGISTERED = False


@dataclass(frozen=True, slots=True)
class PassportPDFDocument:
    content: bytes
    filename: str
    generated_at: datetime


class PassportPDFService:
    """Generate a private owner export from the canonical Passport engine."""

    def __init__(self, engine: PassportEngineService) -> None:
        self._engine = engine

    async def generate(self, owner_user_id: UUID) -> PassportPDFDocument:
        started_at = time.perf_counter()
        generated_at = datetime.now(UTC)
        logger.info(
            "passport_pdf_export_requested",
            extra={"owner_user_id": str(owner_user_id)},
        )

        try:
            owner_passport = await self._engine.get_owner_passport(owner_user_id)
        except NoResultFound:
            raise NotFoundError("Trust Passport not found") from None

        try:
            projection = build_passport_pdf_projection(owner_passport, generated_at=generated_at)
            content = render_passport_pdf(projection)
            if not content or not content.startswith(b"%PDF-"):
                raise ValueError("renderer returned an invalid PDF payload")
        except Exception as exc:
            logger.exception(
                "passport_pdf_export_failed",
                extra={
                    "owner_user_id": str(owner_user_id),
                    "duration_ms": round((time.perf_counter() - started_at) * 1000),
                },
            )
            raise ServiceUnavailableError("Trust Passport PDF is temporarily unavailable") from exc

        logger.info(
            "passport_pdf_export_completed",
            extra={
                "owner_user_id": str(owner_user_id),
                "duration_ms": round((time.perf_counter() - started_at) * 1000),
                "byte_size": len(content),
            },
        )
        return PassportPDFDocument(
            content=content,
            filename=PDF_FILENAME,
            generated_at=generated_at,
        )


def build_passport_pdf_projection(
    owner_passport: OwnerPassportResponse,
    *,
    generated_at: datetime,
) -> PassportPDFProjection:
    """Project only explicitly approved professional owner-export fields."""

    profile = owner_passport.profile
    trust_score = owner_passport.trust_score
    projected_trust_score = None
    if trust_score.overall is not None and trust_score.status != "consent_required":
        projected_trust_score = PassportPDFTrustScore(
            overall=trust_score.overall,
            status=trust_score.status,
            status_label=_trust_score_status_label(trust_score.status),
        )

    return PassportPDFProjection(
        profile=PassportPDFProfile(
            display_name=profile.full_name or "Candidate",
            headline=profile.headline,
            location=profile.location,
            professional_summary=profile.bio,
            current_role=profile.current_role,
            industry=profile.industry,
            years_of_experience=profile.years_of_experience,
        ),
        trust_score=projected_trust_score,
        employments=[
            PassportPDFEmployment(
                employer_name=item.employer_legal_name,
                job_title=item.job_title,
                start_date=item.start_date,
                end_date=item.end_date,
                verification_status=item.verification_status,
                verification_label=verification_status_label(item.verification_status),
            )
            for item in owner_passport.vault.employments
        ],
        educations=[
            PassportPDFEducation(
                institution_name=item.institution_name,
                degree=item.degree,
                field_of_study=item.field_of_study,
                start_date=item.start_date,
                end_date=item.end_date,
                is_currently_studying=item.is_currently_studying,
                verification_status=item.verification_status,
                verification_label=verification_status_label(item.verification_status),
            )
            for item in owner_passport.vault.educations
        ],
        certifications=[
            PassportPDFCertification(
                title=item.title,
                issuing_organization=item.issuing_organization,
                issued_date=item.issued_date,
                expiry_date=item.expiry_date,
                does_not_expire=item.does_not_expire,
                verification_status=item.verification_status,
                verification_label=verification_status_label(item.verification_status),
            )
            for item in owner_passport.vault.certifications
        ],
        projects=[
            PassportPDFProject(
                title=item.title,
                role=item.role,
                organization_name=item.organization_name,
                description=item.description,
                start_date=item.start_date,
                end_date=item.end_date,
                is_ongoing=item.is_ongoing,
                verification_status=item.verification_status,
                verification_label=verification_status_label(item.verification_status),
            )
            for item in owner_passport.vault.projects
        ],
        skills=[
            PassportPDFSkill(
                name=item.name,
                verification_status=item.verification_status,
                verification_label=verification_status_label(item.verification_status),
            )
            for item in owner_passport.vault.skills
        ],
        generated_at=generated_at,
    )


def verification_status_label(status: str) -> str:
    normalized = status.strip().lower()
    labels = {
        "verified": "Verified",
        "approved": "Verified",
        "draft": "Self-declared / Not Verified",
        "self_declared": "Self-declared / Not Verified",
        "not_verified": "Self-declared / Not Verified",
        "pending": "Pending",
        "pending_upload": "Pending upload",
        "pending_review": "Pending review",
        "submitted": "Submitted for verification",
        "under_review": "In verification",
        "additional_info_requested": "Additional information requested",
        "unable_to_verify": "Unable to verify",
        "rejected": "Rejected",
        "cancelled": "Cancelled",
    }
    return labels.get(normalized, normalized.replace("_", " ").title() or "Not Verified")


def render_passport_pdf(projection: PassportPDFProjection) -> bytes:
    """Render a deterministic, print-oriented PDF without external resources."""

    _register_fonts()
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=19 * mm,
        bottomMargin=20 * mm,
        title="Kairo Trust Passport",
        author="Kairo",
        subject="Candidate-owned professional Trust Passport export",
    )
    styles = _styles()
    story: list = []

    story.extend(_header(projection, styles))
    story.extend(_professional_summary(projection, styles))
    if projection.trust_score is not None:
        story.extend(_trust_score_summary(projection.trust_score, styles))

    _append_record_section(story, "Employment", projection.employments, _employment_story, styles)
    _append_record_section(story, "Education", projection.educations, _education_story, styles)
    _append_record_section(
        story,
        "Certifications",
        projection.certifications,
        _certification_story,
        styles,
    )
    _append_record_section(story, "Projects", projection.projects, _project_story, styles)
    if projection.skills:
        story.extend(_skills_story(projection.skills, styles))

    document.build(
        story,
        onFirstPage=_draw_page_frame,
        onLaterPages=_draw_page_frame,
        canvasmaker=_invariant_canvas,
    )
    return buffer.getvalue()


def _header(projection: PassportPDFProjection, styles: dict[str, ParagraphStyle]) -> list:
    generated = projection.generated_at.astimezone(UTC).strftime("%d %b %Y, %H:%M UTC")
    return [
        Paragraph("KAIRO", styles["brand"]),
        Paragraph("Trust Passport", styles["document_title"]),
        Spacer(1, 3 * mm),
        Paragraph(_safe(projection.profile.display_name), styles["candidate_name"]),
        Paragraph(f"Generated {generated}", styles["caption"]),
        Spacer(1, 7 * mm),
    ]


def _professional_summary(
    projection: PassportPDFProjection,
    styles: dict[str, ParagraphStyle],
) -> list:
    profile = projection.profile
    lines: list[str] = []
    if profile.headline:
        lines.append(_safe(profile.headline))
    role_parts = [value for value in (profile.current_role, profile.industry) if value]
    if role_parts:
        lines.append(_safe(" | ".join(role_parts)))
    experience_parts: list[str] = []
    if profile.years_of_experience is not None:
        experience_parts.append(f"{profile.years_of_experience} years of professional experience")
    if profile.location:
        experience_parts.append(_safe(profile.location))
    if experience_parts:
        lines.append(" | ".join(experience_parts))
    if profile.professional_summary:
        lines.append(_safe(profile.professional_summary))

    if not lines:
        return []

    content = [Paragraph(line, styles["body"]) for line in lines]
    return [
        Paragraph("Professional summary", styles["section_title"]),
        Table(
            [[content]],
            colWidths=[170 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), _SURFACE),
                    ("BOX", (0, 0), (-1, -1), 0.6, _BORDER),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5 * mm),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5 * mm),
                    ("TOPPADDING", (0, 0), (-1, -1), 4 * mm),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * mm),
                ]
            ),
        ),
        Spacer(1, 6 * mm),
    ]


def _trust_score_summary(
    trust_score: PassportPDFTrustScore,
    styles: dict[str, ParagraphStyle],
) -> list:
    table = Table(
        [
            [
                Paragraph("Trust Score", styles["record_title"]),
                Paragraph(f"{trust_score.overall} / 100", styles["score"]),
            ],
            [
                Paragraph("Authoritative backend value", styles["caption"]),
                Paragraph(_safe(trust_score.status_label), styles["status"]),
            ],
        ],
        colWidths=[115 * mm, 55 * mm],
        hAlign="LEFT",
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _STATUS_SURFACE),
                ("BOX", (0, 0), (-1, -1), 0.6, _KAIRO_TEAL),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ]
        ),
    )
    return [table, Spacer(1, 7 * mm)]


def _append_record_section(story, title, records, renderer, styles) -> None:  # noqa: ANN001
    if not records:
        return
    story.append(CondPageBreak(35 * mm))
    story.append(Paragraph(title, styles["section_title"]))
    for index, record in enumerate(records):
        story.extend(renderer(record, styles))
        if index < len(records) - 1:
            story.append(Spacer(1, 3 * mm))
    story.append(Spacer(1, 6 * mm))


def _employment_story(item: PassportPDFEmployment, styles) -> list:  # noqa: ANN001
    subtitle = item.employer_name or "Employer not displayed"
    return _record_story(
        item.job_title,
        subtitle,
        _date_range(item.start_date, item.end_date),
        item.verification_label,
        None,
        styles,
    )


def _education_story(item: PassportPDFEducation, styles) -> list:  # noqa: ANN001
    degree = " - ".join(part for part in (item.degree, item.field_of_study) if part)
    return _record_story(
        degree,
        item.institution_name,
        _date_range(item.start_date, item.end_date, ongoing=item.is_currently_studying),
        item.verification_label,
        None,
        styles,
    )


def _certification_story(item: PassportPDFCertification, styles) -> list:  # noqa: ANN001
    date_parts: list[str] = []
    if item.issued_date:
        date_parts.append(f"Issued {_format_date(item.issued_date)}")
    if item.does_not_expire:
        date_parts.append("Does not expire")
    elif item.expiry_date:
        date_parts.append(f"Expires {_format_date(item.expiry_date)}")
    return _record_story(
        item.title,
        item.issuing_organization,
        " | ".join(date_parts) or None,
        item.verification_label,
        None,
        styles,
    )


def _project_story(item: PassportPDFProject, styles) -> list:  # noqa: ANN001
    subtitle = " | ".join(part for part in (item.role, item.organization_name) if part)
    return _record_story(
        item.title,
        subtitle or None,
        _date_range(item.start_date, item.end_date, ongoing=item.is_ongoing),
        item.verification_label,
        item.description,
        styles,
    )


def _record_story(
    title: str,
    subtitle: str | None,
    dates: str | None,
    status: str,
    description: str | None,
    styles: dict[str, ParagraphStyle],
) -> list:
    header = Table(
        [
            [
                Paragraph(_safe(title), styles["record_title"]),
                Paragraph(_safe(status), styles["status"]),
            ]
        ],
        colWidths=[125 * mm, 45 * mm],
        hAlign="LEFT",
        style=TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 * mm),
            ]
        ),
    )
    metadata_parts = [_safe(value) for value in (subtitle, dates) if value]
    leading = [header]
    if metadata_parts:
        leading.append(Paragraph(" | ".join(metadata_parts), styles["metadata"]))
    result = [KeepTogether(leading)]
    if description:
        result.append(Paragraph(_safe(description), styles["body"]))
    result.append(
        Table(
            [[""]],
            colWidths=[170 * mm],
            rowHeights=[0.2 * mm],
            style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), _BORDER)]),
        )
    )
    return result


def _skills_story(skills: list[PassportPDFSkill], styles) -> list:  # noqa: ANN001
    rows = [
        [
            Paragraph(_safe(item.name), styles["body"]),
            Paragraph(_safe(item.verification_label), styles["status"]),
        ]
        for item in skills
    ]
    table = LongTable(
        rows,
        colWidths=[125 * mm, 45 * mm],
        hAlign="LEFT",
        repeatRows=0,
        style=TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, _SURFACE]),
                ("BOX", (0, 0), (-1, -1), 0.4, _BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, _BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 2.2 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2 * mm),
            ]
        ),
    )
    return [
        CondPageBreak(35 * mm),
        Paragraph("Skills", styles["section_title"]),
        table,
    ]


def _styles() -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    return {
        "brand": ParagraphStyle(
            "KairoBrand",
            parent=sample["Normal"],
            fontName="KairoSans-Bold",
            fontSize=10,
            leading=12,
            textColor=_KAIRO_TEAL,
            tracking=1.8,
            spaceAfter=1 * mm,
        ),
        "document_title": ParagraphStyle(
            "KairoDocumentTitle",
            parent=sample["Title"],
            fontName="KairoSans-Bold",
            fontSize=25,
            leading=29,
            alignment=TA_LEFT,
            textColor=_INK,
            spaceAfter=1 * mm,
        ),
        "candidate_name": ParagraphStyle(
            "KairoCandidateName",
            parent=sample["Heading1"],
            fontName="KairoSans-Bold",
            fontSize=17,
            leading=21,
            textColor=_INK,
            spaceAfter=1.2 * mm,
        ),
        "section_title": ParagraphStyle(
            "KairoSectionTitle",
            parent=sample["Heading2"],
            fontName="KairoSans-Bold",
            fontSize=13,
            leading=16,
            textColor=_KAIRO_TEAL,
            keepWithNext=True,
            spaceBefore=1 * mm,
            spaceAfter=3 * mm,
        ),
        "record_title": ParagraphStyle(
            "KairoRecordTitle",
            parent=sample["Normal"],
            fontName="KairoSans-Bold",
            fontSize=10.5,
            leading=14,
            textColor=_INK,
        ),
        "body": ParagraphStyle(
            "KairoBody",
            parent=sample["BodyText"],
            fontName="KairoSans",
            fontSize=9.4,
            leading=13.5,
            textColor=_INK,
            spaceAfter=1.5 * mm,
        ),
        "metadata": ParagraphStyle(
            "KairoMetadata",
            parent=sample["Normal"],
            fontName="KairoSans",
            fontSize=8.5,
            leading=11,
            textColor=_MUTED,
            spaceAfter=2 * mm,
        ),
        "caption": ParagraphStyle(
            "KairoCaption",
            parent=sample["Normal"],
            fontName="KairoSans",
            fontSize=8,
            leading=10,
            textColor=_MUTED,
        ),
        "status": ParagraphStyle(
            "KairoStatus",
            parent=sample["Normal"],
            fontName="KairoSans-Bold",
            fontSize=8,
            leading=10,
            alignment=TA_CENTER,
            textColor=_KAIRO_TEAL,
        ),
        "score": ParagraphStyle(
            "KairoScore",
            parent=sample["Normal"],
            fontName="KairoSans-Bold",
            fontSize=15,
            leading=18,
            alignment=TA_CENTER,
            textColor=_KAIRO_TEAL,
        ),
    }


def _draw_page_frame(pdf_canvas: canvas.Canvas, document: SimpleDocTemplate) -> None:
    pdf_canvas.saveState()
    pdf_canvas.setTitle("Kairo Trust Passport")
    pdf_canvas.setAuthor("Kairo")
    pdf_canvas.setSubject("Candidate-owned professional Trust Passport export")
    pdf_canvas.setStrokeColor(_BORDER)
    pdf_canvas.setLineWidth(0.5)
    pdf_canvas.line(20 * mm, 14 * mm, A4[0] - 20 * mm, 14 * mm)
    pdf_canvas.setFont("KairoSans", 7.5)
    pdf_canvas.setFillColor(_MUTED)
    pdf_canvas.drawString(20 * mm, 9.5 * mm, "Private owner export - generated by Kairo")
    pdf_canvas.drawRightString(A4[0] - 20 * mm, 9.5 * mm, f"Page {document.page}")
    pdf_canvas.restoreState()


def _invariant_canvas(*args, **kwargs):  # noqa: ANN002, ANN003
    kwargs["invariant"] = 1
    return canvas.Canvas(*args, **kwargs)


def _register_fonts() -> None:
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return
    font_directory = files("reportlab").joinpath("fonts")
    pdfmetrics.registerFont(TTFont("KairoSans", str(font_directory.joinpath("Vera.ttf"))))
    pdfmetrics.registerFont(TTFont("KairoSans-Bold", str(font_directory.joinpath("VeraBd.ttf"))))
    _FONT_REGISTERED = True


def _safe(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    normalized = _CONTROL_CHARACTERS.sub("", normalized)
    return html.escape(normalized, quote=False).replace("\n", "<br/>")


def _date_range(start: date | None, end: date | None, *, ongoing: bool = False) -> str | None:
    if start is None and end is None and not ongoing:
        return None
    start_text = _format_date(start) if start else "Date not provided"
    end_text = "Present" if ongoing else _format_date(end) if end else "Present"
    return f"{start_text} - {end_text}"


def _format_date(value: date) -> str:
    return value.strftime("%b %Y")


def _trust_score_status_label(status: str) -> str:
    return {
        "calculated": "Calculated",
        "incomplete_verification": "Verification incomplete",
        "critical_manual_fraud_review": "Manual review required",
    }.get(status, status.replace("_", " ").title())
