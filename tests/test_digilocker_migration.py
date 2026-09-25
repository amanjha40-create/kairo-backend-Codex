import ast
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from app.db.session import engine
from app.models import DigiLockerConnection


def test_bounded_migration_and_single_head():
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == ["083"]
    revision = script.get_revision("080")
    assert revision.down_revision == "079"
    tree = ast.parse(Path(revision.path).read_text())
    operations = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "op"
    ]
    assert [(node.func.attr, ast.literal_eval(node.args[0])) for node in operations] == [
        ("create_table", "digilocker_connections"),
        ("drop_table", "digilocker_connections"),
    ]


async def test_database_matches_connection_metadata():
    def check(connection):
        inspector = inspect(connection)
        model = DigiLockerConnection.__table__
        actual = inspector.get_columns(model.name)
        assert {c["name"]: c["nullable"] for c in actual} == {
            c.name: c.nullable for c in model.columns
        }
        fk = inspector.get_foreign_keys(model.name)
        assert len(fk) == 1 and fk[0]["referred_table"] == "users"
        assert fk[0]["options"]["ondelete"] == "CASCADE"
        unique = inspector.get_unique_constraints(model.name)
        assert [constraint["column_names"] for constraint in unique] == [["user_id"]]
        checks = inspector.get_check_constraints(model.name)
        assert len(checks) == 5

    async with engine.connect() as connection:
        await connection.run_sync(check)


def test_083_only_widens_match_reason_constraint(monkeypatch):
    from unittest.mock import Mock

    revision = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("083")
    assert revision.down_revision == "082"
    migration = revision.module
    operations = Mock()
    operations.f.side_effect = lambda name: name
    monkeypatch.setattr(migration, "op", operations)
    migration.upgrade()
    operations.drop_constraint.assert_called_once_with(
        "ck_digilocker_identity_verifications_match_reason",
        "digilocker_identity_verifications",
        type_="check",
    )
    name, table, expression = operations.create_check_constraint.call_args.args
    assert name == "match_reason" and table == "digilocker_identity_verifications"
    assert "NAME_EXACT_MATCH" in expression and "FIRST_LAST_MATCH_MIDDLE_IGNORED" in expression
    assert {call[0] for call in operations.mock_calls} == {
        "f",
        "drop_constraint",
        "create_check_constraint",
    }
    operations.reset_mock()
    migration.downgrade()
    assert (
        "FIRST_LAST_MATCH_MIDDLE_IGNORED"
        not in operations.create_check_constraint.call_args.args[2]
    )
    assert {call[0] for call in operations.mock_calls} == {
        "f",
        "drop_constraint",
        "create_check_constraint",
    }
