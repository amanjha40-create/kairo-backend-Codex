"""GitHub OAuth2 provider."""

from __future__ import annotations

from urllib.parse import urlencode

import httpx

from app.auth.providers.base import OAuthProfile, OAuthProvider
from app.config import Settings

_AUTH_URL = "https://github.com/login/oauth/authorize"
_TOKEN_URL = "https://github.com/login/oauth/access_token"
_USERINFO_URL = "https://api.github.com/user"
_EMAILS_URL = "https://api.github.com/user/emails"


class GitHubOAuthProvider(OAuthProvider):
    provider_name = "github"

    def get_auth_url(self, settings: Settings) -> str:
        params = {
            "client_id": settings.github_client_id,
            "redirect_uri": settings.github_redirect_uri,
            "scope": "read:user user:email",
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, settings: Settings) -> OAuthProfile:
        async with httpx.AsyncClient() as client:
            token_resp = await client.post(
                _TOKEN_URL,
                data={
                    "client_id": settings.github_client_id,
                    "client_secret": settings.github_client_secret,
                    "code": code,
                    "redirect_uri": settings.github_redirect_uri,
                },
                headers={"Accept": "application/json"},
            )
            token_resp.raise_for_status()
            access_token = token_resp.json().get("access_token")

            headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            }

            user_resp = await client.get(_USERINFO_URL, headers=headers)
            user_resp.raise_for_status()
            data = user_resp.json()

            # GitHub may not expose email publicly — fetch from /user/emails
            email = data.get("email")
            if not email:
                emails_resp = await client.get(_EMAILS_URL, headers=headers)
                emails_resp.raise_for_status()
                primary = next(
                    (e for e in emails_resp.json() if e.get("primary") and e.get("verified")),
                    None,
                )
                email = primary["email"] if primary else None

        if not email:
            raise ValueError("GitHub account has no verified email address")

        return OAuthProfile(
            provider_user_id=str(data["id"]),
            email=email,
            full_name=data.get("name"),
        )
