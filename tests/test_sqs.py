"""SQS envelope and worker registry unit tests (no AWS calls)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.sqs.envelope import SqsJobEnvelope
from app.workers.registry import get_handler, register_handler, registered_types


def test_envelope_valid() -> None:
    env = SqsJobEnvelope.model_validate({"type": "noop", "data": {"k": 1}})
    assert env.type == "noop"
    assert env.data["k"] == 1


def test_envelope_rejects_extra_keys() -> None:
    with pytest.raises(ValidationError):
        SqsJobEnvelope.model_validate({"type": "x", "data": {}, "evil": True})


@pytest.mark.asyncio
async def test_register_handler() -> None:
    import uuid

    tid = f"test_register_{uuid.uuid4().hex}"

    @register_handler(tid)
    async def _h(data: dict, session: AsyncSession) -> None:
        _ = (data, session)

    assert get_handler(tid) is _h
    assert tid in registered_types()
