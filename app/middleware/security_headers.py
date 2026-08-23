"""Apply browser-facing security headers and prevent sensitive API caching."""

from __future__ import annotations

from collections.abc import Iterable

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class SecurityHeadersMiddleware:
    """Attach safe defaults to every response without changing endpoint payloads."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        enable_hsts: bool,
        no_store_prefixes: Iterable[str] = (),
    ) -> None:
        self.app = app
        self.enable_hsts = enable_hsts
        self.no_store_prefixes = tuple(no_store_prefixes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("x-content-type-options", "nosniff")
                headers.setdefault("x-frame-options", "DENY")
                headers.setdefault("referrer-policy", "no-referrer")
                headers.setdefault(
                    "permissions-policy",
                    "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
                )
                headers.setdefault(
                    "content-security-policy",
                    "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
                    "form-action 'none'",
                )
                if self.enable_hsts:
                    headers.setdefault(
                        "strict-transport-security",
                        "max-age=31536000; includeSubDomains",
                    )
                if path.startswith(self.no_store_prefixes):
                    headers["cache-control"] = "private, no-store, max-age=0, must-revalidate"
                    headers["pragma"] = "no-cache"
            await send(message)

        await self.app(scope, receive, send_with_security_headers)
