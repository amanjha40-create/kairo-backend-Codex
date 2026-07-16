from enum import StrEnum


class ResumeReviewStatus(StrEnum):
    DRAFT = "draft"
    REVIEWING = "reviewing"
    READY_TO_IMPORT = "ready_to_import"
    IMPORTING = "importing"
    PARTIALLY_IMPORTED = "partially_imported"
    IMPORTED = "imported"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ResumeReviewItemStatus(StrEnum):
    PENDING = "pending"
    EDITED = "edited"
    SELECTED = "selected"
    DESELECTED = "deselected"
    INVALID = "invalid"
    IMPORTED = "imported"
    SKIPPED = "skipped"
    FAILED = "failed"


class ResumeImportAction(StrEnum):
    CREATE_NEW = "create_new"
    SKIP = "skip"
    LINK_EXISTING = "link_existing"
    UPDATE_EXISTING = "update_existing"


class DuplicateStatus(StrEnum):
    NO_MATCH = "no_match"
    POSSIBLE = "possible_match"
    PROBABLE = "probable_match"
    EXACT = "exact_match"
    CONFLICT = "conflict"
