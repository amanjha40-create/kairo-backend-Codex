"""Email provider abstraction."""

from __future__ import annotations

from typing import Protocol

from app.schemas.email_delivery import EmailSendResult, RenderedEmailMessage


class EmailProvider(Protocol):
    async def send(self, message: RenderedEmailMessage) -> EmailSendResult: ...
