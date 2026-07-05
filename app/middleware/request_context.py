"""Attach correlation IDs and structured HTTP access logging."""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import get_settings
from app.core.constants import HttpHeader
from app.logging import get_logger
from app.logging.context import bind_request_context, reset_request_context

_access_logger = get_logger("http.access")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Generate/propagate correlation IDs and emit one structured access log line per request."""

    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        request_id = request.headers.get(HttpHeader.REQUEST_ID) or str(uuid.uuid4())
        correlation_id = request.headers.get(HttpHeader.CORRELATION_ID) or request_id

        bind_request_context(request_id=request_id, correlation_id=correlation_id)
        request.state.request_id = request_id
        request.state.correlation_id = correlation_id

        response: Response | None = None
        started = time.perf_counter()
        try:
            response = await call_next(request)
            return response
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            status_code = response.status_code if response is not None else 500

            if settings.log_access_enabled:
                client_host = request.client.host if request.client else None
                route_path = ""
                route_obj = request.scope.get("route")
                if route_obj is not None and hasattr(route_obj, "path"):
                    route_path = getattr(route_obj, "path", "") or ""

                _access_logger.info(
                    "request_completed",
                    extra={
                        "event": "http_access",
                        "http_method": request.method,
                        "http_path": request.url.path,
                        "http_route": route_path,
                        "status_code": status_code,
                        "duration_ms": round(duration_ms, 3),
                        "client_host": client_host,
                    },
                )

            reset_request_context()

            if response is not None:
                response.headers[HttpHeader.REQUEST_ID] = request_id
                response.headers[HttpHeader.CORRELATION_ID] = correlation_id
