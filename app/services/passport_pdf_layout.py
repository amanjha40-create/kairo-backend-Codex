"""Shared branded layout primitives for owner and recipient Passport PDFs."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Iterable

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, KeepTogether, Paragraph, Spacer

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
) -> list:
    """Build the common KairoID logo, identity, timestamp, and notice header."""

    image_width, image_height = ImageReader(str(_LOGO)).getSize()
    logo = Image(str(_LOGO), width=52 * mm, height=52 * mm * image_height / image_width)
    logo.hAlign = "LEFT"
    story = [logo, Spacer(1, 5 * mm), Paragraph(title, styles["document_title"])]
    if candidate_name:
        story.append(Paragraph(safe(candidate_name), styles["candidate_name"]))
    for line in profile_lines:
        if line:
            story.append(Paragraph(safe(line), styles["body"]))
    generated = generated_at.astimezone(UTC).strftime("%d %b %Y, %H:%M UTC")
    story.extend(
        [
            Spacer(1, 3 * mm),
            Paragraph(f"Generated {generated}", styles["caption"]),
            Paragraph(safe(notice), styles["caption"]),
            Spacer(1, 6 * mm),
        ]
    )
    return story


def branded_trust_score(
    *,
    overall: int,
    caption: str,
    styles: dict[str, ParagraphStyle],
    status_label: str | None = None,
    safe: Callable[[str], str],
) -> list:
    """Render the shared Trust Score hierarchy without recalculating the value."""

    story = [
        Paragraph("Trust Score", styles["section_title"]),
        Paragraph(f"{overall} / 100", styles["record_title"]),
    ]
    if status_label:
        story.append(Paragraph(safe(status_label), styles["status"]))
    story.extend([Paragraph(safe(caption), styles["caption"]), Spacer(1, 5 * mm)])
    return story


def branded_record(
    *,
    fields: Iterable[tuple[str, str]],
    verification_label: str,
    styles: dict[str, ParagraphStyle],
    safe: Callable[[str], str],
) -> list:
    """Render one record using the disclosure-scoped PDF's labeled-field layout."""

    record = [
        Paragraph(f"<b>{safe(label)}:</b> {safe(value)}", styles["body"])
        for label, value in fields
        if value
    ]
    record.append(Paragraph(safe(verification_label), styles["status"]))
    return [KeepTogether(record), Spacer(1, 5 * mm)]


def branded_footer(
    *,
    label: str,
    title: str,
    subject: str,
):
    """Return a page callback with consistent KairoID metadata and pagination."""

    def footer(pdf_canvas, document):  # noqa: ANN001
        pdf_canvas.saveState()
        pdf_canvas.setTitle(title)
        pdf_canvas.setAuthor("KairoID")
        pdf_canvas.setSubject(subject)
        pdf_canvas.setFont("KairoSans", 8)
        pdf_canvas.drawString(20 * mm, 12 * mm, label)
        pdf_canvas.drawRightString(A4[0] - 20 * mm, 12 * mm, f"Page {document.page}")
        pdf_canvas.restoreState()

    return footer
