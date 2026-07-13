"""Static catalog of employment evidence types and upload constraints for clients."""

from __future__ import annotations

from app.config import Settings
from app.employment.enums import EmploymentDocumentType, VerificationMethod


def _document_type_options() -> list[dict[str, str]]:
    labels: dict[EmploymentDocumentType, tuple[str, str]] = {
        EmploymentDocumentType.PAY_STUB: (
            "Pay stub / Payslip",
            "Recent payslip showing employer and pay period.",
        ),
        EmploymentDocumentType.OFFER_LETTER: (
            "Offer letter",
            "Signed or official offer letter from the employer.",
        ),
        EmploymentDocumentType.APPOINTMENT_LETTER: (
            "Appointment letter",
            "Official appointment letter issued by the employer.",
        ),
        EmploymentDocumentType.EXPERIENCE_LETTER: (
            "Experience letter",
            "Employer-issued letter confirming role and tenure.",
        ),
        EmploymentDocumentType.PAYSLIP: (
            "Payslip",
            "Recent payslip showing employer and pay period.",
        ),
        EmploymentDocumentType.EMPLOYMENT_ID_CARD: (
            "Employment ID card",
            "Employer-issued identification card.",
        ),
        EmploymentDocumentType.CONTRACT: (
            "Contract",
            "Signed contract supporting the employment relationship.",
        ),
        EmploymentDocumentType.BANK_STATEMENT: (
            "Bank statement",
            "Statement containing an identifiable employer salary credit.",
        ),
        EmploymentDocumentType.FORM_W2: (
            "Form W-2",
            "US W-2 tax form for the employment year.",
        ),
        EmploymentDocumentType.FORM_1099: (
            "Form 1099",
            "US 1099 form for contractor income.",
        ),
        EmploymentDocumentType.EMPLOYMENT_CONTRACT: (
            "Employment contract",
            "Signed employment or appointment contract.",
        ),
        EmploymentDocumentType.HR_LETTER: (
            "HR letter",
            "HR or employer letter confirming employment.",
        ),
        EmploymentDocumentType.RELIEVING_LETTER: (
            "Relieving / experience letter",
            "Letter issued when leaving the company.",
        ),
        EmploymentDocumentType.GOVERNMENT_ID: (
            "Government ID",
            "Government-issued ID used only when required as employment proof.",
        ),
        EmploymentDocumentType.OTHER: (
            "Other employment proof",
            "Other document that supports this role (admin will review).",
        ),
    }
    return [
        {
            "value": doc_type.value,
            "label": labels[doc_type][0],
            "description": labels[doc_type][1],
        }
        for doc_type in EmploymentDocumentType
    ]


def _content_type_options(settings: Settings) -> list[dict[str, object]]:
    mime_labels: dict[str, tuple[str, list[str]]] = {
        "application/pdf": ("PDF", [".pdf"]),
        "image/jpeg": ("JPEG image", [".jpg", ".jpeg"]),
        "image/png": ("PNG image", [".png"]),
        "image/webp": ("WebP image", [".webp"]),
        "application/msword": ("Word document (.doc)", [".doc"]),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
            "Word document (.docx)",
            [".docx"],
        ),
    }
    items: list[dict[str, object]] = []
    for mime in settings.s3_allowed_upload_content_types:
        label, extensions = mime_labels.get(mime, (mime, []))
        items.append(
            {
                "mime_type": mime,
                "label": label,
                "extensions": extensions,
            }
        )
    return items


def _verification_method_options() -> list[dict[str, str]]:
    return [
        {
            "value": VerificationMethod.DOCUMENT.value,
            "label": "Upload documents",
            "description": "Upload payslips, offer letters, or other proof for admin review.",
        },
        {
            "value": VerificationMethod.EMPLOYER_CONFIRMATION.value,
            "label": "Employer confirmation",
            "description": "Email your employer or manager a secure link to confirm employment.",
        },
    ]


def build_document_upload_options(settings: Settings) -> dict[str, object]:
    """JSON-serializable upload catalog for mobile/web clients."""

    return {
        "verification_methods": _verification_method_options(),
        "document_types": _document_type_options(),
        "allowed_content_types": _content_type_options(settings),
        "max_upload_bytes": settings.employment_max_upload_bytes,
        "presigned_put_ttl_seconds": settings.s3_presigned_put_ttl_seconds,
        "extraction_enabled": False,
        "upload_steps": [
            "POST /api/v1/employments/{employment_id}/documents/upload-intent",
            "PUT file bytes to upload_url (headers from headers_required)",
            "POST /api/v1/employments/{employment_id}/documents/{document_id}/complete-upload",
        ],
    }
