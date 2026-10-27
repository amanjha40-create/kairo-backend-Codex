"""Allowlisted Places telemetry; never inherit request/user context or exception text."""

import json
import logging
import sys
from contextlib import contextmanager

LOGGER_NAME = "kairo.safe_places"
EVENT = "permanent_address.places_call"
GOOGLE_DIAGNOSTIC_LOGGER_NAME = "kairo.safe_google_geocode"
GOOGLE_DIAGNOSTIC_EVENT = "permanent_address.google_geocode_diagnostic"
OPERATIONS = frozenset({"geocode", "reverse_geocode"})
OUTCOMES = frozenset({"started", "succeeded", "failed"})
PROVIDERS = frozenset({"amazon_location", "google"})
ENVIRONMENTS = frozenset({"production", "staging", "development", "test"})
GOOGLE_STATUSES = frozenset({
    "OK",
    "ZERO_RESULTS",
    "OVER_QUERY_LIMIT",
    "REQUEST_DENIED",
    "INVALID_REQUEST",
    "UNKNOWN_ERROR",
})
GOOGLE_DIAGNOSTIC_REASONS = frozenset({
    "GOOGLE_GEOCODE_SUCCESS",
    "GOOGLE_GEOCODE_ZERO_RESULTS",
    "GOOGLE_GEOCODE_AUTH_FAILURE",
    "GOOGLE_GEOCODE_QUOTA_OR_RATE_LIMIT",
    "GOOGLE_GEOCODE_PROVIDER_4XX",
    "GOOGLE_GEOCODE_PROVIDER_5XX",
    "GOOGLE_GEOCODE_TIMEOUT",
    "GOOGLE_GEOCODE_NETWORK_FAILURE",
    "GOOGLE_GEOCODE_MALFORMED_RESPONSE",
    "GOOGLE_GEOCODE_MISSING_COORDINATES",
    "GOOGLE_GEOCODE_NORMALIZATION_FAILURE",
    "GOOGLE_GEOCODE_POLICY_INELIGIBLE",
    "GOOGLE_GEOCODE_INTERNAL_FAILURE",
})

logger = logging.getLogger(LOGGER_NAME)
logger.propagate = False
logger.addHandler(logging.NullHandler())
google_diagnostic_logger = logging.getLogger(GOOGLE_DIAGNOSTIC_LOGGER_NAME)
google_diagnostic_logger.propagate = False
google_diagnostic_logger.addHandler(logging.NullHandler())


class PlacesFormatter(logging.Formatter):
    def __init__(self, environment):
        super().__init__()
        self.environment = (
            environment if type(environment) is str and environment in ENVIRONMENTS else "unknown"
        )

    def format(self, record):
        operation = getattr(record, "operation", None)
        outcome = getattr(record, "outcome", None)
        provider = getattr(record, "provider", None)
        # Construct a new object, not a redacted copy of an enriched LogRecord.
        return json.dumps({
            "event": EVENT,
            "environment": self.environment,
            "operation": (
                operation if type(operation) is str and operation in OPERATIONS else "unknown"
            ),
            "provider": provider if type(provider) is str and provider in PROVIDERS else "unknown",
            "outcome": outcome if type(outcome) is str and outcome in OUTCOMES else "unknown",
        }, separators=(",", ":"))


class GoogleDiagnosticFormatter(logging.Formatter):
    def __init__(self, environment):
        super().__init__()
        self.environment = (
            environment if type(environment) is str and environment in ENVIRONMENTS else "unknown"
        )

    def format(self, record):
        reason = getattr(record, "reason", None)
        google_status = getattr(record, "google_status", None)
        correlation_id = getattr(record, "correlation_id", None)
        http_status = getattr(record, "http_status", None)
        result_count = getattr(record, "result_count", None)
        return json.dumps({
            "event": GOOGLE_DIAGNOSTIC_EVENT,
            "environment": self.environment,
            "provider": "google",
            "operation": (
                record.operation if getattr(record, "operation", None) in OPERATIONS else "unknown"
            ),
            "reason": (
                reason
                if reason in GOOGLE_DIAGNOSTIC_REASONS
                else "GOOGLE_GEOCODE_INTERNAL_FAILURE"
            ),
            "http_status": (
                http_status if type(http_status) is int and 100 <= http_status <= 599 else None
            ),
            "google_status": google_status if google_status in GOOGLE_STATUSES else None,
            "result_count": (
                result_count if type(result_count) is int and 0 <= result_count <= 100 else None
            ),
            "coordinates_present": getattr(record, "coordinates_present", None) is True,
            "normalized_result_eligible": (
                getattr(record, "normalized_result_eligible", None) is True
            ),
            "correlation_id": (
                correlation_id
                if type(correlation_id) is str
                and len(correlation_id) == 32
                and all(char in "0123456789abcdef" for char in correlation_id)
                else "unknown"
            ),
        }, separators=(",", ":"))


def configure_places_logging(environment):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(PlacesFormatter(environment))
    logger.handlers[:] = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    diagnostic_handler = logging.StreamHandler(sys.stdout)
    diagnostic_handler.setFormatter(GoogleDiagnosticFormatter(environment))
    google_diagnostic_logger.handlers[:] = [diagnostic_handler]
    google_diagnostic_logger.setLevel(logging.INFO)
    google_diagnostic_logger.propagate = False


def log_google_geocode_diagnostic(
    *,
    operation,
    reason,
    correlation_id,
    http_status=None,
    google_status=None,
    result_count=None,
    coordinates_present=False,
    normalized_result_eligible=False,
):
    """Emit only allowlisted provider diagnostics; never accept payload or address data."""
    google_diagnostic_logger.info(
        GOOGLE_DIAGNOSTIC_EVENT,
        extra={
            "operation": operation,
            "reason": reason,
            "correlation_id": correlation_id,
            "http_status": http_status,
            "google_status": google_status,
            "result_count": result_count,
            "coordinates_present": coordinates_present,
            "normalized_result_eligible": normalized_result_eligible,
        },
    )


@contextmanager
def places_call(operation, provider="amazon_location"):
    if operation not in OPERATIONS:
        raise ValueError("Unsupported Places operation")
    if provider not in PROVIDERS:
        raise ValueError("Unsupported Places provider")
    logger.info(
        EVENT,
        extra={"operation": operation, "provider": provider, "outcome": "started"},
    )
    try:
        yield
    except Exception:
        logger.info(
            EVENT,
            extra={"operation": operation, "provider": provider, "outcome": "failed"},
        )
        raise
    else:
        logger.info(
            EVENT,
            extra={"operation": operation, "provider": provider, "outcome": "succeeded"},
        )
