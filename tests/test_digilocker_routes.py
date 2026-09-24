from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from digilocker_helpers import settings

from app.api.v1.routes.digilocker import get_digilocker_service
from app.auth.deps import CurrentUser, get_current_user
from app.main import app
from app.services.digilocker_service import flow_error, unavailable

BASE = "/api/v1/integrations/digilocker"


@pytest.fixture
async def client_service():
    service = SimpleNamespace(
        settings=settings(),
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
    service.connect.assert_awaited_once_with(user.id)
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
        BASE + "/identity/verify",
        BASE + "/identity/verifications",
    }
    assert "security" not in schema["paths"][BASE + "/callback"]["get"]
    for path, method in [("/connect", "post"), ("/status", "get"), ("/connection", "delete")]:
        assert schema["paths"][BASE + path][method]["security"]
