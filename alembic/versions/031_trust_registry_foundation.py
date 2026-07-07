"""Add Trust Registry foundation tables and additive resolution links.

Revision ID: 031
Revises: 030
Create Date: 2026-07-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trust_registry_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("registry_code", sa.String(length=32), nullable=False),
        sa.Column("legal_name", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("organization_type", sa.String(length=64), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("state_province", sa.String(length=128), nullable=True),
        sa.Column("website", sa.String(length=2048), nullable=True),
        sa.Column("lifecycle_status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("trust_status", sa.String(length=32), nullable=False, server_default="unreviewed"),
        sa.Column(
            "registry_confidence_score",
            sa.Numeric(5, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column("trust_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "registry_confidence_score >= 0 AND registry_confidence_score <= 100",
            name="ck_trust_registry_records_confidence_range",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_trust_registry_records_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name=op.f("fk_trust_registry_records_updated_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["deleted_by_user_id"],
            ["users.id"],
            name=op.f("fk_trust_registry_records_deleted_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trust_registry_records")),
        sa.UniqueConstraint("public_id", name=op.f("uq_trust_registry_records_public_id")),
        sa.UniqueConstraint("registry_code", name=op.f("uq_trust_registry_records_registry_code")),
    )
    op.create_index(op.f("ix_trust_registry_records_legal_name"), "trust_registry_records", ["legal_name"], unique=False)
    op.create_index(op.f("ix_trust_registry_records_display_name"), "trust_registry_records", ["display_name"], unique=False)
    op.create_index(op.f("ix_trust_registry_records_organization_type"), "trust_registry_records", ["organization_type"], unique=False)
    op.create_index(op.f("ix_trust_registry_records_country"), "trust_registry_records", ["country"], unique=False)
    op.create_index(op.f("ix_trust_registry_records_lifecycle_status"), "trust_registry_records", ["lifecycle_status"], unique=False)
    op.create_index(op.f("ix_trust_registry_records_trust_status"), "trust_registry_records", ["trust_status"], unique=False)
    op.create_index(
        "ix_trust_registry_records_active_lookup",
        "trust_registry_records",
        ["country", "organization_type", "lifecycle_status", "trust_status"],
        unique=False,
    )

    op.create_table(
        "trust_registry_capabilities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capability_key", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trust_registry_capabilities")),
        sa.UniqueConstraint("public_id", name=op.f("uq_trust_registry_capabilities_public_id")),
        sa.UniqueConstraint("capability_key", name=op.f("uq_trust_registry_capabilities_capability_key")),
    )

    op.create_table(
        "trust_registry_record_capabilities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("registry_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capability_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["registry_record_id"],
            ["trust_registry_records.id"],
            name=op.f("fk_trust_registry_record_capabilities_registry_record_id_trust_registry_records"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["capability_id"],
            ["trust_registry_capabilities.id"],
            name=op.f("fk_trust_registry_record_capabilities_capability_id_trust_registry_capabilities"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trust_registry_record_capabilities")),
        sa.UniqueConstraint("public_id", name=op.f("uq_trust_registry_record_capabilities_public_id")),
        sa.UniqueConstraint(
            "registry_record_id",
            "capability_id",
            name="uq_trust_registry_record_capabilities_registry_record_id_capability_id",
        ),
    )
    op.create_index(
        op.f("ix_trust_registry_record_capabilities_registry_record_id"),
        "trust_registry_record_capabilities",
        ["registry_record_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_trust_registry_record_capabilities_capability_id"),
        "trust_registry_record_capabilities",
        ["capability_id"],
        unique=False,
    )

    op.create_table(
        "trust_registry_identifiers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("registry_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("identifier_type", sa.String(length=64), nullable=False),
        sa.Column("identifier_value", sa.String(length=255), nullable=False),
        sa.Column("issuing_country", sa.String(length=2), nullable=True),
        sa.Column("issuing_authority", sa.String(length=255), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["registry_record_id"],
            ["trust_registry_records.id"],
            name=op.f("fk_trust_registry_identifiers_registry_record_id_trust_registry_records"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["deleted_by_user_id"],
            ["users.id"],
            name=op.f("fk_trust_registry_identifiers_deleted_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trust_registry_identifiers")),
        sa.UniqueConstraint("public_id", name=op.f("uq_trust_registry_identifiers_public_id")),
        sa.UniqueConstraint(
            "identifier_type",
            "identifier_value",
            "issuing_country",
            name="uq_trust_registry_identifiers_type_value_country",
        ),
    )
    op.create_index(op.f("ix_trust_registry_identifiers_registry_record_id"), "trust_registry_identifiers", ["registry_record_id"], unique=False)
    op.create_index(op.f("ix_trust_registry_identifiers_identifier_type"), "trust_registry_identifiers", ["identifier_type"], unique=False)
    op.create_index(
        "ix_trust_registry_identifiers_identifier_lookup",
        "trust_registry_identifiers",
        ["identifier_type", "identifier_value"],
        unique=False,
    )

    op.create_table(
        "trust_registry_domains",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("registry_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["registry_record_id"],
            ["trust_registry_records.id"],
            name=op.f("fk_trust_registry_domains_registry_record_id_trust_registry_records"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["deleted_by_user_id"],
            ["users.id"],
            name=op.f("fk_trust_registry_domains_deleted_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trust_registry_domains")),
        sa.UniqueConstraint("public_id", name=op.f("uq_trust_registry_domains_public_id")),
        sa.UniqueConstraint("registry_record_id", "domain", name="uq_trust_registry_domains_registry_record_id_domain"),
    )
    op.create_index(op.f("ix_trust_registry_domains_registry_record_id"), "trust_registry_domains", ["registry_record_id"], unique=False)
    op.create_index(op.f("ix_trust_registry_domains_domain"), "trust_registry_domains", ["domain"], unique=False)

    op.create_table(
        "trust_registry_aliases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("registry_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alias_name", sa.String(length=255), nullable=False),
        sa.Column("alias_type", sa.String(length=32), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["registry_record_id"],
            ["trust_registry_records.id"],
            name=op.f("fk_trust_registry_aliases_registry_record_id_trust_registry_records"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["deleted_by_user_id"],
            ["users.id"],
            name=op.f("fk_trust_registry_aliases_deleted_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trust_registry_aliases")),
        sa.UniqueConstraint("public_id", name=op.f("uq_trust_registry_aliases_public_id")),
        sa.UniqueConstraint("registry_record_id", "alias_name", name="uq_trust_registry_aliases_registry_record_id_alias_name"),
    )
    op.create_index(op.f("ix_trust_registry_aliases_registry_record_id"), "trust_registry_aliases", ["registry_record_id"], unique=False)
    op.create_index(op.f("ix_trust_registry_aliases_alias_name"), "trust_registry_aliases", ["alias_name"], unique=False)

    op.create_table(
        "trust_registry_relationships",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_registry_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("child_registry_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relationship_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "parent_registry_record_id <> child_registry_record_id",
            name="ck_trust_registry_relationships_distinct_parent_child",
        ),
        sa.ForeignKeyConstraint(
            ["parent_registry_record_id"],
            ["trust_registry_records.id"],
            name=op.f("fk_trust_registry_relationships_parent_registry_record_id_trust_registry_records"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["child_registry_record_id"],
            ["trust_registry_records.id"],
            name=op.f("fk_trust_registry_relationships_child_registry_record_id_trust_registry_records"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["deleted_by_user_id"],
            ["users.id"],
            name=op.f("fk_trust_registry_relationships_deleted_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trust_registry_relationships")),
        sa.UniqueConstraint("public_id", name=op.f("uq_trust_registry_relationships_public_id")),
        sa.UniqueConstraint(
            "parent_registry_record_id",
            "child_registry_record_id",
            "relationship_type",
            name="uq_trust_registry_relationships_parent_child_type",
        ),
    )
    op.create_index(
        op.f("ix_trust_registry_relationships_parent_registry_record_id"),
        "trust_registry_relationships",
        ["parent_registry_record_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_trust_registry_relationships_child_registry_record_id"),
        "trust_registry_relationships",
        ["child_registry_record_id"],
        unique=False,
    )

    op.create_table(
        "trust_registry_merge_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_registry_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_registry_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merged_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("merge_reason", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "source_registry_record_id <> target_registry_record_id",
            name="ck_trust_registry_merge_history_distinct_source_target",
        ),
        sa.ForeignKeyConstraint(
            ["source_registry_record_id"],
            ["trust_registry_records.id"],
            name=op.f("fk_trust_registry_merge_history_source_registry_record_id_trust_registry_records"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_registry_record_id"],
            ["trust_registry_records.id"],
            name=op.f("fk_trust_registry_merge_history_target_registry_record_id_trust_registry_records"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["merged_by_user_id"],
            ["users.id"],
            name=op.f("fk_trust_registry_merge_history_merged_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trust_registry_merge_history")),
        sa.UniqueConstraint("public_id", name=op.f("uq_trust_registry_merge_history_public_id")),
    )
    op.create_index(
        op.f("ix_trust_registry_merge_history_source_registry_record_id"),
        "trust_registry_merge_history",
        ["source_registry_record_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_trust_registry_merge_history_target_registry_record_id"),
        "trust_registry_merge_history",
        ["target_registry_record_id"],
        unique=False,
    )

    op.add_column("organizations", sa.Column("registry_record_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("organizations", sa.Column("registry_resolution_method", sa.String(length=32), nullable=True))
    op.add_column("organizations", sa.Column("registry_resolution_confidence", sa.Numeric(5, 2), nullable=True))
    op.add_column(
        "organizations",
        sa.Column(
            "registry_resolution_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column("organizations", sa.Column("registry_resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("organizations", sa.Column("registry_resolved_by_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index(op.f("ix_organizations_registry_record_id"), "organizations", ["registry_record_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_organizations_registry_record_id_trust_registry_records"),
        "organizations",
        "trust_registry_records",
        ["registry_record_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_organizations_registry_resolved_by_user_id_users"),
        "organizations",
        "users",
        ["registry_resolved_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("verification_requests", sa.Column("registry_record_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(
        "verification_requests",
        sa.Column("registry_resolution_state", sa.String(length=32), nullable=False, server_default="unresolved"),
    )
    op.add_column("verification_requests", sa.Column("registry_resolution_method", sa.String(length=32), nullable=True))
    op.add_column("verification_requests", sa.Column("registry_resolution_confidence", sa.Numeric(5, 2), nullable=True))
    op.add_column(
        "verification_requests",
        sa.Column(
            "registry_resolution_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column("verification_requests", sa.Column("registry_resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("verification_requests", sa.Column("registry_resolved_by_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index(
        op.f("ix_verification_requests_registry_record_id"),
        "verification_requests",
        ["registry_record_id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk_verification_requests_registry_record_id_trust_registry_records"),
        "verification_requests",
        "trust_registry_records",
        ["registry_record_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_verification_requests_registry_resolved_by_user_id_users"),
        "verification_requests",
        "users",
        ["registry_resolved_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_verification_requests_registry_resolved_by_user_id_users"), "verification_requests", type_="foreignkey")
    op.drop_constraint(op.f("fk_verification_requests_registry_record_id_trust_registry_records"), "verification_requests", type_="foreignkey")
    op.drop_index(op.f("ix_verification_requests_registry_record_id"), table_name="verification_requests")
    op.drop_column("verification_requests", "registry_resolved_by_user_id")
    op.drop_column("verification_requests", "registry_resolved_at")
    op.drop_column("verification_requests", "registry_resolution_metadata")
    op.drop_column("verification_requests", "registry_resolution_confidence")
    op.drop_column("verification_requests", "registry_resolution_method")
    op.drop_column("verification_requests", "registry_resolution_state")
    op.drop_column("verification_requests", "registry_record_id")

    op.drop_constraint(op.f("fk_organizations_registry_resolved_by_user_id_users"), "organizations", type_="foreignkey")
    op.drop_constraint(op.f("fk_organizations_registry_record_id_trust_registry_records"), "organizations", type_="foreignkey")
    op.drop_index(op.f("ix_organizations_registry_record_id"), table_name="organizations")
    op.drop_column("organizations", "registry_resolved_by_user_id")
    op.drop_column("organizations", "registry_resolved_at")
    op.drop_column("organizations", "registry_resolution_metadata")
    op.drop_column("organizations", "registry_resolution_confidence")
    op.drop_column("organizations", "registry_resolution_method")
    op.drop_column("organizations", "registry_record_id")

    op.drop_index(op.f("ix_trust_registry_merge_history_target_registry_record_id"), table_name="trust_registry_merge_history")
    op.drop_index(op.f("ix_trust_registry_merge_history_source_registry_record_id"), table_name="trust_registry_merge_history")
    op.drop_table("trust_registry_merge_history")

    op.drop_index(op.f("ix_trust_registry_relationships_child_registry_record_id"), table_name="trust_registry_relationships")
    op.drop_index(op.f("ix_trust_registry_relationships_parent_registry_record_id"), table_name="trust_registry_relationships")
    op.drop_table("trust_registry_relationships")

    op.drop_index(op.f("ix_trust_registry_aliases_alias_name"), table_name="trust_registry_aliases")
    op.drop_index(op.f("ix_trust_registry_aliases_registry_record_id"), table_name="trust_registry_aliases")
    op.drop_table("trust_registry_aliases")

    op.drop_index(op.f("ix_trust_registry_domains_domain"), table_name="trust_registry_domains")
    op.drop_index(op.f("ix_trust_registry_domains_registry_record_id"), table_name="trust_registry_domains")
    op.drop_table("trust_registry_domains")

    op.drop_index("ix_trust_registry_identifiers_identifier_lookup", table_name="trust_registry_identifiers")
    op.drop_index(op.f("ix_trust_registry_identifiers_identifier_type"), table_name="trust_registry_identifiers")
    op.drop_index(op.f("ix_trust_registry_identifiers_registry_record_id"), table_name="trust_registry_identifiers")
    op.drop_table("trust_registry_identifiers")

    op.drop_index(op.f("ix_trust_registry_record_capabilities_capability_id"), table_name="trust_registry_record_capabilities")
    op.drop_index(op.f("ix_trust_registry_record_capabilities_registry_record_id"), table_name="trust_registry_record_capabilities")
    op.drop_table("trust_registry_record_capabilities")

    op.drop_table("trust_registry_capabilities")

    op.drop_index("ix_trust_registry_records_active_lookup", table_name="trust_registry_records")
    op.drop_index(op.f("ix_trust_registry_records_trust_status"), table_name="trust_registry_records")
    op.drop_index(op.f("ix_trust_registry_records_lifecycle_status"), table_name="trust_registry_records")
    op.drop_index(op.f("ix_trust_registry_records_country"), table_name="trust_registry_records")
    op.drop_index(op.f("ix_trust_registry_records_organization_type"), table_name="trust_registry_records")
    op.drop_index(op.f("ix_trust_registry_records_display_name"), table_name="trust_registry_records")
    op.drop_index(op.f("ix_trust_registry_records_legal_name"), table_name="trust_registry_records")
    op.drop_table("trust_registry_records")
