"""Encrypted DigiLocker requester connections only.

Revision ID: 080
Revises: 079
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "080"
down_revision = "079"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "digilocker_connections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("encrypted_access_token", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("encrypted_refresh_token", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consent_valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("granted_scopes", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("pending_attempt_id", sa.UUID(), nullable=True),
        sa.Column("pending_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", name="uq_digilocker_connections_user_id"),
        sa.CheckConstraint(
            "status IN ('pending','active','reconnect_required','disconnected')", name="status"
        ),
        sa.CheckConstraint(
            "status != 'active' OR (encrypted_access_token IS NOT NULL "
            "AND token_expires_at IS NOT NULL AND connected_at IS NOT NULL)",
            name="active_token",
        ),
        sa.CheckConstraint(
            "status = 'active' OR (encrypted_access_token IS NULL "
            "AND encrypted_refresh_token IS NULL)",
            name="inactive_tokens_erased",
        ),
        sa.CheckConstraint(
            "encrypted_access_token IS NULL OR jsonb_typeof(encrypted_access_token) = 'object'",
            name="access_envelope",
        ),
        sa.CheckConstraint(
            "encrypted_refresh_token IS NULL OR jsonb_typeof(encrypted_refresh_token) = 'object'",
            name="refresh_envelope",
        ),
    )


def downgrade():
    op.drop_table("digilocker_connections")
