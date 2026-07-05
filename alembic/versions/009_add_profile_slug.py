"""add profile_slug to users

Revision ID: 009
Revises: 008
Create Date: 2026-06-07
"""

from alembic import op
import sqlalchemy as sa
import re
import uuid

revision = "009"
down_revision = "008_social_accounts"
branch_labels = None
depends_on = None


def _slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:60] if slug else "user"


def upgrade() -> None:
    op.add_column("users", sa.Column("profile_slug", sa.String(100), nullable=True))

    # Backfill existing users with a slug derived from full_name or email
    conn = op.get_bind()
    users = conn.execute(sa.text("SELECT id, full_name, email FROM users WHERE profile_slug IS NULL")).fetchall()

    used: set[str] = set()
    for row in users:
        user_id, full_name, email = row
        base = _slugify(full_name) if full_name else _slugify(email.split("@")[0])
        slug = base
        # Ensure uniqueness
        while slug in used:
            slug = f"{base}-{uuid.uuid4().hex[:4]}"
        used.add(slug)
        conn.execute(
            sa.text("UPDATE users SET profile_slug = :slug WHERE id = :id"),
            {"slug": slug, "id": str(user_id)},
        )

    op.create_unique_constraint("uq_users_profile_slug", "users", ["profile_slug"])
    op.create_index("ix_users_profile_slug", "users", ["profile_slug"])


def downgrade() -> None:
    op.drop_index("ix_users_profile_slug", table_name="users")
    op.drop_constraint("uq_users_profile_slug", "users", type_="unique")
    op.drop_column("users", "profile_slug")
