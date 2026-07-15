from __future__ import annotations

import io
import zipfile
from pathlib import PurePosixPath

from app.exceptions import ValidationAppError

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ALLOWED = {PDF, DOCX}


def normalize_resume_filename(filename: str) -> str:
    name = PurePosixPath(filename.replace("\\", "/")).name
    if not name or name.startswith(".") or "." not in name:
        raise ValidationAppError("Resume filename must have a PDF or DOCX extension")
    stem, ext = name.rsplit(".", 1)
    ext = ext.lower()
    if ext not in {"pdf", "docx"}:
        raise ValidationAppError("Only PDF and DOCX resumes are supported")
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in stem).strip("._")
    return f"{safe[:200] or 'resume'}.{ext}"


def validate_resume_declaration(*, filename: str, content_type: str, byte_size: int, max_bytes: int) -> str:
    safe = normalize_resume_filename(filename)
    if content_type.split(";", 1)[0].strip().lower() not in ALLOWED:
        raise ValidationAppError("Only PDF and DOCX resumes are supported")
    if byte_size <= 0 or byte_size > max_bytes:
        raise ValidationAppError("Resume size is invalid or exceeds the configured limit")
    return safe


def validate_resume_bytes(data: bytes, *, content_type: str, max_bytes: int) -> str:
    if not data or len(data) > max_bytes:
        raise ValidationAppError("Resume content is empty or exceeds the configured limit")
    primary = content_type.split(";", 1)[0].strip().lower()
    if primary == PDF and data.startswith(b"%PDF-"):
        return primary
    if primary == DOCX and data.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = set(archive.namelist())
                if "[Content_Types].xml" in names and "word/document.xml" in names:
                    return primary
        except zipfile.BadZipFile:
            pass
    raise ValidationAppError("Uploaded resume signature does not match its declared type")
