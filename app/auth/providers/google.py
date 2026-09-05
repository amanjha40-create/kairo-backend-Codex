"""Google OAuth2 provider."""

from __future__ import annotations

from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWKClient
from jwt.exceptions import InvalidTokenError

from app.auth.providers.base import OAuthProfile, OAuthProvider
from app.config import Settings

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
_ISSUERS = {"https://accounts.google.com", "accounts.google.com"}


class GoogleOAuthProvider(OAuthProvider):
    provider_name = "google"

    def get_auth_url(
        self, settings: Settings, *, state: str = "", code_challenge: str = ""
    ) -> str:
        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "offline",
            "prompt": "select_account",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(
        self, code: str, settings: Settings, *, code_verifier: str = ""
    ) -> OAuthProfile:
        async with httpx.AsyncClient() as client:
            token_resp = await client.post(
                _TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uri": settings.google_redirect_uri,
                    "grant_type": "authorization_code",
                    "code_verifier": code_verifier,
                },
            )
            token_resp.raise_for_status()
            id_token = token_resp.json().get("id_token")
            if not id_token or not settings.google_client_id:
                raise ValueError("Google identity token is unavailable")
            try:
                signing_key = PyJWKClient(_JWKS_URL).get_signing_key_from_jwt(id_token)
                data = jwt.decode(
                    id_token,
                    signing_key.key,
                    algorithms=["RS256"],
                    audience=settings.google_client_id,
                    issuer=list(_ISSUERS),
                    options={"require": ["exp", "iss", "aud", "sub", "email", "email_verified"]},
                )
            except InvalidTokenError as exc:
                raise ValueError("Google identity token is invalid") from exc

        if data.get("email_verified") is not True:
            raise ValueError("Google email is not verified")
        if not isinstance(data.get("sub"), str) or not data["sub"].strip():
            raise ValueError("Google identity subject is invalid")
        if not isinstance(data.get("email"), str) or not data["email"].strip():
            raise ValueError("Google identity email is invalid")

        return OAuthProfile(
            provider_user_id=data["sub"],
            email=data["email"],
            full_name=data.get("name"),
            email_verified=True,
        )
