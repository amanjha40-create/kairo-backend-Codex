from html import unescape
from types import SimpleNamespace

import pytest

from app.integrations.digilocker.browser_return import browser_redirect, completion_page


@pytest.mark.parametrize(
    "environment,host,package,forbidden",
    [
        ("production", "api.kairoid.com", "com.kairoid.app", "com.kairo.app"),
        ("staging", "staging-api.kairoid.com", "com.kairo.app.staging", "com.kairoid.app"),
    ],
)
@pytest.mark.parametrize(
    "outcome", ["connected", "failed", "", "invalid&code=synthetic-code&state=synthetic-state"]
)
def test_android_fallback_package_is_environment_isolated(
    environment, host, package, forbidden, outcome
):
    callback = f"https://{host}/api/v1/integrations/digilocker/callback"
    settings = SimpleNamespace(
        app_env=SimpleNamespace(value=environment),
        digilocker_redirect_uri=callback,
        digilocker_connection_return_url=None,
    )
    response = completion_page(settings, outcome)
    html = unescape(response.body.decode())
    result = "connected" if outcome == "connected" else "failed"
    intent = (
        f"intent://{host}/api/v1/integrations/digilocker/complete"
        f"?digilocker_result={result}#Intent;scheme=https;package={package};end"
    )
    assert f'href="{intent}"' in html
    assert html.count("intent://") == 1
    assert forbidden not in html
    assert settings.digilocker_redirect_uri == callback
    assert "/callback" not in html
    assert "synthetic-" not in html
    for credential in (
        "code=",
        "state=",
        "access_token",
        "refresh_token",
        "client_secret",
        "code_verifier",
    ):
        assert credential not in html
    assert "If the app does not open, close this browser and return to KairoID." in html
    assert "Do not reload the authorization callback." in html
    assert "<script" not in html
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert completion_page(settings, outcome).body == response.body


@pytest.mark.parametrize("outcome", ["connected", "failed"])
def test_android_completion_redirect_path_is_unchanged(outcome):
    response = browser_redirect(outcome)
    assert response.status_code == 303
    assert response.headers["location"] == (
        "/api/v1/integrations/digilocker/complete?digilocker_result=" + outcome
    )
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
