"""PostgreSQL-native ENUM types — created by Alembic (`create_type=False` at runtime).

SQLAlchemy maps Python layer to these types without emitting CREATE TYPE on `metadata.create_all`.
"""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import ENUM

from app.admin_review.enums import (
    VerificationRequestEvidenceStatus,
    VerificationRequestReviewStatus,
    VerificationReviewCorrectionStatus,
    VerificationReviewNoteType,
    VerificationReviewNoteVisibility,
)
from app.db.base import Base
from app.employment.enums import (
    DocumentExtractionStatus,
    EmploymentDocumentType,
    EmploymentType,
    VerificationAuditAction,
    VerificationStatus,
)
from app.organization.enums import OrganizationRole, OrganizationType
from app.trust_invitations.enums import TrustInvitationStatus
from app.verification_requests.enums import (
    VerificationRequestEventSource,
    VerificationRequestOriginType,
    VerificationRequestStatus,
    VerificationRequestType,
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

organization_type_enum = ENUM(
    *[m.value for m in OrganizationType],
    name="organization_type_enum",
    metadata=Base.metadata,
    create_type=False,
)

organization_role_enum = ENUM(
    *[m.value for m in OrganizationRole],
    name="organization_role_enum",
    metadata=Base.metadata,
    create_type=False,
)

trust_invitation_status_enum = ENUM(
    *[m.value for m in TrustInvitationStatus],
    name="trust_invitation_status_enum",
    metadata=Base.metadata,
    create_type=False,
)

verification_request_type_enum = ENUM(
    *[m.value for m in VerificationRequestType],
    name="verification_request_type_enum",
    metadata=Base.metadata,
    create_type=False,
)

verification_request_origin_type_enum = ENUM(
    *[m.value for m in VerificationRequestOriginType],
    name="verification_request_origin_type_enum",
    metadata=Base.metadata,
    create_type=False,
)

verification_request_status_enum = ENUM(
    *[m.value for m in VerificationRequestStatus],
    name="verification_request_status_enum",
    metadata=Base.metadata,
    create_type=False,
)

verification_request_event_source_enum = ENUM(
    *[m.value for m in VerificationRequestEventSource],
    name="verification_request_event_source_enum",
    metadata=Base.metadata,
    create_type=False,
)

verification_request_review_status_enum = ENUM(
    *[m.value for m in VerificationRequestReviewStatus],
    name="verification_request_review_status_enum",
    metadata=Base.metadata,
    create_type=False,
)

verification_review_note_visibility_enum = ENUM(
    *[m.value for m in VerificationReviewNoteVisibility],
    name="verification_review_note_visibility_enum",
    metadata=Base.metadata,
    create_type=False,
)

verification_review_note_type_enum = ENUM(
    *[m.value for m in VerificationReviewNoteType],
    name="verification_review_note_type_enum",
    metadata=Base.metadata,
    create_type=False,
)

verification_review_correction_status_enum = ENUM(
    *[m.value for m in VerificationReviewCorrectionStatus],
    name="verification_review_correction_status_enum",
    metadata=Base.metadata,
    create_type=False,
)

verification_request_evidence_status_enum = ENUM(
    *[m.value for m in VerificationRequestEvidenceStatus],
    name="verification_request_evidence_status_enum",
    metadata=Base.metadata,
    create_type=False,
)
