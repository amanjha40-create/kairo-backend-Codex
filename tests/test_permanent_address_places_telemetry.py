"""Exercise final serialized output with synthetic secrets, never a live provider."""

import io
import json
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.logging import places
from app.logging.context import bind_request_context, bind_user_context, reset_request_context
from app.services.permanent_address_geocoder import AmazonAddressGeocoder


@pytest.fixture
def output(monkeypatch):
    stream = io.StringIO()
    before = places.logger.handlers[:], places.logger.level, places.logger.propagate
    monkeypatch.setattr(places, "sys", SimpleNamespace(stdout=stream))
    places.configure_places_logging("production")
    yield stream
    places.logger.handlers[:], level, places.logger.propagate = before
    places.logger.setLevel(level)
    reset_request_context()


@pytest.mark.parametrize("operation", ["geocode", "reverse_geocode"])
@pytest.mark.parametrize("fails", [False, True])
def test_request_boundary_emits_only_allowlist(output, monkeypatch, caplog, operation, fails):
    sentinel = "SYNTHETIC-PRIVATE-DO-NOT-LOG"
    bind_request_context(request_id=sentinel, correlation_id=sentinel)
    bind_user_context(sentinel)
    client = Mock()
    method = getattr(client, operation)
    method.return_value = {"private_response": sentinel}
    if fails:
        method.side_effect = RuntimeError(sentinel)
    factory = Mock(return_value=client)
    monkeypatch.setattr("app.services.permanent_address_geocoder.boto3.client", factory)
    geocoder = AmazonAddressGeocoder()

    def invoke():
        if operation == "geocode":
            return geocoder._request({"Street": sentinel}, sentinel)
        return geocoder._reverse_request((12.34, 56.78))

    with caplog.at_level(logging.INFO):
        if fails:
            with pytest.raises(RuntimeError):
                invoke()
        else:
            assert invoke() == {"private_response": sentinel}
    method.assert_called_once()
    assert factory.call_args.kwargs["config"].retries["total_max_attempts"] == 1
    assert places.logger.propagate is False
    expected = [{
        "event": places.EVENT, "environment": "production",
        "operation": operation, "outcome": outcome,
    } for outcome in ("started", "failed" if fails else "succeeded")]
    assert [json.loads(line) for line in output.getvalue().splitlines()] == expected
    assert sentinel not in output.getvalue()
    assert "12.34" not in output.getvalue() and "56.78" not in output.getvalue()


@pytest.mark.parametrize("environment", ["production", "staging", "test", "development"])
def test_formatter_discards_sensitive_extras_message_and_traceback(environment):
    private = "SYNTHETIC-SENSITIVE"
    record = logging.LogRecord("name", logging.ERROR, private, 1, private, (), None)
    for field in (
        "address", "query", "postal_code", "latitude", "longitude", "provider_request",
        "provider_response", "user_id", "candidate_id", "document_id", "encrypted_target",
        "ciphertext", "key_id", "request_id", "correlation_id", "exc_text", "stack_info",
    ):
        setattr(record, field, private)
    record.operation = "reverse_geocode"
    record.outcome = "failed"
    record.exc_info = (RuntimeError, RuntimeError(private), None)
    result = places.PlacesFormatter(environment).format(record)
    assert json.loads(result) == {
        "event": places.EVENT, "environment": environment,
        "operation": "reverse_geocode", "outcome": "failed",
    }
    assert private not in result


@pytest.mark.parametrize("invalid", ["SYNTHETIC-PRIVATE", None, {"private": "value"}, 12.34])
def test_untrusted_field_values_are_not_serialized(invalid):
    record = logging.makeLogRecord({"operation": invalid, "outcome": invalid})
    assert json.loads(places.PlacesFormatter(invalid).format(record)) == {
        "event": places.EVENT, "environment": "unknown",
        "operation": "unknown", "outcome": "unknown",
    }


def test_configuration_is_singleton_and_context_free(output):
    places.configure_places_logging("production")
    places.configure_places_logging("production")
    assert len(places.logger.handlers) == 1
    assert not places.logger.handlers[0].filters
    assert places.logger.propagate is False
    with places.places_call("geocode"):
        pass
    assert len(output.getvalue().splitlines()) == 2


def test_invalid_operation_does_not_emit(output):
    with pytest.raises(ValueError):
        with places.places_call("private-query"):
            pytest.fail("invalid operation ran")
    assert output.getvalue() == ""


def test_no_root_identity_enrichment(output):
    root_output = io.StringIO()
    root_handler = logging.StreamHandler(root_output)
    root_handler.setFormatter(logging.Formatter("%(message)s %(user_id)s"))
    root = logging.getLogger()
    root.addHandler(root_handler)
    try:
        with places.places_call("geocode"):
            pass
        assert root_output.getvalue() == ""
        assert len(output.getvalue().splitlines()) == 2
    finally:
        root.removeHandler(root_handler)


@pytest.mark.parametrize("json_logs", [False, True])
def test_application_startup_configures_allowlist_even_for_text_logs(
    output, monkeypatch, json_logs,
):
    from app.logging import setup

    root = logging.getLogger()
    before = root.handlers[:], root.level
    monkeypatch.setattr(setup, "get_settings", lambda: SimpleNamespace(
        log_level="INFO", log_json=json_logs, app_name="synthetic",
        app_env=SimpleNamespace(value="production"), log_access_enabled=False,
    ))
    try:
        setup.configure_logging()
        bind_user_context("SYNTHETIC-IDENTITY")
        with places.places_call("reverse_geocode"):
            pass
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        assert len(records) == 2
        assert all(set(row) == {"event", "environment", "operation", "outcome"} for row in records)
        assert all(row["environment"] == "production" for row in records)
    finally:
        root.handlers[:] = before[0]
        root.setLevel(before[1])
