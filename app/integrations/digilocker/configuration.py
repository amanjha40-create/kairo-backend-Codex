"""Fail-closed integration configuration, without provider endpoint defaults."""

import ipaddress
import re
from urllib.parse import urlsplit


class DigiLockerConfigurationError(RuntimeError):
    def __init__(self):
        super().__init__("DigiLocker enabled configuration is incomplete or unsafe")


def _url(value):
    if not isinstance(value, str) or len(value) > 2048 or any(c.isspace() for c in value):
        raise ValueError()
    url = urlsplit(value)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
        or "\\" in value
        or url.hostname == "localhost"
        or url.hostname.endswith(".localhost")
        or url.port not in {None, 443}
    ):
        raise ValueError()
    try:
        ipaddress.ip_address(url.hostname)
    except ValueError:
        pass
    else:
        raise ValueError()
    return url


def validate_configuration(settings):
    try:
        # Native access logs include query credentials; SQL DEBUG can dump envelope values.
        if not settings.log_access_enabled or settings.log_level == "DEBUG":
            raise ValueError()
        if settings.database_echo_sql or (
            settings.app_env.value == "development" and settings.database_echo_sql is not False
        ):
            raise ValueError()
        if not settings.digilocker_client_id or not settings.digilocker_client_id.strip():
            raise ValueError()
        if not settings.digilocker_client_secret:
            raise ValueError()
        if not settings.digilocker_client_secret.get_secret_value().strip():
            raise ValueError()
        for value in (
            settings.digilocker_authorize_url,
            settings.digilocker_token_url,
            settings.digilocker_revoke_url,
        ):
            _url(value)
        callback = _url(settings.digilocker_redirect_uri)
        if callback.path != settings.api_v1_prefix + "/integrations/digilocker/callback":
            raise ValueError()
        if settings.app_env.value == "staging" and callback.hostname == "api.kairoid.com":
            raise ValueError()
        if settings.app_env.value == "production" and callback.hostname.startswith("staging"):
            raise ValueError()
        if settings.digilocker_connection_return_url:
            target = _url(settings.digilocker_connection_return_url)
            portal = _url(settings.candidate_portal_base_url)
            if (target.scheme, target.netloc) != (portal.scheme, portal.netloc):
                raise ValueError()
        if settings.digilocker_purpose not in {
            None,
            "kyc",
            "verification",
            "compliance",
            "availing_services",
            "educational",
        }:
            raise ValueError()
        if settings.digilocker_req_doctypes is not None and not re.fullmatch(
            r"[A-Z]{2,16}(,[A-Z]{2,16}){0,19}", settings.digilocker_req_doctypes
        ):
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise DigiLockerConfigurationError() from None
