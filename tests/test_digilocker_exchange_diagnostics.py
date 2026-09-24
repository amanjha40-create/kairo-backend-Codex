import json
import logging
import socket
import ssl
from datetime import UTC, datetime

import httpx
import pytest
from digilocker_helpers import settings
from pydantic import SecretStr

from app.integrations.digilocker.provider import DigiLockerProvider, ProviderError
from app.logging.setup import KairoJsonFormatter

LOGGER = "app.integrations.digilocker.diagnostics"
PRIVATE = ["synthetic-client-secret", "PRIVATE-CODE", "PRIVATE-VERIFIER",
           "PRIVATE-ACCESS", "PRIVATE-REFRESH", "PRIVATE-STATE", "PRIVATE-ID-TOKEN"]


def grant():
    return {"access_token": PRIVATE[3], "refresh_token": PRIVATE[4], "token_type": "Bearer",
            "expires_in": 3600, "id_token": PRIVATE[6], "state": PRIVATE[5]}


async def invoke(caplog, handler, *, success=False):
    caplog.set_level(logging.INFO, logger=LOGGER)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = DigiLockerProvider(settings(), client=client)
        if success:
            result = await provider.exchange_authorization_code(
                SecretStr(PRIVATE[1]), SecretStr(PRIVATE[2]), now=datetime.now(UTC))
            assert result.access_token.get_secret_value() == PRIVATE[3]
        else:
            with pytest.raises(ProviderError):
                await provider.exchange_authorization_code(
                    SecretStr(PRIVATE[1]), SecretStr(PRIVATE[2]), now=datetime.now(UTC))
    records = [r for r in caplog.records if r.name == LOGGER]
    formatter = KairoJsonFormatter()
    formatted = [json.loads(formatter.format(r)) for r in records]
    raw = repr([r.__dict__ for r in records]) + json.dumps(formatted)
    for private in PRIVATE + ["synthetic-client", "PRIVATE-HEADER", "PRIVATE-DESCRIPTION"]:
        assert private not in raw
    assert all(r.exc_info is None and r.stack_info is None for r in records)
    assert formatted[0]["message"] == "digilocker_token_exchange_started"
    assert formatted[0]["client_auth_method"] == "http_basic"
    assert all(formatted[0][k] for k in (
        "code_present", "code_verifier_present", "redirect_uri_present"))
    assert formatted[0]["timeout_seconds"] == {
        "total": 15, "connect": 3, "pool": 3, "read": 10, "write": 10}
    return formatted


@pytest.mark.parametrize("status,error", [(400, "invalid_grant"), (401, "invalid_client"),
                                         (500, "server_error"), (302, "invalid_request")])
async def test_http_rejection_metadata(caplog, status, error):
    records = await invoke(caplog, lambda r: httpx.Response(status, json={
        "error": error, "error_description": "PRIVATE-DESCRIPTION " + " ".join(PRIVATE),
        **grant(),
    }))
    response = records[-1]
    assert response["http_status"] == status
    assert response["provider_oauth_error"] == error
    assert response["failure_category"] == "PROVIDER_HTTP_REJECTION"
    assert response["response_parse_category"] == "json"
    assert response["elapsed_ms"] >= 0


@pytest.mark.parametrize("error", [PRIVATE[1], {"nested": PRIVATE[3]}, [PRIVATE[5]], 123])
async def test_untrusted_error_and_headers_not_logged(caplog, error):
    records = await invoke(caplog, lambda r: httpx.Response(400, json={"error": error},
        headers={"content-type": "PRIVATE-HEADER", "x-error": PRIVATE[0]}))
    assert records[-1]["provider_oauth_error"] == "other_redacted"
    assert records[-1]["content_type"] == "other"


@pytest.mark.parametrize("exception,cause,category,failure", [
    (httpx.ConnectTimeout, None, "CONNECT_TIMEOUT", "TIMEOUT"),
    (httpx.ReadTimeout, None, "READ_TIMEOUT", "TIMEOUT"),
    (httpx.WriteTimeout, None, "OTHER", "TIMEOUT"),
    (TimeoutError, None, "OTHER", "TIMEOUT"),
    (httpx.ConnectError, ssl.SSLCertVerificationError, "TLS", "TLS_ERROR"),
    (httpx.ConnectError, socket.gaierror, "DNS", "TRANSPORT_ERROR"),
    (httpx.ConnectError, None, "CONNECTION", "TRANSPORT_ERROR"),
    (httpx.RemoteProtocolError, None, "OTHER", "TRANSPORT_ERROR"),
])
async def test_transport_classification_without_exception_strings(
    caplog, exception, cause, category, failure
):
    def handler(request):
        exc = exception(" ".join(PRIVATE))
        if cause:
            raise exc from cause(" ".join(PRIVATE))
        raise exc
    records = await invoke(caplog, handler)
    assert len(records) == 2
    assert records[-1]["message"] == "digilocker_token_exchange_transport_error"
    assert records[-1]["exception_class"] == exception.__name__
    assert records[-1]["category"] == category
    assert records[-1]["failure_category"] == failure
    assert records[-1]["response_received"] is False


