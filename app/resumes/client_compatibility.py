"""Request-scoped compatibility rules for Resume review contracts."""

from app.employment.client_compatibility import current_client_metadata

EXPLICIT_RESUME_REVIEW_CAPABILITY = "resume-explicit-review-v1"


def explicit_resume_review_capable() -> bool:
    """Use strict review decisions only for clients that advertise support."""

    return EXPLICIT_RESUME_REVIEW_CAPABILITY in current_client_metadata().capabilities
