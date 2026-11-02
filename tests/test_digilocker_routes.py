from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from digilocker_helpers import settings

from app.api.v1.routes.digilocker import get_digilocker_service
from app.auth.deps import CurrentUser, get_current_user
from app.config import get_settings
from app.config.settings import AppEnvironment
from app.integrations.digilocker.browser_return import RETURN_COOKIE
from app.main import app
from app.services.digilocker_service import flow_error, unavailable

BASE = "/api/v1/integrations/digilocker"


@pytest.fixture
async def client_service():
    service = SimpleNamespace(
        settings=settings(),
        callback_client_target="web",
        connect=AsyncMock(
            return_value={
                "authorization_url": "https://provider.example.invalid/auth",
                "expires_at": datetime.now(UTC),
                "connection_state": "pending",
            }
        ),
        status=AsyncMock(
            return_value={
                "connected": False,
                "status": "disconnected",
                "connected_at": None,
                "consent_valid_until": None,
                "scopes": [],
            }
        ),
        callback=AsyncMock(return_value={"connection_state": "active"}),
        disconnect=AsyncMock(),
    )
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_digilocker_service] = lambda: service
    app.dependency_overrides[get_settings] = lambda: service.settings
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        yield client, service
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous)


def authenticated():
    principal = CurrentUser(id=uuid4(), email="synthetic@example.invalid", role="user")
    app.dependency_overrides[get_current_user] = lambda: principal
    return principal


@pytest.mark.parametrize(
    "method,path", [("POST", "/connect"), ("GET", "/status"), ("DELETE", "/connection")]
)
async def test_auth_required(client_service, method, path):
    client, service = client_service
    response = await client.request(method, BASE + path)
    assert response.status_code == 401
    service.connect.assert_not_awaited()
    service.status.assert_not_awaited()
    service.disconnect.assert_not_awaited()


async def test_authenticated_safe_contracts_and_no_public_refresh(client_service):
    client, service = client_service
    user = authenticated()
    response = await client.post(BASE + "/connect", json={})
    assert response.status_code == 200
    assert set(response.json()) == {"authorization_url", "expires_at", "connection_state"}
    assert response.headers["cache-control"] == "no-store"
    service.connect.assert_awaited_once_with(user.id, client_target="web")
    response = await client.get(BASE + "/status")
    assert response.status_code == 200
    assert set(response.json()) == {
        "connected",
        "status",
        "connected_at",
        "consent_valid_until",
        "scopes",
    }
    response = await client.delete(BASE + "/connection")
    assert response.status_code == 204
    service.disconnect.assert_awaited_once_with(user.id)
    assert (await client.post(BASE + "/refresh")).status_code == 404


@pytest.mark.parametrize(
    "query,body",
    [
        ("?return_to=https://attacker.invalid", {}),
        ("", {"return_to": "https://attacker.invalid"}),
        ("", {"user_id": str(uuid4())}),
    ],
)
async def test_connect_does_not_accept_return_url_or_owner_override(client_service, query, body):
    client, service = client_service
    authenticated()
    response = await client.post(BASE + "/connect" + query, json=body)
    assert response.status_code in {400, 422}
    service.connect.assert_not_awaited()


@pytest.mark.parametrize(
    "headers",
    [
        {"X-KairoID-Platform": "ios", "X-KairoID-Package": "com.kairoid.Kairo"},
        {"X-KairoID-Platform": "android", "X-KairoID-Package": "com.kairoid.app"},
        {"X-KairoID-Platform": "ios", "X-KairoID-Package": "attacker.invalid"},
        {"X-KairoID-Platform": "https://attacker.invalid", "X-KairoID-Package": "x"},
    ],
)
async def test_unknown_environment_binds_all_client_metadata_to_web(client_service, headers):
    client, service = client_service
    user = authenticated()
    response = await client.post(BASE + "/connect", json={}, headers=headers)
    assert response.status_code == 200
    service.connect.assert_awaited_once_with(user.id, client_target="web")


@pytest.mark.parametrize(
    "headers,expected",
    [
        (
            {"X-KairoID-Platform": "ios", "X-KairoID-Package": "com.kairoid.Kairo"},
            "ios",
        ),
        (
            {"X-KairoID-Platform": "android", "X-KairoID-Package": "com.kairoid.app"},
            "android",
        ),
        (
            {"X-KairoID-Platform": "ios", "X-KairoID-Package": "attacker.invalid"},
            "web",
        ),
    ],
)
async def test_production_connect_binds_only_allowlisted_client_metadata(
    client_service, headers, expected
):
    client, service = client_service
    service.settings = settings().model_copy(update={"app_env": AppEnvironment.PRODUCTION})
    user = authenticated()
    response = await client.post(BASE + "/connect", json={}, headers=headers)
    assert response.status_code == 200
    service.connect.assert_awaited_once_with(user.id, client_target=expected)


