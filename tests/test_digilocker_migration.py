import ast
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from app.db.session import engine
from app.models import DigiLockerConnection


def test_bounded_migration_and_single_head():
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == ["080"]
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
