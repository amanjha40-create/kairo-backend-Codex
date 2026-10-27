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
GOOGLE_LOCATION_TYPES = frozenset({
    "ROOFTOP",
    "RANGE_INTERPOLATED",
    "GEOMETRIC_CENTER",
    "APPROXIMATE",
})
GOOGLE_RESULT_TYPE_CLASSES = frozenset({
    "street_address",
    "premise",
    "subpremise",
    "route",
    "postal_code",
    "locality",
    "other",
})
PROVIDER_NEUTRAL_QUALITIES = frozenset({
    "precise_address",
    "approximate_address",
    "precise_address_street_unavailable",
})
ELIGIBILITY_REASONS = frozenset({
    "country_mismatch",
    "state_mismatch",
    "locality_mismatch",
    "pin_mismatch_or_missing",
    "street_missing_or_mismatch",
    "number_warning_requires_complete_structure",
    "country_component_score_invalid",
    "state_component_score_invalid",
    "city_component_score_invalid",
    "pin_component_score_invalid",
    "approximate_requires_complete_structure",
    "broad_or_unsupported_place_type",
    "invalid_position",
    "candidate_list_truncated",
    "foreign_result",
    "competing_candidates",
    "no_eligible_target",
})
REQUIRED_COMPONENTS = (
    "country",
    "state",
    "locality",
    "postal_code",
    "street",
    "address_number",
)
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
        component_presence = getattr(record, "required_component_presence", None)
        component_presence = component_presence if isinstance(component_presence, dict) else {}
        eligibility_reasons = getattr(record, "eligibility_reasons", ())
        eligibility_reasons = eligibility_reasons if isinstance(eligibility_reasons, tuple) else ()
        google_location_type = getattr(record, "google_location_type", None)
        result_type_class = getattr(record, "selected_result_type_class", None)
        provider_neutral_quality = getattr(record, "provider_neutral_quality", None)
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
            "google_location_type": (
                google_location_type
                if google_location_type in GOOGLE_LOCATION_TYPES
                else None
            ),
            "partial_match": getattr(record, "partial_match", None) is True,
            "selected_result_type_class": (
                result_type_class
                if result_type_class in GOOGLE_RESULT_TYPE_CLASSES
                else None
            ),
            "required_component_presence": {
                key: component_presence.get(key) is True for key in REQUIRED_COMPONENTS
            },
            "provider_neutral_quality": (
                provider_neutral_quality
                if provider_neutral_quality in PROVIDER_NEUTRAL_QUALITIES
                else None
            ),
            "eligibility_reasons": [
                reason for reason in eligibility_reasons if reason in ELIGIBILITY_REASONS
            ],
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
    google_location_type=None,
    partial_match=False,
    selected_result_type_class=None,
    required_component_presence=None,
    provider_neutral_quality=None,
    eligibility_reasons=(),
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
            "google_location_type": google_location_type,
            "partial_match": partial_match,
            "selected_result_type_class": selected_result_type_class,
            "required_component_presence": required_component_presence,
            "provider_neutral_quality": provider_neutral_quality,
            "eligibility_reasons": eligibility_reasons,
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
