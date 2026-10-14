from html.parser import HTMLParser
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from app.integrations.digilocker.browser_return import completion_page


@pytest.mark.parametrize(
    "outcome",
    [
        "connected",
        "failed",
        "unknown&code=synthetic-secret",
        'connected\"><script>alert("synthetic")</script>',
        "connected&access_token=synthetic-token&refresh_token=synthetic-refresh",
        "failed&client_secret=synthetic-secret&candidate_id=synthetic-id&provider_id=synthetic",
        "CONNECTED",
        "",
    ],
)
@pytest.mark.parametrize("environment", ["staging", "production"])
def test_iphone_return_is_environment_isolated_and_preserves_other_actions(outcome, environment):
    host = "staging-api.kairoid.com" if environment == "staging" else "api.kairoid.com"
    settings = SimpleNamespace(
        app_env=SimpleNamespace(value=environment),
        digilocker_redirect_uri=f"https://{host}/api/v1/integrations/digilocker/callback",
        digilocker_connection_return_url="https://candidate.example.invalid/verify-digilocker",
    )
    response = completion_page(settings, outcome)
    html = response.body.decode()
    expected = "connected" if outcome == "connected" else "failed"
    scheme = (
        "com.kairoid.staging.digilocker" if environment == "staging" else "com.kairoid.digilocker"
    )
    forbidden = (
        "com.kairoid.digilocker" if environment == "staging" else "com.kairoid.staging.digilocker"
    )
    assert "Return to KairoID on iPhone" in html
    assert f'{scheme}://complete?result={expected}"' in html
    assert html.count(scheme + ":") == 1
    assert forbidden not in html
    links = CompletionLinks()
    links.feed(html)
    iphone_links = [href for href in links.hrefs if href.startswith(scheme + ":")]
    assert iphone_links == [f"{scheme}://complete?result={expected}"]
    target = urlsplit(iphone_links[0])
    assert target.netloc == "complete" and target.path == "" and target.fragment == ""
    assert parse_qs(target.query) == {"result": [expected]}
    package = "com.kairo.app.staging" if environment == "staging" else "com.kairoid.app"
    assert f"package={package};end" in html
    assert (
        f'intent://{host}/api/v1/integrations/digilocker/complete?digilocker_result={expected}'
        f'#Intent;scheme=https;package={package};end"'
    ) in html
    assert "Continue in KairoID web" in html
    assert "close this browser and return to KairoID" in html
    assert "synthetic-secret" not in html
    for forbidden_value in (
        "access_token", "refresh_token", "client_secret", "candidate_id", "provider_id",
        "synthetic-token", "<script", "code_verifier",
    ):
        assert forbidden_value not in html
    assert "code=" not in html and "state=" not in html
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-type"].startswith("text/html")
    assert response.status_code == 200
    assert completion_page(settings, outcome).body == response.body


class CompletionLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.hrefs.extend(value for name, value in attrs if name == "href")


@pytest.mark.parametrize("environment", ["development", "test", "unknown", "PRODUCTION", ""])
@pytest.mark.parametrize("outcome", ["connected", "failed"])
def test_other_environments_do_not_inherit_an_iphone_return(environment, outcome):
    settings = SimpleNamespace(
        app_env=SimpleNamespace(value=environment),
        digilocker_redirect_uri=None,
        digilocker_connection_return_url=None,
    )
    html = completion_page(settings, outcome).body.decode()
    assert "com.kairoid.digilocker" not in html
    assert "com.kairoid.staging.digilocker" not in html
    assert "Return to KairoID on iPhone" not in html
    assert "Close this browser window and return to the KairoID app." in html