async def test_staging_connect_accepts_only_staging_android_package(client_service):
    client, service = client_service
    service.settings = settings().model_copy(update={"app_env": AppEnvironment.STAGING})
    user = authenticated()
    headers = {
        "X-KairoID-Platform": "android",
        "X-KairoID-Package": "com.kairo.app.staging",
    }
    assert (await client.post(BASE + "/connect", json={}, headers=headers)).status_code == 200
    service.connect.assert_awaited_once_with(user.id, client_target="android")


async def test_callback_is_public_no_credentials_in_completion(client_service):
    client, service = client_service
    response = await client.get(
        BASE + "/callback", params={"code": "test-code", "state": "test-state"}
    )
    assert response.status_code == 200
    assert response.json() == {"connection_state": "active"}
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    service.callback.assert_awaited_once_with(code="test-code", state="test-state", error=None)
    service.settings.digilocker_connection_return_url = "https://candidate.example.invalid/complete"
    response = await client.get(
        BASE + "/callback", params={"code": "test-code", "state": "test-state"}
    )
    assert response.status_code == 303
    assert (
        response.headers["location"]
        == "https://candidate.example.invalid/complete?digilocker_result=connected"
    )
    assert "test-code" not in response.headers["location"]
    assert "test-state" not in response.headers["location"]


@pytest.mark.parametrize(
    "query",
    [
        "state=a&state=b&code=x",
        "state=a&code=x&code=y",
        "state=a&return_to=https://attacker.invalid",
    ],
)
async def test_callback_rejects_ambiguous_or_redirect_inputs(client_service, query):
    client, service = client_service
    response = await client.get(BASE + "/callback?" + query)
    assert response.status_code == 400
    service.callback.assert_not_awaited()


@pytest.mark.parametrize(
    "error,status", [(flow_error("consent_denied"), 400), (unavailable(), 503)]
)
async def test_callback_errors_safe_and_uncached(client_service, error, status):
    client, service = client_service
    service.callback.side_effect = error
    response = await client.get(
        BASE + "/callback",
        params={
            "state": "test-state",
            "error": "access_denied",
            "error_description": "private provider payload",
        },
    )
    assert response.status_code == status
    assert response.json()["error"]["code"] == error.code
    assert "private provider payload" not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert "error_description" not in service.callback.call_args.kwargs


def test_openapi_exposes_connection_and_document_routes():
    schema = app.openapi()
    assert {path for path in schema["paths"] if path.startswith(BASE)} == {
        BASE + "/connect",
        BASE + "/callback",
        BASE + "/status",
        BASE + "/connection",
        BASE + "/documents/issued",
        BASE + "/documents/retrieve",
        BASE + "/available-records",
        BASE + "/records/import",
        BASE + "/identity/verify",
        BASE + "/identity/verifications",
        BASE + "/identity/trust",
        BASE + "/eaadhaar/availability",
        BASE + "/eaadhaar/verify",
    }
    assert "security" not in schema["paths"][BASE + "/callback"]["get"]
    identity_fields = schema["components"]["schemas"]["IdentityVerificationItem"][
        "properties"
    ]
    assert {"verification_status", "verification_source", "verified_at"} <= set(
        identity_fields
    )
    address_fields = schema["components"]["schemas"]["AddressCandidate"]["properties"]
    assert set(address_fields) == {
        "candidate_id",
        "doctype",
        "display_type",
        "source",
        "review_state",
        "candidate_type",
        "address_state",
        "document_address_type",
        "requires_permanent_confirmation",
        "requires_replacement_confirmation",
        "address",
        "structured_address",
    }
    assert address_fields["address"]["$ref"].endswith("/PermanentAddressInput-Output")
    prefill_fields = schema["components"]["schemas"]["AddressPrefillCandidate"][
        "properties"
    ]
    assert set(prefill_fields) == {
        "candidate_id",
        "doctype",
        "display_type",
        "source",
        "review_state",
        "candidate_type",
        "address_state",
        "document_address_type",
        "requires_permanent_confirmation",
        "requires_replacement_confirmation",
        "prefill_text",
        "structured_address",
    }
    response_fields = schema["components"]["schemas"]["AvailableRecordsResponse"][
        "properties"
    ]
    assert {
        "address_prefill_candidates",
        "address_discovery_state",
        "discovery_status",
    } <= set(response_fields)
    record_fields = schema["components"]["schemas"]["AvailableRecord"]["properties"]
    assert "failure_reason" in record_fields
    assert "google_place_id" not in repr(prefill_fields)
    for path, method in [("/connect", "post"), ("/status", "get"), ("/connection", "delete")]:
        assert schema["paths"][BASE + path][method]["security"]


