"""Permanent organization closure and transactional deletion ownership audit.

Revision ID: 094
Revises: 093
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "094"
down_revision = "093"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("organizations", sa.Column("closed_at", sa.DateTime(timezone=True)))
    op.add_column("organizations", sa.Column("closure_deletion_id", postgresql.UUID(as_uuid=True)))
    op.create_foreign_key(
        "fk_organizations_closure_deletion",
        "organizations",
        "account_deletions",
        ["closure_deletion_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_organizations_closure",
        "organizations",
        "(closed_at IS NULL AND closure_deletion_id IS NULL) OR "
        "(closed_at IS NOT NULL AND closure_deletion_id IS NOT NULL AND suspended_at IS NOT NULL)",
    )
    op.create_table(
        "organization_deletion_resolutions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "deletion_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("account_deletions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column(
            "successor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
        ),
        sa.UniqueConstraint("deletion_id", "organization_id", name="uq_org_deletion_resolution"),
        sa.CheckConstraint("action IN ('leave', 'transfer', 'close')", name="action"),
        sa.CheckConstraint(
            "(action = 'transfer') = (successor_user_id IS NOT NULL)", name="successor"
        ),
    )
    # Keep older suspended-workspace guards effective; permanent closure cannot
    # be undone by an administrative unsuspend or a stale ORM update.
    op.execute("""
        CREATE FUNCTION guard_permanent_organization_closure() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
          IF OLD.closed_at IS NOT NULL AND (
            NEW.closed_at IS DISTINCT FROM OLD.closed_at OR
            NEW.closure_deletion_id IS DISTINCT FROM OLD.closure_deletion_id OR
            NEW.suspended_at IS NULL
          ) THEN
            RAISE EXCEPTION 'organization_permanently_closed';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER organization_closure_immutable BEFORE UPDATE ON organizations
        FOR EACH ROW EXECUTE FUNCTION guard_permanent_organization_closure();
    """)
    # Every membership mutation takes the same organization lock as closure.
    # NOWAIT on user rows prevents inverse user/org lock order from deadlocking;
    # callers fail atomically rather than transferring to an in-flight deletion.
    op.execute("""
        CREATE FUNCTION guard_organization_membership_lifecycle() RETURNS trigger
        LANGUAGE plpgsql AS $$ DECLARE org_closed timestamptz; eligible boolean; BEGIN
          IF TG_OP = 'DELETE' THEN
            PERFORM 1 FROM organizations WHERE id = OLD.organization_id FOR UPDATE NOWAIT;
            RETURN OLD;
          END IF;
          IF TG_OP = 'UPDATE' AND NEW.organization_id <> OLD.organization_id THEN
            RAISE EXCEPTION 'organization_membership_reparent_forbidden';
          END IF;
          SELECT closed_at INTO org_closed FROM organizations
            WHERE id = NEW.organization_id FOR UPDATE NOWAIT;
          IF org_closed IS NOT NULL THEN
            RAISE EXCEPTION 'organization_permanently_closed';
          END IF;
          SELECT (is_active AND deleted_at IS NULL) INTO eligible FROM users
            WHERE id = NEW.user_id FOR UPDATE NOWAIT;
          IF eligible IS DISTINCT FROM TRUE THEN
            RAISE EXCEPTION 'organization_member_ineligible';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER organization_membership_lifecycle
        BEFORE INSERT OR UPDATE OR DELETE ON organization_members
        FOR EACH ROW EXECUTE FUNCTION guard_organization_membership_lifecycle();
    """)
    op.execute("""
        CREATE FUNCTION guard_closed_organization_grant() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE payload jsonb; org_id uuid; org_closed timestamptz;
        BEGIN
          payload := to_jsonb(NEW);
          org_id := (payload->>'organization_id')::uuid;
          IF org_id IS NULL AND payload->>'organization_person_id' IS NOT NULL THEN
            SELECT organization_id INTO org_id FROM organization_people
              WHERE id = (payload->>'organization_person_id')::uuid;
          END IF;
          IF org_id IS NULL AND payload->>'verification_request_id' IS NOT NULL THEN
            SELECT organization_id INTO org_id FROM verification_requests
              WHERE id = (payload->>'verification_request_id')::uuid;
          END IF;
          IF org_id IS NULL THEN RETURN NEW; END IF;
          SELECT closed_at INTO org_closed FROM organizations WHERE id = org_id FOR UPDATE;
          IF org_closed IS NOT NULL THEN
            RAISE EXCEPTION 'organization_permanently_closed';
          END IF;
          RETURN NEW;
        END $$;
    """)
    # Token/grant creation or reactivation is serialized with closure. Retained
    # history scrubbing/revocation remains permitted after closure.
    for table, columns in (
        ("organization_invitations", "token_hash, token_revoked_at"),
        ("trust_invitations", "token_hash"),
        ("organization_logo_uploads", "object_key, expires_at"),
        ("organization_roster_imports", "source_storage_key"),
        ("organization_people", "organization_id"),
        ("verification_requests", "organization_id"),
        ("organization_person_passport_access", "permissions_snapshot, revoked_at"),
        ("institution_verification_requests", "token_hash, revoked_at"),
        ("employer_verification_requests", "token_hash, revoked_at"),
    ):
        op.execute(f"""
            CREATE TRIGGER closed_org_insert BEFORE INSERT ON {table}
            FOR EACH ROW EXECUTE FUNCTION guard_closed_organization_grant()
        """)
        if table == "organization_invitations":
            predicate = "NEW.token_hash IS NOT NULL AND NEW.token_revoked_at IS NULL"
        elif table in {
            "organization_person_passport_access",
            "institution_verification_requests",
            "employer_verification_requests",
        }:
            predicate = "NEW.revoked_at IS NULL"
        elif table == "trust_invitations":
            predicate = "NEW.cancelled_at IS NULL AND NEW.expires_at > now()"
        else:
            predicate = "TRUE"
        op.execute(f"""
            CREATE TRIGGER closed_org_regrant BEFORE UPDATE OF {columns} ON {table}
            FOR EACH ROW WHEN ({predicate})
            EXECUTE FUNCTION guard_closed_organization_grant()
        """)


def downgrade():
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM organization_deletion_resolutions) OR
             EXISTS (SELECT 1 FROM organizations WHERE closed_at IS NOT NULL) THEN
            RAISE EXCEPTION 'cannot_discard_organization_deletion_history';
          END IF;
        END $$;
    """)
    for table in (
        "organization_invitations",
        "trust_invitations",
        "organization_logo_uploads",
        "organization_roster_imports",
        "organization_people",
        "verification_requests",
        "organization_person_passport_access",
        "institution_verification_requests",
        "employer_verification_requests",
    ):
        op.execute(f"DROP TRIGGER closed_org_insert ON {table}")
        op.execute(f"DROP TRIGGER closed_org_regrant ON {table}")
    op.execute("DROP FUNCTION guard_closed_organization_grant()")
    op.execute("DROP TRIGGER organization_membership_lifecycle ON organization_members")
    op.execute("DROP FUNCTION guard_organization_membership_lifecycle()")
    op.execute("DROP TRIGGER organization_closure_immutable ON organizations")
    op.execute("DROP FUNCTION guard_permanent_organization_closure()")
    op.drop_table("organization_deletion_resolutions")
    op.drop_constraint("ck_organizations_closure", "organizations", type_="check")
    op.drop_constraint("fk_organizations_closure_deletion", "organizations", type_="foreignkey")
    op.drop_column("organizations", "closure_deletion_id")
    op.drop_column("organizations", "closed_at")
