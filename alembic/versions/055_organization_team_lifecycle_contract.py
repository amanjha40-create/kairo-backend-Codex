"""Harden organization team invitations.

Revision ID: 055
Revises: 054
Create Date: 2026-07-25
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE organization_invitations
        SET invitee_email = lower(btrim(invitee_email))
        WHERE invitee_email <> lower(btrim(invitee_email))
        """
    )

    op.execute(
        sa.text(
            """
            UPDATE organization_invitations
            SET status = CAST(:expired_status AS organization_invitation_status_enum)
            WHERE status = CAST(:pending_status AS organization_invitation_status_enum)
              AND accepted_at IS NULL
              AND declined_at IS NULL
              AND cancelled_at IS NULL
              AND expires_at IS NOT NULL
              AND expires_at <= now()
            """
        ).bindparams(
            expired_status="expired",
            pending_status="pending",
        )
    )

    op.execute(
        sa.text(
            """
            WITH ranked_pending AS (
                SELECT
                    id,
                    row_number() OVER (
                        PARTITION BY organization_id, lower(invitee_email)
                        ORDER BY created_at DESC, id DESC
                    ) AS rank
                FROM organization_invitations
                WHERE status = CAST(:pending_status AS organization_invitation_status_enum)
                  AND accepted_at IS NULL
                  AND declined_at IS NULL
                  AND cancelled_at IS NULL
            )
            UPDATE organization_invitations AS invitations
            SET status = CAST(:cancelled_status AS organization_invitation_status_enum),
                cancelled_at = COALESCE(invitations.cancelled_at, now())
            FROM ranked_pending
            WHERE invitations.id = ranked_pending.id
              AND ranked_pending.rank > 1
            """
        ).bindparams(
            pending_status="pending",
            cancelled_status="cancelled",
        )
    )

    op.execute(
        """
        CREATE UNIQUE INDEX uq_organization_invitations_active_pending_email
        ON organization_invitations (organization_id, lower(invitee_email))
        WHERE status = 'pending'
          AND accepted_at IS NULL
          AND declined_at IS NULL
          AND cancelled_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index(
        "uq_organization_invitations_active_pending_email",
        table_name="organization_invitations",
    )
