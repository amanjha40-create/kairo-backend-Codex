"""Admin Operations V1.1 assisted account and verification contracts.

Revision ID: 093
Revises: 092
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "093"
down_revision = "092"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column("claim_status", sa.String(length=32), server_default="claimed", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("admin_created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "users", sa.Column("admin_created_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("users", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "assisted_creation_idempotency_key", postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.create_foreign_key(
        "fk_users_admin_created_by_user_id_users",
        "users",
        "users",
        ["admin_created_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_users_claim_status", "users", ["claim_status"])
    op.create_index(
        "ix_users_admin_created_by_user_id", "users", ["admin_created_by_user_id"]
    )
    op.create_unique_constraint(
        "uq_users_assisted_creation_idempotency_key",
        "users",
        ["assisted_creation_idempotency_key"],
    )
    op.create_check_constraint(
        "ck_users_claim_status",
        "users",
        "claim_status IN ('admin_created_unclaimed', 'activation_pending', 'claimed')",
    )

    op.add_column(
        "organizations",
        sa.Column("provisioned_by_admin_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "organizations", sa.Column("provisioned_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "organizations",
        sa.Column(
            "admin_provisioning_idempotency_key", postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.create_foreign_key(
        "fk_organizations_provisioned_by_admin_user_id_users",
        "organizations",
        "users",
        ["provisioned_by_admin_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_organizations_provisioned_by_admin_user_id",
        "organizations",
        ["provisioned_by_admin_user_id"],
    )
    op.create_unique_constraint(
        "uq_organizations_admin_provisioning_idempotency_key",
        "organizations",
        ["admin_provisioning_idempotency_key"],
    )

    op.add_column(
        "organization_invitations",
        sa.Column("invitee_name", sa.String(length=255), nullable=True),
    )

    op.add_column(
        "resume_record_provenance",
        sa.Column(
            "confirmation_source",
            sa.String(length=48),
            server_default="candidate_confirmed",
            nullable=False,
        ),
    )
    op.add_column(
        "resume_record_provenance",
        sa.Column("confirmed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_resume_record_provenance_confirmed_by_user_id_users",
        "resume_record_provenance",
        "users",
        ["confirmed_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "candidate_activation_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_version", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivery_failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_candidate_activation_tokens_user_id", "candidate_activation_tokens", ["user_id"]
    )
    op.create_index(
        "ix_candidate_activation_tokens_created_by_user_id",
        "candidate_activation_tokens",
        ["created_by_user_id"],
    )
    op.create_index(
        "ix_candidate_activation_tokens_expires_at",
        "candidate_activation_tokens",
        ["expires_at"],
    )

    op.create_table(
        "admin_profile_provenance",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("record_type", sa.String(length=32), nullable=False),
        sa.Column("record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("field_name", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("value_hash", sa.String(length=64), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("candidate_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "source IN ('admin_entered', 'cv_extracted', 'candidate_confirmed', 'source_verified')",
            name="ck_admin_profile_provenance_source",
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("user_id", "record_type", "record_id", "field_name", "source"):
        op.create_index(
            f"ix_admin_profile_provenance_{column}", "admin_profile_provenance", [column]
        )

    op.create_table(
        "court_record_checks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("searched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("jurisdiction", sa.String(length=255), nullable=False),
        sa.Column("coverage", sa.String(length=1000), nullable=False),
        sa.Column("search_period", sa.String(length=255), nullable=True),
        sa.Column("source", sa.String(length=512), nullable=False),
        sa.Column("finding", sa.String(length=1000), nullable=True),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("limitations", sa.String(length=2000), nullable=False),
        sa.Column("reviewer_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'no_match_found', 'match_found', "
            "'review_required', 'unable_to_complete')",
            name="ck_court_record_checks_status",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_person_id"], ["organization_people.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["reviewer_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["subject_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_court_record_checks_organization_id_idempotency_key",
        ),
    )
    for column in ("organization_id", "organization_person_id", "subject_user_id", "status"):
        op.create_index(f"ix_court_record_checks_{column}", "court_record_checks", [column])

    op.create_table(
        "court_record_check_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("court_record_check_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attached_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["attached_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["court_record_check_id"], ["court_record_checks.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["document_id"], ["user_documents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "court_record_check_id",
            "document_id",
            name="uq_court_record_check_evidence_check_document",
        ),
    )
    op.create_index(
        "ix_court_record_check_evidence_court_record_check_id",
        "court_record_check_evidence",
        ["court_record_check_id"],
    )
    op.create_index(
        "ix_court_record_check_evidence_document_id",
        "court_record_check_evidence",
        ["document_id"],
    )

    op.create_table(
        "in_person_verification_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("verification_type", sa.String(length=64), nullable=False),
        sa.Column("method", sa.String(length=32), server_default="in_person", nullable=False),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("performed_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("person_met", sa.String(length=255), nullable=True),
        sa.Column("relationship", sa.String(length=255), nullable=True),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "evidence_document_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            server_default=sa.text("'{}'::uuid[]"),
            nullable=False,
        ),
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "verification_type IN ('identity_observation', 'document_observation')",
            name="ck_in_person_verification_records_type",
        ),
        sa.CheckConstraint("method = 'in_person'", name="ck_in_person_verification_records_method"),
        sa.CheckConstraint(
            "result IN ('observed_consistent', 'discrepancy', 'unable_to_complete')",
            name="ck_in_person_verification_records_result",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_person_id"], ["organization_people.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["performed_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["subject_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_in_person_verification_records_org_idempotency_key",
        ),
    )
    for column in (
        "organization_id",
        "organization_person_id",
        "subject_user_id",
        "verification_type",
    ):
        op.create_index(
            f"ix_in_person_verification_records_{column}",
            "in_person_verification_records",
            [column],
        )


def downgrade():
    op.drop_table("in_person_verification_records")
    op.drop_table("court_record_check_evidence")
    op.drop_table("court_record_checks")
    op.drop_table("admin_profile_provenance")
    op.drop_table("candidate_activation_tokens")

    op.drop_constraint(
        "fk_resume_record_provenance_confirmed_by_user_id_users",
        "resume_record_provenance",
        type_="foreignkey",
    )
    op.drop_column("resume_record_provenance", "confirmed_by_user_id")
    op.drop_column("resume_record_provenance", "confirmation_source")

    op.drop_column("organization_invitations", "invitee_name")

    op.drop_constraint(
        "uq_organizations_admin_provisioning_idempotency_key",
        "organizations",
        type_="unique",
    )
    op.drop_index(
        "ix_organizations_provisioned_by_admin_user_id", table_name="organizations"
    )
    op.drop_constraint(
        "fk_organizations_provisioned_by_admin_user_id_users",
        "organizations",
        type_="foreignkey",
    )
    op.drop_column("organizations", "admin_provisioning_idempotency_key")
    op.drop_column("organizations", "provisioned_at")
    op.drop_column("organizations", "provisioned_by_admin_user_id")

    op.drop_constraint("ck_users_claim_status", "users", type_="check")
    op.drop_constraint(
        "uq_users_assisted_creation_idempotency_key", "users", type_="unique"
    )
    op.drop_index("ix_users_admin_created_by_user_id", table_name="users")
    op.drop_index("ix_users_claim_status", table_name="users")
    op.drop_constraint(
        "fk_users_admin_created_by_user_id_users", "users", type_="foreignkey"
    )
    op.drop_column("users", "assisted_creation_idempotency_key")
    op.drop_column("users", "claimed_at")
    op.drop_column("users", "admin_created_at")
    op.drop_column("users", "admin_created_by_user_id")
    op.drop_column("users", "claim_status")
