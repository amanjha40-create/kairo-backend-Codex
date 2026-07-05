"""Abstract OAuth provider — all providers implement this contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.config import Settings


@dataclass
class OAuthProfile:
    """Normalised user profile returned by every provider."""

    provider_user_id: str
    email: str
    full_name: str | None = None


class OAuthProvider(ABC):
    """One implementation per OAuth provider — stateless, no DB access."""

    provider_name: str  # must match registry key and DB value

    @abstractmethod
    def get_auth_url(self, settings: Settings) -> str:
        """Return the provider's authorization URL to redirect the user to."""

    @abstractmethod
    async def exchange_code(self, code: str, settings: Settings) -> OAuthProfile:
        """Exchange auth code for a normalised OAuthProfile."""
