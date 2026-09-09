"""Canonical header-only CSV templates for organization roster imports."""

from __future__ import annotations

import csv
import io

from app.organization_roster_import.enums import OrganizationRosterType
from app.organization_roster_import.headers import template_columns

EMPLOYEE_TEMPLATE_FILENAME = "kairo-employee-roster-template.csv"
STUDENT_TEMPLATE_FILENAME = "kairo-student-roster-template.csv"


def build_roster_template(roster_type: OrganizationRosterType) -> tuple[str, str]:
    filename = (
        EMPLOYEE_TEMPLATE_FILENAME
        if roster_type is OrganizationRosterType.EMPLOYEE
        else STUDENT_TEMPLATE_FILENAME
    )
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow([display_name for display_name, _ in template_columns(roster_type)])
    return filename, output.getvalue()
