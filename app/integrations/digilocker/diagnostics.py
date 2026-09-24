"""Allowlisted metadata for code exchange only; never retain wire payloads."""

import logging
import socket
import ssl
from time import monotonic
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)
OAUTH_ERRORS = frozenset({
    "invalid_request", "invalid_client", "invalid_grant", "unauthorized_client",
    "unsupported_grant_type", "invalid_scope", "access_denied", "server_error",
    "temporarily_unavailable",
})


def transport_category(exc):
    current, seen = exc, set()
    for _ in range(8):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        if isinstance(current, ssl.SSLError):
            return "TLS", "TLS_ERROR"
        if isinstance(current, socket.gaierror):
            return "DNS", "TRANSPORT_ERROR"
        current = current.__cause__ or current.__context__
    if isinstance(exc, httpx.ConnectTimeout):
        return "CONNECT_TIMEOUT", "TIMEOUT"
    if isinstance(exc, httpx.ReadTimeout):
        return "READ_TIMEOUT", "TIMEOUT"
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return "OTHER", "TIMEOUT"
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError)):
        return "CONNECTION", "TRANSPORT_ERROR"
    return "OTHER", "TRANSPORT_ERROR"


class ExchangeDiagnostics:
    def __init__(self, url, data):
        endpoint = urlsplit(url)
        # Runtime configuration is validated, but only known public endpoint labels
        # are emitted so even a misconfigured path cannot become a log exfiltration channel.
        self.endpoint = {
            "provider": "digilocker",
            "endpoint_host": (endpoint.hostname if endpoint.hostname ==
                              "digilocker.meripehchaan.gov.in" else "other"),
            "endpoint_path": (endpoint.path if endpoint.path in {
                "/public/oauth2/1/token", "/public/oauth2/2/token"} else "other"),
        }
        self.started = monotonic()
        self.status = None
        self.content_type = "missing"
        self.parse_category = "not_read"
        self.error_code = "absent"
        self.failure = None
        logger.info("digilocker_token_exchange_started", extra=self.endpoint | {
            "grant_type": "authorization_code", "client_auth_method": "http_basic",
            "redirect_uri_present": bool(data.get("redirect_uri")),
            "code_verifier_present": bool(data.get("code_verifier")),
            "code_present": bool(data.get("code")),
            "timeout_seconds": {"total": 15, "connect": 3, "pool": 3,
                                "read": 10, "write": 10},
        })

    def received(self, response):
        self.status = response.status_code
        media = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        self.content_type = media if media in {
            "application/json", "text/html", "text/plain", "application/octet-stream"
        } else ("other" if media else "missing")

    def parsed(self, payload):
        self.parse_category = "json"
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, str) and error in OAUTH_ERRORS:
            self.error_code = error
        elif error is not None:
            self.error_code = "other_redacted"

    def schema_failure(self, payload):
        self.failure = "TOKEN_SCHEMA_ERROR"
        self.parse_category = "schema_validation_failure"
        if not isinstance(payload, dict):
            return
        if "access_token" not in payload:
            self.parse_category = "missing_access_token"
        elif not isinstance(payload.get("token_type"), str) or (
            payload["token_type"].lower() != "bearer"
        ):
            self.parse_category = "malformed_token_type"
        elif type(payload.get("expires_in")) is not int or not (
            1 <= payload["expires_in"] <= 31_536_000
        ):
            self.parse_category = "malformed_expiry"

    def transport_error(self, exc):
        category, self.failure = transport_category(exc)
        known = (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout,
                 httpx.PoolTimeout, httpx.ConnectError, httpx.ReadError, httpx.WriteError,
                 httpx.CloseError, httpx.RemoteProtocolError, httpx.LocalProtocolError,
                 httpx.ProxyError, TimeoutError)
        exception_class = next((t.__name__ for t in known if type(exc) is t), "HTTPError")
        logger.info("digilocker_token_exchange_transport_error", extra=self.endpoint | {
            "exception_class": exception_class, "category": category,
            "failure_category": self.failure, "elapsed_ms": self.elapsed(),
            "response_received": self.status is not None,
        })

    def elapsed(self):
        return max(0, round((monotonic() - self.started) * 1000))

    def finish(self):
        if self.status is not None:
            logger.info("digilocker_token_exchange_response", extra=self.endpoint | {
                "http_status": self.status, "elapsed_ms": self.elapsed(),
                "content_type": self.content_type,
                "content_type_category": ("expected" if self.content_type ==
                                          "application/json" else "unexpected_content_type"),
                "response_parse_category": self.parse_category,
                "provider_oauth_error": self.error_code,
                "failure_category": self.failure or (
                    "PROVIDER_HTTP_REJECTION" if self.status != 200 else "NONE"),
            })
