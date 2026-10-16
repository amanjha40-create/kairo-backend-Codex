"""Startup-safe readiness checks; never import services, probe AWS or print keys."""

import re

from app.integrations.digilocker.crypto import parse_keyring


class PermanentAddressConfigurationError(RuntimeError):
    def __init__(self):
        super().__init__("Permanent Address configuration is incomplete or invalid")


def validate_configuration(settings):
    if not settings.permanent_address_enabled:
        return
    try:
        environment = str(settings.app_env)
        if environment not in {"test", "staging", "production"}:
            raise ValueError()
        parse_keyring(
            settings.permanent_address_keys,
            settings.permanent_address_key_id,
            environment,
        )
        if settings.permanent_address_places_region != "us-east-1":
            raise ValueError()
        if environment != "test":
            bucket = settings.s3_documents_bucket or ""
            prefix = settings.s3_document_key_prefix
            if (
                settings.aws_region != "us-east-1"
                or settings.aws_endpoint_url
                or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket)
                or not prefix
                or prefix.startswith("/")
                or any(part in {"", ".", ".."} for part in prefix.rstrip("/").split("/"))
                or any(char in prefix for char in "*?\\")
            ):
                raise ValueError()
            if environment == "production" and re.search(
                r"(^|[-.])(stage|staging|test|dev)([-.]|$)", bucket
            ):
                raise ValueError()
    except Exception:
        # RuntimeError avoids Pydantic embedding the input keyring in errors.
        raise PermanentAddressConfigurationError() from None
