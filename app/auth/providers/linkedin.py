"""LinkedIn OAuth2 provider."""

from __future__ import annotations

from urllib.parse import urlencode

import httpx

from app.auth.providers.base import OAuthProfile, OAuthProvider
from app.config import Settings

_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"


class LinkedInOAuthProvider(OAuthProvider):
    provider_name = "linkedin"

    def get_auth_url(self, settings: Settings) -> str:
        params = {
            "response_type": "code",
            "client_id": settings.linkedin_client_id,
            "redirect_uri": settings.linkedin_redirect_uri,
            "scope": "openid profile email",
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, settings: Settings) -> OAuthProfile:
        async with httpx.AsyncClient() as client:
            token_resp = await client.post(
                _TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.linkedin_redirect_uri,
                    "client_id": settings.linkedin_client_id,
                    "client_secret": settings.linkedin_client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            token_resp.raise_for_status()
            access_token = token_resp.json().get("access_token")

            user_resp = await client.get(
                _USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            user_resp.raise_for_status()
            data = user_resp.json()

        return OAuthProfile(
            provider_user_id=data["sub"],
            email=data["email"],
            full_name=data.get("name"),
        )
