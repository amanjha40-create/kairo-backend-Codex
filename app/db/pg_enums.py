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
from app.organization.enums import (
    OrganizationInvitationStatus,
    OrganizationRole,
    OrganizationType,
    OrganizationVerificationState,
)
from app.organization_people.enums import (
    OrganizationPersonIdentifierType,
    OrganizationPersonInvitationStatusSummary,
    OrganizationPersonLifecycleStatus,
    OrganizationPersonPassportAccessState,
    OrganizationPersonPassportStatusSummary,
    OrganizationPersonRelationship,
    OrganizationPersonTrustState,
    OrganizationPersonVerificationStatusSummary,
)
from app.trust_invitations.enums import (
    TrustInvitationDeliveryMethod,
    TrustInvitationDeliveryState,
    TrustInvitationStatus,
)
from app.verification_requests.enums import (
    VerificationContactReviewStatus,
    VerificationContactType,
    VerificationRequestEventSource,
    VerificationRequestOriginType,
    VerificationRequestStatus,
    VerificationRequestType,
)

verification_contact_type_enum = ENUM(
    *[m.value for m in VerificationContactType],
    name="verification_contact_type_enum",
    metadata=Base.metadata,
    create_type=False,
)

verification_contact_review_status_enum = ENUM(
    *[m.value for m in VerificationContactReviewStatus],
    name="verification_contact_review_status_enum",
    metadata=Base.metadata,
    create_type=False,
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

organization_verification_state_enum = ENUM(
    *[m.value for m in OrganizationVerificationState],
    name="organization_verification_state_enum",
    metadata=Base.metadata,
    create_type=False,
)

organization_invitation_status_enum = ENUM(
    *[m.value for m in OrganizationInvitationStatus],
    name="organization_invitation_status_enum",
    metadata=Base.metadata,
    create_type=False,
)

organization_person_relationship_enum = ENUM(
    *[m.value for m in OrganizationPersonRelationship],
    name="organization_person_relationship_enum",
    metadata=Base.metadata,
    create_type=False,
)

organization_person_lifecycle_status_enum = ENUM(
    *[m.value for m in OrganizationPersonLifecycleStatus],
    name="organization_person_lifecycle_status_enum",
    metadata=Base.metadata,
    create_type=False,
)

organization_person_trust_state_enum = ENUM(
    *[m.value for m in OrganizationPersonTrustState],
    name="organization_person_trust_state_enum",
    metadata=Base.metadata,
    create_type=False,
)

organization_person_invitation_status_summary_enum = ENUM(
    *[m.value for m in OrganizationPersonInvitationStatusSummary],
    name="organization_person_invitation_status_summary_enum",
    metadata=Base.metadata,
    create_type=False,
)

organization_person_verification_status_summary_enum = ENUM(
    *[m.value for m in OrganizationPersonVerificationStatusSummary],
    name="organization_person_verification_status_summary_enum",
    metadata=Base.metadata,
    create_type=False,
)

organization_person_passport_status_summary_enum = ENUM(
    *[m.value for m in OrganizationPersonPassportStatusSummary],
    name="organization_person_passport_status_summary_enum",
    metadata=Base.metadata,
    create_type=False,
)

organization_person_passport_access_state_enum = ENUM(
    *[m.value for m in OrganizationPersonPassportAccessState],
    name="organization_person_passport_access_state_enum",
    metadata=Base.metadata,
    create_type=False,
)

organization_person_identifier_type_enum = ENUM(
    *[m.value for m in OrganizationPersonIdentifierType],
    name="organization_person_identifier_type_enum",
    metadata=Base.metadata,
    create_type=False,
)

trust_invitation_status_enum = ENUM(
    *[m.value for m in TrustInvitationStatus],
    name="trust_invitation_status_enum",
    metadata=Base.metadata,
    create_type=False,
)

trust_invitation_delivery_method_enum = ENUM(
    *[m.value for m in TrustInvitationDeliveryMethod],
    name="trust_invitation_delivery_method_enum",
    metadata=Base.metadata,
    create_type=False,
)

trust_invitation_delivery_state_enum = ENUM(
    *[m.value for m in TrustInvitationDeliveryState],
    name="trust_invitation_delivery_state_enum",
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
