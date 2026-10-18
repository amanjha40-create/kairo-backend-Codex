"""Stable string enums for additive Admin Operations persistence."""

from __future__ import annotations

from enum import StrEnum


class CandidateClaimStatus(StrEnum):
    ADMIN_CREATED_UNCLAIMED = "admin_created_unclaimed"
    ACTIVATION_PENDING = "activation_pending"
    CLAIMED = "claimed"


class ProfileProvenanceSource(StrEnum):
    ADMIN_ENTERED = "admin_entered"
    CV_EXTRACTED = "cv_extracted"
    CANDIDATE_CONFIRMED = "candidate_confirmed"
    SOURCE_VERIFIED = "source_verified"


class CourtCheckStatus(StrEnum):
    PENDING = "pending"
    NO_MATCH_FOUND = "no_match_found"
    MATCH_FOUND = "match_found"
    REVIEW_REQUIRED = "review_required"
    UNABLE_TO_COMPLETE = "unable_to_complete"


class InPersonVerificationType(StrEnum):
    """Only types with a policy that permits observational in-person evidence."""

    IDENTITY_OBSERVATION = "identity_observation"
    DOCUMENT_OBSERVATION = "document_observation"


class InPersonVerificationResult(StrEnum):
    OBSERVED_CONSISTENT = "observed_consistent"
    DISCREPANCY = "discrepancy"
    UNABLE_TO_COMPLETE = "unable_to_complete"
