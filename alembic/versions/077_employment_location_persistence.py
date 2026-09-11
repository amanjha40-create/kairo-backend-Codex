"""Persist Employment city and work arrangement.

Revision ID: 077
Revises: 076
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "077"
down_revision = "076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"]: column for column in inspector.get_columns("employments")}

    if "work_location_city" not in columns:
        op.add_column(
            "employments",
            sa.Column("work_location_city", sa.String(length=128), nullable=True),
        )
    else:
        op.alter_column(
            "employments",
            "work_location_city",
            existing_type=columns["work_location_city"]["type"],
            type_=sa.String(length=128),
            nullable=True,
        )

    if "work_arrangement" not in columns:
        op.add_column(
            "employments",
            sa.Column("work_arrangement", sa.String(length=16), nullable=True),
        )
    else:
        op.execute(
            "ALTER TABLE employments ALTER COLUMN work_arrangement "
            "TYPE VARCHAR(16) USING work_arrangement::text"
        )
        op.alter_column("employments", "work_arrangement", nullable=True)

    check_constraints = {
        constraint["name"]
        for constraint in sa.inspect(bind).get_check_constraints("employments")
    }
    if "ck_employments_work_arrangement" not in check_constraints:
        op.create_check_constraint(
            "ck_employments_work_arrangement",
            "employments",
            "work_arrangement IS NULL OR work_arrangement IN ('onsite', 'hybrid', 'remote')",
        )

    # A pre-Alembic staging prototype used this enum for the same nullable field.
    op.execute("DROP TYPE IF EXISTS work_arrangement_enum")


def downgrade() -> None:
    op.drop_constraint(
        "ck_employments_work_arrangement",
        "employments",
        type_="check",
    )
    op.drop_column("employments", "work_arrangement")
    op.drop_column("employments", "work_location_city")
