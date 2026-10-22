"""Credential-free browser completion. Outcomes never confer verification or access."""

from html import escape
import json
import secrets
from urllib.parse import urlsplit

from starlette.responses import HTMLResponse, RedirectResponse

COMPLETE_PATH = "/api/v1/integrations/digilocker/complete"
HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def browser_redirect(outcome: str) -> RedirectResponse:
    assert outcome in {"connected", "failed"}
    return RedirectResponse(
        COMPLETE_PATH + "?digilocker_result=" + outcome, status_code=303, headers=HEADERS
    )


def completion_page(settings, outcome: str, *, user_agent: str = "") -> HTMLResponse:
    outcome = "connected" if outcome == "connected" else "failed"
    origin = urlsplit(settings.digilocker_redirect_uri or "")
    # The destination comes only from validated server configuration, never Host or input.
    host = origin.netloc
    package = "com.kairo.app.staging" if settings.app_env.value == "staging" else "com.kairoid.app"
    intent = f"intent://{host}{COMPLETE_PATH}?digilocker_result={outcome}#Intent;scheme=https;package={package};end"
    title = "Return to KairoID" if outcome == "connected" else "Couldn't connect DigiLocker"
    message = (
        "Return to KairoID to check your connection and saved results."
        if outcome == "connected"
        else "This connection attempt could not be completed. "
        "Your saved verification results are preserved. "
        "Return to KairoID to check status and try again when you are ready."
    )
    web = settings.digilocker_connection_return_url
    web_action = (
        f'<p><a href="{escape(web + "?digilocker_result=" + outcome, quote=True)}">'
        "Continue in KairoID web</a></p>"
        if web
        else ""
    )
    # A session-scoped iOS return, never an OAuth credential or connection assertion.
    # Only explicitly supported environments receive an iOS auth-session return.
    # Never derive a scheme from request input or fall back across environments.
    iphone_scheme = {
        "staging": "com.kairoid.staging.digilocker",
        "production": "com.kairoid.digilocker",
    }.get(settings.app_env.value)
    # UA selects presentation only; it never confers identity or connection status.
    ua = user_agent[:2048].lower()
    ios = any(device in ua for device in ("iphone", "ipad", "ipod"))
    android = "android" in ua and not ios
    destination = None
    if ios and iphone_scheme:
        destination = f"{iphone_scheme}://complete?result={outcome}"
    elif android and origin.scheme == "https" and host:
        destination = intent
    action = (
        f'<a class="action" href="{escape(destination, quote=True)}">Return to KairoID</a>'
        if destination
        else "<p>Close this browser window and return to the KairoID app.</p>"
    )
    # iOS authentication sessions capture their registered scheme. One navigation
    # attempt only; keep the explicit fallback if the browser suppresses it.
    nonce = secrets.token_urlsafe(24)
    auto_return = (
        f'<script nonce="{nonce}">window.location.replace({json.dumps(destination)});</script>'
        if ios and destination else ""
    )
    body = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer"><title>{escape(title)} | KairoID</title>
<style>
html{{color-scheme:light dark}}
body{{margin:0;background:#eef8f7;color:#123354;font:1rem/1.6 sans-serif;padding:24px}}
main{{max-width:32rem;margin:8vh auto;background:#fff;padding:28px;
border:1px solid #c5e5e0;border-radius:24px}}
.brand{{font-size:1.6rem;font-weight:700;color:#008b89}}
h1{{font-size:1.5rem;line-height:1.3}}a{{color:#007c7a}}
.action{{display:block;text-align:center;background:#123354;color:#fff;
border-radius:16px;padding:14px;text-decoration:none}}
a:focus-visible{{outline:3px solid #00a99d;outline-offset:4px}}
@media(prefers-color-scheme:dark){{body{{background:#0b1824;color:#eef8f7}}
main{{background:#142a38;border-color:#35515e}}a,.brand{{color:#55ddd1}}
.action{{background:#008c87;color:#fff}}}}</style></head>
<body><main><p class="brand">KairoID</p><h1>{escape(title)}</h1><p>{escape(message)}</p>
{action}{web_action}
<p>If the app does not open, close this browser and return to KairoID.
Do not reload the authorization callback.</p>
</main>{auto_return}</body></html>"""
    # The HTTPS completion URL is handled by Android's verified App Link before this
    # fallback page is reached. The explicit package action covers browser suppression.
    return HTMLResponse(
        body,
        headers={
            **HEADERS,
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; "
                f"form-action 'none'; frame-ancestors 'none'; script-src 'nonce-{nonce}'"
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )
