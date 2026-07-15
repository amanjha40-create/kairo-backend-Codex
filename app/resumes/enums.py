from enum import StrEnum


class ResumeUploadStatus(StrEnum):
    PENDING_UPLOAD = "pending_upload"
    UPLOADED = "uploaded"
    DELETED = "deleted"


class ResumeProcessingStatus(StrEnum):
    QUEUED = "queued"
    EXTRACTING = "extracting"
    EXTRACTED = "extracted"
    PARSING = "parsing"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DELETED = "deleted"
