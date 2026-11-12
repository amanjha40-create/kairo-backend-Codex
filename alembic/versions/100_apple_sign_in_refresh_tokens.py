"""Store encrypted Apple refresh tokens for account-deletion revocation.

Revision ID: 100
Revises: 099
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "100"
down_revision = "099"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_social_accounts",
        sa.Column(
            "encrypted_refresh_token",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "pending_signups",
        sa.Column(
            "oauth_refresh_token_encrypted",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("pending_signups", "oauth_refresh_token_encrypted")
    op.drop_column("user_social_accounts", "encrypted_refresh_token")
