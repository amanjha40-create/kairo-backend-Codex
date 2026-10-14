"""Rehearse 074 -> 090 only on an explicitly named disposable localhost DB."""

import json
import os
import time
from datetime import UTC, datetime
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import MetaData, create_engine, inspect, select, text
from sqlalchemy.engine import make_url


def main():
    url = make_url(os.environ["MIGRATION_DATABASE_URL"])
    if url.host not in {"localhost", "127.0.0.1"} or url.database != "kairo_migration":
        raise RuntimeError("disposable_local_migration_database_required")
    engine = create_engine(url)
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["090"]
    metadata = MetaData()
    metadata.reflect(engine)
    tables = metadata.tables
    ids = {}
    before = {}

    def insert(conn, table_name, **values):
        table = tables[table_name]
        values.setdefault("id", uuid4())
        if "public_id" in table.c:
            values.setdefault("public_id", uuid4())
        conn.execute(table.insert().values(**values))
        ids[table_name] = values["id"]

    with engine.begin() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all() == [
            "074"
        ]
        assert conn.execute(select(tables["users"].c.id)).first() is None
        insert(conn, "users", email="rc-candidate@example.invalid", role="user")
        user = ids["users"]
        insert(
            conn,
            "organizations",
            created_by_user_id=user,
            name="Synthetic RC Employer",
            organization_type="employer",
        )
        org = ids["organizations"]
        insert(conn, "organization_members", organization_id=org, user_id=user, role="owner")
        insert(
            conn,
            "employments",
            created_by_user_id=user,
            subject_full_name="Synthetic RC Candidate",
            employer_legal_name="Synthetic RC Employer",
            job_title="Synthetic QA",
            verification_status="verified",
        )
        employment = ids["employments"]
        insert(
            conn,
            "verification_requests",
            subject_user_id=user,
            requested_by_user_id=user,
            subject_name="Synthetic RC Candidate",
            subject_email="rc-candidate@example.invalid",
            request_type="employment",
            status="verified",
            employment_id=employment,
            organization_id=org,
        )
        request = ids["verification_requests"]
        insert(
            conn,
            "employment_documents",
            employment_id=employment,
            uploaded_by_user_id=user,
            document_type="payslip",
            object_key="synthetic/rc/evidence.pdf",
            original_filename="synthetic.pdf",
            content_type="application/pdf",
            byte_size=100,
            checksum_sha256="a" * 64,
            verification_status="uploaded",
        )
        insert(
            conn,
            "verification_request_evidence",
            verification_request_id=request,
            submitted_by_user_id=user,
            evidence_type="document",
            field_key="employment",
            employment_document_id=ids["employment_documents"],
            status="accepted",
        )
        insert(
            conn,
            "verification_request_reviews",
            verification_request_id=request,
            review_round=1,
            review_status="approved",
        )
        insert(
            conn,
            "trust_score_snapshots",
            user_id=user,
            score_version="v1",
            status="calculated",
            overall_score=71,
            verification_completeness_percentage=50,
            domain_scores={},
            positive_contributors=[],
            negative_contributors=[],
            critical_overrides=[],
            calculated_at=datetime.now(UTC),
        )
        insert(
            conn,
            "passport_share_links",
            owner_user_id=user,
            token_hash="b" * 64,
            permissions={"employment": True},
        )
        insert(
            conn,
            "notifications",
            recipient_user_id=user,
            notification_type="synthetic",
            event_type="synthetic",
            channel="in_app",
            template_key="synthetic",
            status="sent",
        )
        for name in ids:
            before[name] = dict(conn.execute(select(tables[name])).mappings().one())

    timings = {}
    for revision in reversed(list(script.iterate_revisions("090", "074"))):
        started = time.monotonic()
        command.upgrade(config, revision.revision)
        timings[revision.revision] = round(time.monotonic() - started, 3)
        with engine.connect() as conn:
            assert conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalars().all() == [revision.revision]
            for name, original in before.items():
                assert dict(conn.execute(select(tables[name])).mappings().one()) == original, name

    with engine.connect() as conn:
        assert (
            conn.execute(text("SELECT evidence_role FROM employment_documents")).scalar_one()
            is None
        )
        assert (
            conn.execute(text("SELECT reviewed_at FROM verification_request_evidence")).scalar_one()
            is None
        )
        assert conn.execute(text("SELECT count(*) FROM digilocker_connections")).scalar_one() == 0
    expected_tables = {
        "digilocker_connections",
        "digilocker_identity_verifications",
        "employment_references",
        "permanent_address_documents",
        "account_deletions",
    }
    assert expected_tables <= set(inspect(engine).get_table_names())

    # No new-feature rows exist, so guarded downgrades are safe on this fixture DB.
    command.downgrade(config, "074")
    with engine.connect() as conn:
        for name, original in before.items():
            assert dict(conn.execute(select(tables[name])).mappings().one()) == original, name
    command.upgrade(config, "090")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all() == [
            "090"
        ]
        for name, original in before.items():
            assert dict(conn.execute(select(tables[name])).mappings().one()) == original, name
    print(
        json.dumps(
            {
                "upgrade": "PASS",
                "downgrade_empty_new_features": "PASS",
                "reupgrade": "PASS",
                "fixture_tables_preserved": sorted(before),
                "legacy_role": None,
                "source_heads": script.get_heads(),
                "migration_seconds_local_only": timings,
            }
        )
    )
    engine.dispose()


if __name__ == "__main__":
    main()
