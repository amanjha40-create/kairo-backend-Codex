"""Allowlisted Places telemetry; never inherit request/user context or exception text."""

import json
import logging
import sys
from contextlib import contextmanager

LOGGER_NAME = "kairo.safe_places"
EVENT = "permanent_address.places_call"
OPERATIONS = frozenset({"geocode", "reverse_geocode"})
OUTCOMES = frozenset({"started", "succeeded", "failed"})
ENVIRONMENTS = frozenset({"production", "staging", "development", "test"})

logger = logging.getLogger(LOGGER_NAME)
logger.propagate = False
logger.addHandler(logging.NullHandler())


class PlacesFormatter(logging.Formatter):
    def __init__(self, environment):
        super().__init__()
        self.environment = (
            environment if type(environment) is str and environment in ENVIRONMENTS else "unknown"
        )

    def format(self, record):
        operation = getattr(record, "operation", None)
        outcome = getattr(record, "outcome", None)
        # Construct a new object, not a redacted copy of an enriched LogRecord.
        return json.dumps({
            "event": EVENT,
            "environment": self.environment,
            "operation": (
                operation if type(operation) is str and operation in OPERATIONS else "unknown"
            ),
            "outcome": outcome if type(outcome) is str and outcome in OUTCOMES else "unknown",
        }, separators=(",", ":"))


def configure_places_logging(environment):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(PlacesFormatter(environment))
    logger.handlers[:] = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False


@contextmanager
def places_call(operation):
    if operation not in OPERATIONS:
        raise ValueError("Unsupported Places operation")
    logger.info(EVENT, extra={"operation": operation, "outcome": "started"})
    try:
        yield
    except Exception:
        logger.info(EVENT, extra={"operation": operation, "outcome": "failed"})
        raise
    else:
        logger.info(EVENT, extra={"operation": operation, "outcome": "succeeded"})
