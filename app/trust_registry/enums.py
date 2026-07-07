"""Trust Registry enums used across schemas and services."""

from __future__ import annotations

from enum import StrEnum


class TrustRegistryLifecycleStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    RESTRICTED = "restricted"
    ARCHIVED = "archived"


class TrustRegistryTrustStatus(StrEnum):
    UNREVIEWED = "unreviewed"
    REVIEW_IN_PROGRESS = "review_in_progress"
    TRUSTED = "trusted"
    LIMITED_TRUST = "limited_trust"
    UNTRUSTED = "untrusted"


class TrustRegistrySourceType(StrEnum):
    MANUAL = "manual"
    SUBJECT_SUBMISSION = "subject_submission"
    ORGANIZATION_SUBMISSION = "organization_submission"
    GOVERNMENT_IMPORT = "government_import"
    PUBLIC_DIRECTORY = "public_directory"
    PARTNER_API = "partner_api"
    AI_SUGGESTION = "ai_suggestion"
    BULK_IMPORT = "bulk_import"


class TrustRegistryCapabilityStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    LIMITED = "limited"


class TrustRegistryIdentifierStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"
    INVALID = "invalid"


class TrustRegistryRelationshipStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class TrustRegistryAliasType(StrEnum):
    ALTERNATE_NAME = "alternate_name"
    FORMER_NAME = "former_name"
    ABBREVIATION = "abbreviation"
    BRAND_NAME = "brand_name"


class TrustRegistryRelationshipType(StrEnum):
    PARENT_CHILD = "parent_child"
    BRANCH_OF = "branch_of"
    SUBSIDIARY_OF = "subsidiary_of"
    DEPARTMENT_OF = "department_of"
    CAMPUS_OF = "campus_of"
    UNIT_OF = "unit_of"
    AFFILIATE_OF = "affiliate_of"


class TrustRegistryResolutionState(StrEnum):
    UNRESOLVED = "unresolved"
    RESOLVED = "resolved"
    DEFERRED = "deferred"


class TrustRegistryResolutionMethod(StrEnum):
    EXACT_NAME = "exact_name"
    EXACT_DOMAIN = "exact_domain"
    EXACT_IDENTIFIER = "exact_identifier"
    MANUAL = "manual"
    AI_SUGGESTED = "ai_suggested"
    CREATED_NEW = "created_new"

