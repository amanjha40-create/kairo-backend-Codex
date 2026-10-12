"""Account-free referee capabilities are not candidate JWT endpoints."""

from fastapi import Request

from app.config import get_settings
from app.exceptions import ForbiddenError


def capability_only(request: Request):
    if request.headers.get("authorization"):
        raise ForbiddenError("Use the private referee link without an account session")


def manager_capability(request: Request):
    capability_only(request)
    origin = request.headers.get("origin")
    expected = get_settings().manager_reference_public_base_url
    if origin and (not expected or origin.rstrip("/") != expected):
        raise ForbiddenError("Cross-origin reference submission is not allowed")


def employer_capability(request: Request):
    capability_only(request)
    origin = request.headers.get("origin")
    allowed = {str(request.base_url).rstrip("/")}
    allowed.update(value.rstrip("/") for value in get_settings().cors_origins if value != "*")
    if origin and origin.rstrip("/") not in allowed:
        raise ForbiddenError("This employer portal origin is not allowed")
