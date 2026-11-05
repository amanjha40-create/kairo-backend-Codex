"""Shared branded layout primitives for owner and recipient Passport PDFs."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Iterable

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, KeepTogether, Paragraph, Spacer, Table, TableStyle

_NAVY = HexColor("#07122B")
_NAVY_PANEL = HexColor("#10233E")
_TEAL = HexColor("#12D6C5")
_MINT = HexColor("#F4F8F7")
_MUTED = HexColor("#607184")
_BORDER = HexColor("#D8E7E7")
_WHITE = HexColor("#FFFFFF")

_LOGO = (
    Path(__file__).resolve().parents[1]
    / "integrations/email/reference_assets/kairoid-logo-primary.png"
)


def branded_header(
    *,
    title: str,
    candidate_name: str | None,
    profile_lines: Iterable[str],
    generated_at: datetime,
    notice: str,
    styles: dict[str, ParagraphStyle],
    safe: Callable[[str], str],
    trust_score: tuple[int, str | None, str] | None = None,
) -> list:
    """Build the public-link masthead and dark Trust Passport hero."""

    image_width, image_height = ImageReader(str(_LOGO)).getSize()
    logo = Image(str(_LOGO), width=45 * mm, height=45 * mm * image_height / image_width)
    logo.hAlign = "LEFT"
    masthead = Table(
        [[logo, Paragraph("Trust that travels.", styles["brand_tagline"])]],
        colWidths=[105 * mm, 65 * mm],
        hAlign="LEFT",
        style=TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        ),
    )

    hero_intro = [
        Paragraph("CONSENT-BASED PROFESSIONAL IDENTITY", styles["hero_eyebrow"]),
        Paragraph(safe(title), styles["hero_title"]),
        Paragraph(safe(notice), styles["hero_notice"]),
    ]
    profile_content = [
        Paragraph("PASSPORT OWNER", styles["hero_profile_label"]),
    ]
    if candidate_name:
        profile_content.append(Paragraph(safe(candidate_name), styles["hero_name"]))
    for line in profile_lines:
        if line:
            profile_content.append(Paragraph(safe(line), styles["hero_body"]))

    profile_panel = Table(
        [[profile_content]],
        colWidths=[160 * mm],
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _NAVY_PANEL),
                ("BOX", (0, 0), (-1, -1), 0.7, HexColor("#31445F")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 5 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5 * mm),
            ]
        ),
    )

    score_panel = None
    if trust_score is not None:
        overall, status_label, caption = trust_score
        fill_width = max(1, min(147, 148 * overall / 100)) * mm
        track_width = 149 * mm - fill_width
        progress = Table(
            [["", ""]],
            colWidths=[fill_width, track_width],
            rowHeights=[1.6 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, 0), _TEAL),
                    ("BACKGROUND", (1, 0), (1, 0), HexColor("#31445F")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            ),
        )
        score_content = [
            Paragraph("Trust Score", styles["hero_score_label_left"]),
            Paragraph(
                f"{overall} <font size='9' color='#9DB5C7'>/ 100</font>",
                styles["hero_score_left"],
            ),
            Spacer(1, 2 * mm),
            progress,
            Spacer(1, 2 * mm),
            Paragraph(safe(caption), styles["hero_score_caption_left"]),
        ]
        if status_label:
            score_content.append(Paragraph(safe(status_label), styles["hero_score_status_left"]))
        score_panel = Table(
            [[score_content]],
            colWidths=[160 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), HexColor("#0B1934")),
                    ("BOX", (0, 0), (-1, -1), 0.7, HexColor("#263858")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6 * mm),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6 * mm),
                    ("TOPPADDING", (0, 0), (-1, -1), 5 * mm),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5 * mm),
                ]
            ),
        )

    hero_rows = [
        [hero_intro],
        [profile_panel],
    ]
    if score_panel is not None:
        hero_rows.append([score_panel])
    generated = generated_at.astimezone(UTC).strftime("%d %b %Y, %H:%M UTC")
    hero_rows.append([Paragraph(f"Generated {generated}", styles["hero_timestamp"])])
    hero = Table(
        hero_rows,
        colWidths=[170 * mm],
        hAlign="LEFT",
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _NAVY),
                ("BOX", (0, 0), (-1, -1), 0.8, HexColor("#183D50")),
                ("LEFTPADDING", (0, 0), (-1, -1), 5 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 4 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
            ]
        ),
    )
    return [masthead, Spacer(1, 4 * mm), hero, Spacer(1, 5 * mm)]


def branded_verification_summary(
    *,
    metrics: Iterable[tuple[str, int]],
    styles: dict[str, ParagraphStyle],
) -> list:
    """Render the public page's compact verification metric strip."""

    values = list(metrics)
    cells = [
        [Paragraph(str(value), styles["metric_value"]), Paragraph(label, styles["metric_label"])]
        for label, value in values
    ]
    table = Table(
        [cells],
        colWidths=[170 * mm / len(cells)] * len(cells),
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _MINT),
                ("BOX", (0, 0), (-1, -1), 0.6, _BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, _BORDER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
            ]
        ),
    )
    return [table, Spacer(1, 7 * mm)]