@pytest.mark.parametrize("payload,category", [
    ({"token_type": "Bearer", "expires_in": 1}, "missing_access_token"),
    (grant() | {"expires_in": "3600"}, "malformed_expiry"),
    (grant() | {"token_type": "PRIVATE-HEADER"}, "malformed_token_type"),
    (grant() | {"scope": {}}, "schema_validation_failure"),
    (grant() | {"access_token": ""}, "schema_validation_failure"),
    ([], "schema_validation_failure"),
])
async def test_token_schema_diagnostics(caplog, payload, category):
    records = await invoke(caplog, lambda r: httpx.Response(200, json=payload))
    assert records[-1]["failure_category"] == "TOKEN_SCHEMA_ERROR"
    assert records[-1]["response_parse_category"] == category


@pytest.mark.parametrize("oversize", [False, True])
async def test_invalid_json_and_size_bound(caplog, oversize):
    records = await invoke(caplog, lambda r: httpx.Response(200,
        content=b"x" * 65537 if oversize else " ".join(PRIVATE).encode(),
        headers={"content-type": "text/html; private=" + PRIVATE[3]}))
    assert records[-1]["failure_category"] == "RESPONSE_PARSE_ERROR"
    assert records[-1]["response_parse_category"] == (
        "response_too_large" if oversize else "invalid_json")
    assert records[-1]["content_type"] == "text/html"


@pytest.mark.parametrize("content_type", ["application/json", "text/plain", "PRIVATE-HEADER"])
async def test_success_and_unexpected_content_type_do_not_change_behavior(caplog, content_type):
    records = await invoke(caplog, lambda r: httpx.Response(200, json=grant(),
        headers={"content-type": content_type}), success=True)
    assert len(records) == 2
    assert records[-1]["failure_category"] == "NONE"
    assert records[-1]["response_parse_category"] == "valid_token_response"
    assert records[-1]["content_type_category"] == (
        "expected" if content_type == "application/json" else "unexpected_content_type")


async def test_refresh_and_revoke_have_no_new_diagnostics(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json=grant())
    )) as client:
        provider = DigiLockerProvider(settings(), client=client)
        await provider.refresh_access_token(SecretStr(PRIVATE[4]), now=datetime.now(UTC))
        await provider.revoke_token(SecretStr(PRIVATE[4]), "refresh_token")
    assert not [r for r in caplog.records if r.name == LOGGER]


async def test_read_timeout_after_headers_preserves_received_status(caplog):
    class BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"{"
            raise httpx.ReadTimeout(" ".join(PRIVATE))
    records = await invoke(caplog, lambda r: httpx.Response(200, stream=BrokenStream(),
        headers={"content-type": "application/json"}))
    assert records[-2]["response_received"] is True
    assert records[-1]["http_status"] == 200
    assert records[-1]["failure_category"] == "TIMEOUT"


@pytest.mark.parametrize("error", [
    "invalid_client", "invalid_grant", "invalid_request", "invalid_grant_type",
    "Provider.Error-42", "x", "x" * 64,
])
async def test_safe_unknown_error_identifier_is_preserved(caplog, error):
    records = await invoke(caplog, lambda r: httpx.Response(400, json={
        "error": error, "error_description": "PRIVATE-DESCRIPTION", "detail": PRIVATE[3],
    }))
    assert records[-1]["provider_oauth_error"] == error
    assert records[-1]["response_fields"] == ["detail", "error", "error_description"]


@pytest.mark.parametrize("error", [
    "", "x" * 65, "invalid grant", "invalid_grant\n", "error\r\ninjected",
    "error\x00", "érror", "error/value", "error=value", "https://example.invalid",
    None, True, PRIVATE[0], PRIVATE[1], PRIVATE[2], "prefix-" + PRIVATE[0],
])
async def test_invalid_or_reflected_error_identifier_is_redacted(caplog, error):
    records = await invoke(caplog, lambda r: httpx.Response(400, json={"error": error}))
    assert records[-1]["provider_oauth_error"] == "other_redacted"


@pytest.mark.parametrize("field,secret", [
    ("access_token", PRIVATE[3]), ("refresh_token", PRIVATE[4]),
    ("state", PRIVATE[5]), ("id_token", PRIVATE[6]),
    ("error_description", "PRIVATE-DESCRIPTION"),
])
async def test_reflected_response_secrets_cannot_be_error_identifiers(caplog, field, secret):
    records = await invoke(caplog, lambda r: httpx.Response(400, json={
        "error": secret, field: secret,
    }))
    assert records[-1]["provider_oauth_error"] == "other_redacted"


async def test_response_field_names_are_bounded_sanitized_and_never_values(caplog):
    payload = {"error": "invalid_grant_type", "error_description": "PRIVATE-DESCRIPTION",
               PRIVATE[1]: PRIVATE[3], "bad\nkey": PRIVATE[4], "x" * 65: PRIVATE[5]}
    records = await invoke(caplog, lambda r: httpx.Response(400, json=payload))
    assert records[-1]["response_fields"] == ["error", "error_description", "other_redacted"]
    caplog.clear()
    records = await invoke(caplog, lambda r: httpx.Response(400, json={
        f"field_{i:02}": PRIVATE[3] for i in range(100)
    }))
    assert len(records[-1]["response_fields"]) == 32
    assert records[-1]["response_fields"] == sorted(records[-1]["response_fields"])


async def test_success_response_field_names_are_not_logged(caplog):
    records = await invoke(caplog, lambda r: httpx.Response(200, json=grant()), success=True)
    assert "response_fields" not in records[-1]
