from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ("app", "alembic", "tests")
EXPECTED_ALEMBIC_HEADS = {"069"}


def test_no_accidental_duplicate_python_filenames() -> None:
    offenders: list[str] = []
    for root in SCAN_ROOTS:
        for path in (REPO_ROOT / root).rglob("*.py"):
            if path.name.endswith(" 2.py"):
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, f"Accidental duplicate Python files found: {offenders}"


def test_alembic_has_single_expected_head() -> None:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    heads = set(script.get_heads())
    assert heads == EXPECTED_ALEMBIC_HEADS, f"Unexpected Alembic heads: {sorted(heads)}"
