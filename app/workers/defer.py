"""Explicit, bounded SQS deferral requested by a canonical job handler."""

from __future__ import annotations

SQS_MAX_VISIBILITY_TIMEOUT_SECONDS = 43_200


class DeferMessage(Exception):
    """Keep the current SQS message and make it visible again later."""

    def __init__(self, delay_seconds: int) -> None:
        if not 1 <= delay_seconds <= SQS_MAX_VISIBILITY_TIMEOUT_SECONDS:
            raise ValueError("invalid_sqs_deferral")
        self.delay_seconds = delay_seconds
        super().__init__("sqs_message_deferred")