@pytest.mark.parametrize(
    "error", [None, flow_error("callback_invalid"), flow_error("consent_denied"), unavailable()]
)
async def test_browser_callback_uses_credential_free_app_link(client_service, error):
    client, service = client_service
    service.callback.side_effect = error
    response = await client.get(
        BASE + "/callback?code=synthetic-code&state=synthetic-state",
        headers={"Accept": "text/html"},
    )
    assert response.status_code == 303
    expected = "failed" if error else "connected"
    assert response.headers["location"] == BASE + "/complete?digilocker_result=" + expected
    assert "client_target" not in response.headers["location"]
    assert "return_url" not in response.headers["location"]
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "secure" in response.headers["set-cookie"].lower()
    assert "samesite=lax" in response.headers["set-cookie"].lower()
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    assert "synthetic-" not in response.text + response.headers["location"]
    service.callback.assert_awaited_once()
    service.connect.assert_not_awaited()
    service.disconnect.assert_not_awaited()


async def test_browser_invalid_query_also_returns_safely(client_service):
    client, service = client_service
    response = await client.get(
        BASE + "/callback?state=a&state=b&code=synthetic", headers={"Accept": "text/html"}
    )
    assert response.status_code == 303
    assert response.headers["location"].endswith("digilocker_result=failed")
    service.callback.assert_not_awaited()


async def test_browser_callback_completion_uses_state_bound_ios_target_not_user_agent(
    client_service,
):
    client, service = client_service
    service.settings = settings().model_copy(
        update={
            "app_env": AppEnvironment.PRODUCTION,
            "digilocker_redirect_uri": (
                "https://api.kairoid.com/api/v1/integrations/digilocker/callback"
            ),
        }
    )
    service.callback_client_target = "ios"
    callback_response = await client.get(
        BASE + "/callback?code=synthetic-code&state=synthetic-state",
        headers={"Accept": "text/html", "User-Agent": "Mozilla/5.0 Android"},
    )
    cookie = callback_response.headers["set-cookie"].split(";", 1)[0]
    completion = await client.get(
        callback_response.headers["location"],
        headers={"Cookie": cookie, "User-Agent": "Mozilla/5.0 Android"},
    )
    assert completion.status_code == 200
    assert "com.kairoid.digilocker://complete?result=connected" in completion.text
    assert "intent://" not in completion.text
    assert RETURN_COOKIE in completion.headers["set-cookie"]
    assert "Max-Age=0" in completion.headers["set-cookie"]


async def test_tampered_return_cookie_fails_closed_without_mobile_action(client_service):
    client, service = client_service
    service.settings = settings().model_copy(
        update={
            "app_env": AppEnvironment.PRODUCTION,
            "digilocker_redirect_uri": (
                "https://api.kairoid.com/api/v1/integrations/digilocker/callback"
            ),
        }
    )
    response = await client.get(
        BASE + "/complete?digilocker_result=connected",
        headers={
            "Cookie": RETURN_COOKIE + "=tampered",
            "User-Agent": "Mozilla/5.0 (iPhone)",
        },
    )
    assert response.status_code == 200
    assert 'class="action"' not in response.text
    assert "com.kairoid.digilocker:" not in response.text
    assert "intent://" not in response.text


@pytest.mark.parametrize(
    "query",
    [
        "digilocker_result=connected",
        "digilocker_result=failed",
        "digilocker_result=connected&code=synthetic-secret",
        "digilocker_result=connected&digilocker_result=failed",
    ],
)
async def test_completion_fallback_is_safe(client_service, query):
    client, service = client_service
    response = await client.get(BASE + "/complete?" + query)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "KairoID" in response.text and "Return to KairoID" in response.text
    assert "synthetic-secret" not in response.text
    assert "digilocker_callback_invalid" not in response.text
    assert "raw state" not in response.text
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert response.headers["referrer-policy"] == "no-referrer"
    if query != "digilocker_result=connected":
        assert "Couldn't connect DigiLocker".replace("'", "&#x27;") in response.text
    service.callback.assert_not_awaited()
    service.connect.assert_not_awaited()
    service.disconnect.assert_not_awaited()
