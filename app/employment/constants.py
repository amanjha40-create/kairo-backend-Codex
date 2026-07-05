"""Cross-cutting employment verification constants."""

from __future__ import annotations

# SHA-256 of empty byte string — sentinel until upload completion replaces with real digest.
PENDING_UPLOAD_CHECKSUM_HEX = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

DOCUMENT_EXTRACTION_JOB_TYPE = "employment.document.extract"

# Async worker / queue job types (pair with SQS handler registry).
VERIFICATION_REVIEW_TRIAGE_JOB_TYPE = "employment.verification.review_triage"

# Audit metadata discriminator for timeline (avoids new PostgreSQL enum values).
TIMELINE_META_AI_PIPELINE_KIND = "ai_pipeline_prepared"
