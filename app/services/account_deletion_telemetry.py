"""Invocation-local, identifier-free sweeper telemetry; no persistence or IO policy."""

import json
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from functools import wraps
from time import monotonic_ns


@dataclass
class SweepMetrics:
    rows_scanned: int = 0
    rows_claimed: int = 0
    requests_claimed: int = 0
    objects_attempted: int = 0
    objects_succeeded: int = 0
    objects_missing: int = 0
    objects_already_absent: int = 0
    retryable_failures: int = 0
    permanent_failures: int = 0
    invocation_failures: int = 0
    invocation_result: str = "no_work"
    failure_category: str = "none"


_current: ContextVar[SweepMetrics | None] = ContextVar("deletion_sweep_metrics", default=None)


def current_metrics():
    return _current.get()


@contextmanager
def sweep_invocation():
    """CLI and service share one summary, without ambient user logging context."""
    existing = current_metrics()
    if existing is not None:
        yield existing
        return
    metrics = SweepMetrics()
    token = _current.set(metrics)
    started = monotonic_ns()
    try:
        yield metrics
    except BaseException:
        metrics.invocation_failures += 1
        metrics.invocation_result = "failed"
        metrics.failure_category = "invocation_failed"
        raise
    finally:
        _current.reset(token)
        # An explicit fixed-field JSON record avoids exception text, SDK parameters
        # and ambient request/user fields. Stdout is the one-shot task's log sink.
        print(
            json.dumps(
                {
                    "event": "account_deletion_sweep_completed",
                    **asdict(metrics),
                    "duration_ms": (monotonic_ns() - started) // 1_000_000,
                }
            ),
            flush=True,
        )


def observe_sweep(function):
    @wraps(function)
    async def observed(*args, **kwargs):
        with sweep_invocation() as metrics:
            result = await function(*args, **kwargs)
            if result is not None:
                metrics.invocation_result = (
                    "review" if result["review"] else "partial" if result["pending"] else "success"
                )
            return result

    return observed
