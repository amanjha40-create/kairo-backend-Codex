"""Single lookup point for all OAuth providers — add new providers here only."""

from __future__ import annotations

from app.auth.providers.base import OAuthProvider
from app.auth.providers.github import GitHubOAuthProvider
from app.auth.providers.google import GoogleOAuthProvider
from app.auth.providers.linkedin import LinkedInOAuthProvider
from app.exceptions import NotFoundError

_REGISTRY: dict[str, OAuthProvider] = {
    "google": GoogleOAuthProvider(),
    "linkedin": LinkedInOAuthProvider(),
    "github": GitHubOAuthProvider(),
}

SUPPORTED_PROVIDERS = list(_REGISTRY.keys())


def get_provider(name: str) -> OAuthProvider:
    """Return provider by name — raises NotFoundError for unknown providers."""

    provider = _REGISTRY.get(name.lower())
    if provider is None:
        raise NotFoundError(f"OAuth provider '{name}' is not supported. Supported: {SUPPORTED_PROVIDERS}")
    return provider
