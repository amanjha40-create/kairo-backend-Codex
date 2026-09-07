"""Redact URL credentials before request details reach application logs."""

from __future__ import annotations

import re

_SENSITIVE_PATHS = (
    re.compile(
        r"(?P<prefix>(?:https?://[^/\s]+)?(?:(?:/api/v1)?/public/employer-verifications?/|/employer-verification/))(?P<credential>[^/?\s]+)"
    ),
    re.compile(
        r"(?P<prefix>(?:https?://[^/\s]+)?(?:(?:/api/v1)?/public/passport/|/p/))(?P<credential>[^/?\s]+)"
    ),
    re.compile(
        r"(?P<prefix>(?:https?://[^/\s]+)?(?:(?:/api/v1)?/public/institution-verifications/|/institution/verify/))(?P<credential>[^/?\s]+)"
    ),
    re.compile(
        r"(?P<prefix>(?:https?://[^/\s]+)?(?:/api/v1)?/trust-invitations/)(?P<credential>[^/?\s]+)"
    ),
)
_SENSITIVE_QUERY_PARAMS = re.compile(
    r"(?P<prefix>[?&](?:token|reset_token|code|state|handoff|magic_token|invitation_token)=)(?P<credential>[^&#\s]+)",
    re.IGNORECASE,
)


def redact_request_credentials(value: str) -> str:
    """Replace path and query credentials without retaining any token material."""

    redacted = value
    for pattern in _SENSITIVE_PATHS:
        redacted = pattern.sub(r"\g<prefix>[REDACTED]", redacted)
    return _SENSITIVE_QUERY_PARAMS.sub(r"\g<prefix>[REDACTED]", redacted)
