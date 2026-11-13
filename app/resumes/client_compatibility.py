"""Request-scoped compatibility rules for Resume review contracts."""

from app.employment.client_compatibility import current_client_metadata

EXPLICIT_RESUME_REVIEW_CAPABILITY = "resume-explicit-review-v1"
IMPORT_FIRST_RESUME_CAPABILITY = "resume-import-first-v1"


def explicit_resume_review_capable() -> bool:
    """Use strict review decisions only for clients that advertise support."""

    return EXPLICIT_RESUME_REVIEW_CAPABILITY in current_client_metadata().capabilities


def import_first_resume_capable() -> bool:
    """Allow safe automatic imports without changing legacy client behavior."""

    capabilities = current_client_metadata().capabilities
    # A malformed/mixed client must not use import-first to bypass the stricter
    # explicit-review contract. Current clients advertise exactly one mode.
    return (
        IMPORT_FIRST_RESUME_CAPABILITY in capabilities
        and EXPLICIT_RESUME_REVIEW_CAPABILITY not in capabilities
    )
