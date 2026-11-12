"""Persist Client attribution for Candidate activation invitations.

Revision ID: 099
Revises: 098
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "099"
down_revision = "098"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidate_activation_tokens",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "candidate_activation_tokens",
        sa.Column("organization_person_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_candidate_activation_tokens_organization_id",
        "candidate_activation_tokens",
        ["organization_id"],
    )
    op.create_index(
        "ix_candidate_activation_tokens_organization_person_id",
        "candidate_activation_tokens",
        ["organization_person_id"],
    )
    op.create_foreign_key(
        "fk_candidate_activation_tokens_organization_id",
        "candidate_activation_tokens",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_candidate_activation_tokens_organization_person_id",
        "candidate_activation_tokens",
        "organization_people",
        ["organization_person_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_candidate_activation_tokens_organization_person_id",
        "candidate_activation_tokens",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_candidate_activation_tokens_organization_id",
        "candidate_activation_tokens",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_candidate_activation_tokens_organization_person_id",
        table_name="candidate_activation_tokens",
    )
    op.drop_index(
        "ix_candidate_activation_tokens_organization_id",
        table_name="candidate_activation_tokens",
    )
    op.drop_column("candidate_activation_tokens", "organization_person_id")
    op.drop_column("candidate_activation_tokens", "organization_id")
