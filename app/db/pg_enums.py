"""PostgreSQL-native ENUM types — created by Alembic (`create_type=False` at runtime).

SQLAlchemy maps Python layer to these types without emitting CREATE TYPE on `metadata.create_all`.
"""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import ENUM

from app.db.base import Base
from app.employment.enums import (
    DocumentExtractionStatus,
    EmploymentDocumentType,
    EmploymentType,
    VerificationAuditAction,
    VerificationStatus,
)

verification_status_enum = ENUM(
    *[m.value for m in VerificationStatus],
    name="verification_status_enum",
    metadata=Base.metadata,
    create_type=False,
)

employment_type_enum = ENUM(
    *[m.value for m in EmploymentType],
    name="employment_type_enum",
    metadata=Base.metadata,
    create_type=False,
)

employment_document_type_enum = ENUM(
    *[m.value for m in EmploymentDocumentType],
    name="employment_document_type_enum",
    metadata=Base.metadata,
    create_type=False,
)

document_extraction_status_enum = ENUM(
    *[m.value for m in DocumentExtractionStatus],
    name="document_extraction_status_enum",
    metadata=Base.metadata,
    create_type=False,
)

verification_audit_action_enum = ENUM(
    *[m.value for m in VerificationAuditAction],
    name="verification_audit_action_enum",
    metadata=Base.metadata,
    create_type=False,
)
