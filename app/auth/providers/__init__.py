"""OAuth provider implementations — pluggable via registry."""

from app.auth.providers.base import OAuthProfile, OAuthProvider
from app.auth.providers.github import GitHubOAuthProvider
from app.auth.providers.google import GoogleOAuthProvider
from app.auth.providers.linkedin import LinkedInOAuthProvider

__all__ = [
    "GitHubOAuthProvider",
    "GoogleOAuthProvider",
    "LinkedInOAuthProvider",
    "OAuthProfile",
    "OAuthProvider",
]