def branded_section_header(
    *,
    title: str,
    count: int,
    styles: dict[str, ParagraphStyle],
    eyebrow: str = "SHARED RECORD",
) -> list:
    """Render the public page's section label, title, and record count."""

    heading = [
        Paragraph(eyebrow, styles["section_eyebrow"]),
        Paragraph(title, styles["section_title_public"]),
    ]
    count_label = f"{count} {'record' if count == 1 else 'records'}"
    row = Table(
        [[heading, Paragraph(count_label, styles["section_count"])]],
        colWidths=[135 * mm, 35 * mm],
        style=TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        ),
    )
    return [row, Spacer(1, 2.5 * mm)]


def branded_record(
    *,
    fields: Iterable[tuple[str, str]],
    verification_label: str,
    styles: dict[str, ParagraphStyle],
    safe: Callable[[str], str],
) -> list:
    """Render one record using the disclosure-scoped PDF's labeled-field layout."""

    visible_fields = [(label, value) for label, value in fields if value]
    if not visible_fields:
        return []
    lead_label, lead_value = visible_fields[0]
    body: list = [
        Paragraph(safe(lead_value), styles["record_card_title"]),
        Paragraph(safe(lead_label), styles["record_card_kicker"]),
    ]
    detail_text = visible_fields[1:]
    details_fit_card = sum(len(label) + len(value) for label, value in detail_text) <= 1200
    if details_fit_card:
        body.extend(
            Paragraph(f"<b>{safe(label)}:</b> {safe(value)}", styles["record_card_body"])
            for label, value in detail_text
        )
    if verification_label in {"Candidate-provided", "Self-declared / Not Verified"}:
        body.append(
            Paragraph(
                "Provided by the Candidate and not independently verified.",
                styles["record_disclosure"],
            )
        )
    card = Table(
        [[[body], Paragraph(safe(verification_label), styles["status_badge"])]],
        colWidths=[105 * mm, 55 * mm],
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _WHITE),
                ("BOX", (0, 0), (-1, -1), 0.6, _BORDER),
                ("LINEBEFORE", (0, 0), (0, 0), 2.2, _TEAL),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5 * mm),
            ]
        ),
    )
    details = []
    if not details_fit_card:
        details = [
            Paragraph(f"<b>{safe(label)}:</b> {safe(value)}", styles["record_card_body"])
            for label, value in detail_text
        ]
    return [KeepTogether([card]), *details, Spacer(1, 3 * mm)]


def branded_footer(
    *,
    label: str,
    title: str,
    subject: str,
):
    """Return a page callback with consistent KairoID metadata and pagination."""

    def footer(pdf_canvas, document):  # noqa: ANN001
        pdf_canvas.saveState()
        pdf_canvas.setFillColor(_MINT)
        pdf_canvas.rect(0, 0, A4[0], A4[1], stroke=0, fill=1)
        pdf_canvas.setFillColor(_WHITE)
        pdf_canvas.rect(14 * mm, 16 * mm, A4[0] - 28 * mm, A4[1] - 32 * mm, stroke=0, fill=1)
        pdf_canvas.setTitle(title)
        pdf_canvas.setAuthor("KairoID")
        pdf_canvas.setSubject(subject)
        pdf_canvas.setFont("KairoSans", 8)
        pdf_canvas.setFillColor(_MUTED)
        pdf_canvas.drawString(20 * mm, 10 * mm, label)
        pdf_canvas.drawRightString(A4[0] - 20 * mm, 10 * mm, f"Page {document.page}")
        pdf_canvas.restoreState()

    return footer
