"""Optional Education institution catalogue provenance, without backfill."""

import sqlalchemy as sa

from alembic import op

revision = "095"
down_revision = "094"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("educations", sa.Column("institution_catalogue_id", sa.String(80), nullable=True))
    op.add_column(
        "educations", sa.Column("institution_catalogue_version", sa.String(32), nullable=True)
    )


def downgrade():
    op.drop_column("educations", "institution_catalogue_version")
    op.drop_column("educations", "institution_catalogue_id")
