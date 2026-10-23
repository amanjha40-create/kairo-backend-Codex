"""Optional catalogue provenance; never an organization or verification identity."""

from typing import Any

from app.catalogues.institutions import CATALOGUE_VERSION, load_catalogue
from app.exceptions import ValidationAppError

FIELDS = ("institution_catalogue_id", "institution_catalogue_version")


def education_identity(payload: dict[str, Any], current: Any = None) -> dict[str, Any]:
    """Validate explicit selections, clear stale selections, preserve manual names."""
    result = dict(payload)

    def previous(key: str) -> Any:
        return current.get(key) if isinstance(current, dict) else getattr(current, key, None)

    name = result.get("institution_name", previous("institution_name"))
    changed = current is not None and name != previous("institution_name")
    identifier, version = (result.get(field) for field in FIELDS)
    # Full-form clients may echo the old selection alongside a manually edited name.
    stale = changed and all(result.get(field) == previous(field) for field in FIELDS)
    if stale or not identifier and not version:
        if changed or any(field in result for field in FIELDS) or current is None:
            result.update(dict.fromkeys(FIELDS))
        return result
    if not identifier or not version:
        raise ValidationAppError(
            "Select an institution again or enter it manually", code="invalid_institution_selection"
        )
    if (
        current is not None
        and not changed
        and all(result.get(field) == previous(field) for field in FIELDS)
    ):
        return result
    try:
        _, rows = load_catalogue()
    except (OSError, ValueError, KeyError, TypeError, AssertionError):
        raise ValidationAppError(
            "Catalogue unavailable; enter the institution manually",
            code="institution_catalogue_unavailable",
        ) from None
    row = next((row for row in rows if row["id"] == identifier), None)
    if version != CATALOGUE_VERSION or row is None or name != row["name"]:
        raise ValidationAppError(
            "Select an institution again or enter it manually", code="invalid_institution_selection"
        )
    return result
