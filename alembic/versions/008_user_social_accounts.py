"""Replace google_id column with generic user_social_accounts table.

Revision ID: 008_social_accounts
Revises: 007_google_oauth
Create Date: 2026-05-25

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "008_social_accounts"
down_revision = "007_google_oauth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the new table
    op.create_table(
        "user_social_accounts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_user_id", sa.String(255), nullable=False),
        sa.Column("provider_email", sa.String(320), nullable=True),
        sa.Column("linked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("provider", "provider_user_id", name="uq_social_provider_user"),
        sa.UniqueConstraint("user_id", "provider", name="uq_social_user_provider"),
    )
    op.create_index("ix_user_social_accounts_user_id", "user_social_accounts", ["user_id"])

    # Migrate existing google_id data into the new table
    op.execute("""
        INSERT INTO user_social_accounts (id, user_id, provider, provider_user_id, provider_email, linked_at)
        SELECT gen_random_uuid(), id, 'google', google_id, email, NOW()
        FROM users
        WHERE google_id IS NOT NULL
    """)

    # Drop the google_id column from users
    op.drop_index("ix_users_google_id", table_name="users")
    op.drop_column("users", "google_id")


def downgrade() -> None:
    op.add_column("users", sa.Column("google_id", sa.String(255), nullable=True))
    op.create_index("ix_users_google_id", "users", ["google_id"], unique=True)

    # Restore google_id from social accounts table
    op.execute("""
        UPDATE users u
        SET google_id = s.provider_user_id
        FROM user_social_accounts s
        WHERE s.user_id = u.id AND s.provider = 'google'
    """)

    op.drop_index("ix_user_social_accounts_user_id", table_name="user_social_accounts")
    op.drop_table("user_social_accounts")
