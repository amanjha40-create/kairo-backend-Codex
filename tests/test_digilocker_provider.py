from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from digilocker_helpers import config_values, settings
from pydantic import SecretStr

from app.config import Settings
from app.integrations.digilocker.configuration import DigiLockerConfigurationError
from app.integrations.digilocker.provider import DigiLockerProvider, ProviderError, parse_grant


@pytest.mark.parametrize(
    "field",
    [
        "client_id",
        "client_secret",
        "authorize_url",
        "token_url",
        "revoke_url",
        "redirect_uri",
    ],
)
def test_missing_configuration_fails_closed(field):
    values = config_values()
    values["digilocker_" + field] = None
    with pytest.raises(DigiLockerConfigurationError):
        Settings(**values)


@pytest.mark.parametrize(
    "value",
    [
        "http://example.invalid/token",
        "https://localhost/token",
        "https://127.0.0.1/token",
        "https://user:password@example.invalid/token",
        "https://example.invalid/token?q=secret",
        "https://example.invalid/token#fragment",
        "https://example.invalid:bad/token",
        "https://example.invalid/ token",
        "https://example.invalid\\other/token",
    ],
)
def test_unsafe_provider_configuration_rejected(value):
    with pytest.raises(DigiLockerConfigurationError):
        settings(digilocker_token_url=value)


def test_return_url_is_operator_allowlisted_and_no_secret_repr():
    with pytest.raises(DigiLockerConfigurationError):
        settings(digilocker_connection_return_url="https://attacker.invalid/done")
    config = settings(
        candidate_portal_base_url="https://candidate.example.invalid",
        digilocker_connection_return_url="https://candidate.example.invalid/done",
    )
    assert config.digilocker_client_secret.get_secret_value() not in repr(config)


@pytest.mark.parametrize(
    "overrides",
    [
        {"log_access_enabled": False},
        {"log_level": "DEBUG"},
        {"database_echo_sql": True},
    ],
)
def test_unsafe_logging_configuration_rejected(overrides):
    with pytest.raises(DigiLockerConfigurationError):
        settings(**overrides)


def test_authorize_exact_callback_pkce_and_optional_consent():
    config = settings(
        digilocker_purpose="educational",
        digilocker_req_doctypes="ABCDE",
        digilocker_consent_ttl=600,
    )
    now = datetime.now(UTC)
    url = DigiLockerProvider(config).build_authorization_url(
        state="synthetic-state", challenge="test-challenge", now=now
    )
    params = parse_qs(urlsplit(url).query)
    assert params == {
        "response_type": ["code"],
        "client_id": ["synthetic-client"],
        "redirect_uri": [config.digilocker_redirect_uri],
        "state": ["synthetic-state"],
        "code_challenge": ["test-challenge"],
        "code_challenge_method": ["S256"],
        "purpose": ["educational"],
        "req_doctype": ["ABCDE"],
        "consent_valid_till": [str(int(now.timestamp()) + 600)],
    }
    assert config.digilocker_client_secret.get_secret_value() not in url


def valid_payload():
    return dict(
        access_token="synthetic-access",
        refresh_token="synthetic-refresh",
        token_type="Bearer",
        expires_in=3600,
    )


@pytest.mark.parametrize(
    "delta",
    [
        {"access_token": ""},
        {"access_token": 3},
        {"access_token": "\ud800"},
        {"refresh_token": None},
        {"refresh_token": "\n"},
        {"token_type": "MAC"},
        {"expires_in": True},
        {"expires_in": "3600"},
        {"expires_in": 0},
        {"scope": {}},
        {"consent_valid_till": 1},
        {"consent_valid_till": True},
    ],
)
def test_invalid_grant_shapes_sanitized(delta):
    with pytest.raises(ProviderError, match="DigiLocker provider request failed"):
        parse_grant(valid_payload() | delta, datetime.now(UTC))


def test_identity_and_document_scopes_discarded():
    payload = valid_payload() | {
        "scope": "openid files.issueddocs issued/ABCDE-12345-PAN files.issueddocs unrecognized",
        "name": "Synthetic Only",
        "digilockerid": "private-provider-id",
        "dob": "2000-01-01",
    }
    result = parse_grant(payload, datetime.now(UTC))
    assert result.scopes == ["files.issueddocs", "openid"]
    assert not hasattr(result, "digilockerid")
    assert "synthetic-access" not in repr(result)


async def test_wire_contract_code_refresh_revoke():
    calls = []

    def handle(request):
        calls.append(request)
        assert request.headers["authorization"].startswith("Basic ")
        assert request.extensions["timeout"]["connect"] == 3
        if request.url.path == "/revoke":
            return httpx.Response(200)
        return httpx.Response(200, json=valid_payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        config = settings()
        provider = DigiLockerProvider(config, client=client)
        await provider.exchange_authorization_code(
            SecretStr("test-code"), SecretStr("test-verifier"), now=datetime.now(UTC)
        )
        await provider.refresh_access_token(SecretStr("test-refresh"), now=datetime.now(UTC))
        await provider.revoke_token(SecretStr("test-refresh"), "refresh_token")
    assert parse_qs(calls[0].content.decode()) == {
        "grant_type": ["authorization_code"],
        "code": ["test-code"],
        "redirect_uri": [config.digilocker_redirect_uri],
        "code_verifier": ["test-verifier"],
    }
    assert parse_qs(calls[1].content.decode())["grant_type"] == ["refresh_token"]
    assert parse_qs(calls[2].content.decode())["token_type_hint"] == ["refresh_token"]


@pytest.mark.parametrize(
    "mode,category",
    [
        ("timeout", "provider_unavailable"),
        ("invalid_grant", "invalid_grant"),
        ("redirect", "provider_unavailable"),
        ("invalid_json", "invalid_response"),
        ("large", "invalid_response"),
        ("unavailable", "provider_unavailable"),
    ],
)
async def test_http_failures_are_bounded_and_sanitized(mode, category):
    def handle(request):
        if mode == "timeout":
            raise httpx.ReadTimeout("sensitive-test-data", request=request)
        if mode == "invalid_grant":
            return httpx.Response(
                400, json={"error": "invalid_grant", "error_description": "private"}
            )
        if mode == "redirect":
            return httpx.Response(302, headers={"Location": "https://attacker.invalid"}, json={})
        if mode == "invalid_json":
            return httpx.Response(200, content=b"private invalid data")
        if mode == "large":
            return httpx.Response(200, content=b"x" * 65_537)
        return httpx.Response(500, json={"private": "data"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        provider = DigiLockerProvider(settings(), client=client)
        with pytest.raises(ProviderError) as exc:
            await provider.refresh_access_token(SecretStr("test-refresh"), now=datetime.now(UTC))
        assert exc.value.category == category
        assert "private" not in str(exc.value)
        assert "sensitive" not in str(exc.value)


def test_dependency_and_no_identity_columns():
    from app.models import DigiLockerConnection

    names = set(DigiLockerConnection.__table__.columns.keys())
    assert not names & {
        "access_token",
        "refresh_token",
        "aadhaar",
        "pan",
        "digilocker_id",
        "name",
        "dob",
        "gender",
        "address",
        "profile",
        "reference_key",
    }
    assert "encrypted_access_token" in names
