"""Explicit operator-only State-B certification. No OAuth, retries or flag writes."""

import argparse
import asyncio
import json
import logging
from uuid import UUID

from app.exceptions import ForbiddenError, NotFoundError, ValidationAppError


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default error can echo an accidentally supplied private value.
        self.exit(2, "ARGUMENTS_INVALID: use --help; never supply credentials or tokens.\n")


def parser():
    result = SafeParser(description=__doc__, allow_abbrev=False)
    result.add_argument("--execute", action="store_true", required=True)
    result.add_argument("--candidate-id", type=UUID, required=True)
    result.add_argument("--connection-id", type=UUID, required=True)
    result.add_argument(
        "--approval-id",
        type=UUID,
        required=True,
        help="Opaque operator approval record binding account, consent and one invocation",
    )
    result.add_argument(
        "--consent-confirmed",
        action="store_true",
        required=True,
        help="Attest the selected Candidate explicitly consented to this e-Aadhaar check",
    )
    result.add_argument("--consent-version", choices=["v1"], required=True)
    return result


def require_state_b(settings, args):
    if (
        settings.app_env.value != "production"
        or not settings.digilocker_enabled
        or settings.digilocker_eaadhaar_enabled
        or settings.digilocker_eaadhaar_entitlement_certified
        or not args.execute
        or not args.consent_confirmed
        or args.consent_version != "v1"
        or not all(
            isinstance(v, UUID) for v in (args.candidate_id, args.connection_id, args.approval_id)
        )
    ):
        raise ValueError("certification_precondition_failed")


def safe_outcome(error):
    code = getattr(error, "code", "")
    if code == "digilocker_insufficient_scope":
        return "ENTITLEMENT_DENIED"
    if code == "digilocker_aadhaar_not_linked":
        return "ACCOUNT_NOT_LINKED"
    if code in {
        "digilocker_invalid_token",
        "digilocker_access_unavailable",
        "digilocker_reconnect_required",
    }:
        return "CONTROLLED_SESSION_RECONNECT_REQUIRED"
    if code == "digilocker_account_unavailable":
        return "ACCOUNT_UNAVAILABLE"
    if code == "digilocker_integrity_failed":
        return "SECURITY_FAILURE"
    if code in {"digilocker_provider_unavailable", "digilocker_transport_error"}:
        return "PROVIDER_TEMPORARY_FAILURE"
    if code in {"digilocker_invalid_response", "digilocker_response_too_large"}:
        return "PROVIDER_RESPONSE_INVALID"
    if isinstance(error, (ForbiddenError, NotFoundError, ValidationAppError)):
        return "CONTROLLED_ACCOUNT_REFUSED"
    return "CERTIFICATION_FAILED"


async def certify(service, args):
    """Not routed through HTTP; operator DB access is the authorization boundary."""
    require_state_b(service.settings, args)
    try:
        async with asyncio.timeout(50):
            await service._verify_with_consent(
                args.candidate_id,
                consent=args.consent_confirmed,
                consent_version=args.consent_version,
                expected_connection_id=args.connection_id,
            )
        # Entitlement success is not an assertion that the identity matched.
        return {
            "outcome": "ENTITLEMENT_CONFIRMED",
            "derived_provenance_persisted": True,
            "feature_flags_changed": False,
        }
    except Exception as error:
        await service.session.rollback()
        outcome = safe_outcome(error)
        return {
            "outcome": outcome,
            "derived_provenance_persisted": None if outcome == "CERTIFICATION_FAILED" else False,
            "feature_flags_changed": False,
        }


async def run(args):
    from app.config import get_settings
    from app.db.session import async_session_factory, engine
    from app.services.digilocker_eaadhaar_service import DigiLockerEAadhaarService

    try:
        settings = get_settings()
        require_state_b(settings, args)
        if engine.echo:
            raise ValueError("sql_echo_must_be_disabled")
        async with async_session_factory() as session:
            # No Redis operation is needed: only the canonical stored connection is read.
            return await certify(DigiLockerEAadhaarService(session, settings, None), args)
    finally:
        await engine.dispose()


def main(argv=None):
    args = parser().parse_args(argv)
    logging.disable(logging.CRITICAL)
    try:
        result = asyncio.run(run(args))
    except (Exception, KeyboardInterrupt):
        result = {
            "outcome": "CERTIFICATION_REFUSED_OR_INTERRUPTED",
            "derived_provenance_persisted": None,
            "feature_flags_changed": False,
        }
    print(json.dumps(result), flush=True)
    return 0 if result["outcome"] == "ENTITLEMENT_CONFIRMED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
