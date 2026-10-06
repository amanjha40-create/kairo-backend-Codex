from types import SimpleNamespace

import pytest

from app.integrations.digilocker.browser_return import completion_page


@pytest.mark.parametrize("outcome", ["connected", "failed", "unknown&code=synthetic-secret"])
@pytest.mark.parametrize("environment", ["staging", "production"])
def test_iphone_return_is_fixed_staging_only_and_preserves_other_actions(outcome, environment):
    settings = SimpleNamespace(
        app_env=SimpleNamespace(value=environment),
        digilocker_redirect_uri="https://staging-api.example.invalid/api/v1/integrations/digilocker/callback",
        digilocker_connection_return_url="https://candidate.example.invalid/verify-digilocker",
    )
    response = completion_page(settings, outcome)
    html = response.body.decode()
    expected = "connected" if outcome == "connected" else "failed"
    if environment == "staging":
        assert "Return to KairoID on iPhone" in html
        assert f'com.kairoid.staging.digilocker://complete?result={expected}"' in html
        assert html.count("com.kairoid.staging.digilocker:") == 1
    else:
        assert "com.kairoid.staging.digilocker" not in html
        assert "on iPhone" not in html
    package = "com.kairo.app.staging" if environment == "staging" else "com.kairo.app"
    assert f"package={package};end" in html
    assert "intent://staging-api.example.invalid/" in html
    assert "Continue in KairoID web" in html
    assert "close this browser and return to KairoID" in html
    assert "synthetic-secret" not in html
    assert "code=" not in html and "state=" not in html
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
