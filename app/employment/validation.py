"""Additional employment period validation beyond Pydantic request bodies."""

from __future__ import annotations

from app.exceptions.employment_domain import EmploymentDateValidationError
from app.models.employment import Employment


def validate_period_after_patch(row: Employment) -> None:
    """Ensure start/end ordering after ORM fields are mutated."""

    if row.end_date is not None and row.end_date < row.start_date:
        raise EmploymentDateValidationError("end_date cannot be before start_date")
