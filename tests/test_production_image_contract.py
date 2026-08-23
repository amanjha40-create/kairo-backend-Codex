"""The default backend image must contain runtime code only."""

from pathlib import Path


def test_default_docker_stage_excludes_tests_and_qa_scripts() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    runtime_stage = dockerfile.rsplit("FROM base AS runtime", maxsplit=1)[1]

    assert "COPY tests" not in runtime_stage
    assert "COPY scripts" not in runtime_stage
    assert "requirements-dev.txt" not in runtime_stage
    assert "FROM base AS runtime" in dockerfile
    assert 'CMD ["gunicorn"' in runtime_stage
