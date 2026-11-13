"""Request-scoped compatibility rules for Resume review contracts."""

from app.employment.client_compatibility import current_client_metadata

EXPLICIT_RESUME_REVIEW_CAPABILITY = "resume-explicit-review-v1"
IMPORT_FIRST_RESUME_CAPABILITY = "resume-import-first-v1"


def explicit_resume_review_capable() -> bool:
    """Use strict review decisions only for clients that advertise support."""

    return EXPLICIT_RESUME_REVIEW_CAPABILITY in current_client_metadata().capabilities


def import_first_resume_capable() -> bool:
    """Allow safe automatic imports without changing legacy client behavior."""

    return IMPORT_FIRST_RESUME_CAPABILITY in current_client_metadata().capabilities
