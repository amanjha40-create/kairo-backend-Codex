"""Allowlisted metadata for code exchange only; never retain wire payloads."""

import logging
import re
import socket
import ssl
from time import monotonic
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)
SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9._-]{1,64}", re.ASCII)
SENSITIVE_FIELDS = frozenset({
    "code", "authorization_code", "state", "code_verifier", "client_id",
    "client_secret", "access_token", "refresh_token", "id_token", "error_description",
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
    def __init__(self, url, data, *, client_id="", client_secret=""):
        self._protected_values = tuple(value for value in (
            data.get("code"), data.get("code_verifier"), client_id, client_secret,
        ) if isinstance(value, str) and value)
        self.response_fields = None
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
            "grant_type": "authorization_code", "client_auth_method": "client_secret_post",
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
        protected = self._protected_values + tuple(
            value for key, value in (payload.items() if isinstance(payload, dict) else ())
            if key in SENSITIVE_FIELDS and isinstance(value, str) and value
        )

        def safe_identifier(value):
            return (isinstance(value, str) and SAFE_IDENTIFIER.fullmatch(value) is not None
                    and not any(secret in value for secret in protected))

        # Syntax alone is insufficient if a provider echoes a known credential.
        if safe_identifier(error):
            self.error_code = error
        elif isinstance(payload, dict) and "error" in payload:
            self.error_code = "other_redacted"
        if self.status is not None and not 200 <= self.status < 300 and isinstance(payload, dict):
            self.response_fields = sorted({
                key if safe_identifier(key) else "other_redacted" for key in payload
            })[:32]

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
            } | ({"response_fields": self.response_fields}
                 if self.response_fields is not None else {}))
