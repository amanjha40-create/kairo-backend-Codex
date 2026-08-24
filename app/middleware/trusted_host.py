"""Trusted-host enforcement with a narrow exception for internal health probes."""

from __future__ import annotations

from ipaddress import ip_address

from starlette.datastructures import Headers
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import Receive, Scope, Send

_HEALTH_PROBE_METHODS = frozenset({"GET", "HEAD"})
_HEALTH_PROBE_PATHS = frozenset(
    {
        "/api/v1/health/live",
        "/api/v1/health/ready",
    }
)


def _host_matches_local_address(scope: Scope) -> bool:
    host_header = Headers(scope=scope).get("host", "")
    hostname = host_header.rsplit(":", 1)[0]
    server = scope.get("server")
    if not server:
        return False

    try:
        host_address = ip_address(hostname)
        server_address = ip_address(server[0])
    except ValueError:
        return False
    return host_address == server_address


class HealthAwareTrustedHostMiddleware(TrustedHostMiddleware):
    """Allow local-address probes only on exact canonical health endpoints."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope.get("method") in _HEALTH_PROBE_METHODS
            and scope.get("path") in _HEALTH_PROBE_PATHS
            and _host_matches_local_address(scope)
        ):
            await self.app(scope, receive, send)
            return

        await super().__call__(scope, receive, send)
