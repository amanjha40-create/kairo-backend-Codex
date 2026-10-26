"""Promote one exact existing Admin to the first Production Superadmin."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from uuid import UUID

from app.config.settings import AppEnvironment, Settings
from app.core.constants import Role


class BootstrapCommandRefused(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "ARGUMENTS_INVALID: use --help; never supply credentials or tokens.\n")


def parser() -> argparse.ArgumentParser:
    result = SafeParser(description=__doc__, allow_abbrev=False)
    result.add_argument("--target-user-id", type=UUID, required=True)
    result.add_argument("--target-email", required=True)
    result.add_argument(
        "--expected-current-role",
        choices=[Role.ADMIN.value],
        required=True,
    )
    result.add_argument(
        "--environment",
        choices=[AppEnvironment.PRODUCTION.value],
        required=True,
    )
    result.add_argument("--confirm-first-superadmin-bootstrap", action="store_true", required=True)
    return result


def validate_execution_contract(settings: Settings, args: argparse.Namespace) -> str:
    if settings.app_env != AppEnvironment.PRODUCTION:
        raise BootstrapCommandRefused("runtime_environment_not_production")
    if args.environment != settings.app_env.value:
        raise BootstrapCommandRefused("environment_mismatch")
    if args.target_email != args.target_email.strip().lower():
        raise BootstrapCommandRefused("target_email_not_canonical")
    if args.expected_current_role != Role.ADMIN.value:
        raise BootstrapCommandRefused("expected_role_must_be_admin")
    if not args.confirm_first_superadmin_bootstrap:
        raise BootstrapCommandRefused("explicit_confirmation_required")
    source_sha = settings.app_git_sha or ""
    if re.fullmatch(r"[0-9a-f]{40}", source_sha) is None:
        raise BootstrapCommandRefused("source_sha_unavailable")
    return source_sha


async def run(args: argparse.Namespace) -> dict[str, object]:
    from app.config import get_settings

    settings = get_settings()
    source_sha = validate_execution_contract(settings, args)

    from app.db.session import async_session_factory, engine
    from app.services.first_superadmin_bootstrap import (
        FirstSuperadminBootstrapRefused,
        FirstSuperadminBootstrapService,
    )

    try:
        if engine.echo:
            raise BootstrapCommandRefused("sql_echo_must_be_disabled")

        async with async_session_factory() as session:
            try:
                async with session.begin():
                    result = await FirstSuperadminBootstrapService(session).promote(
                        target_user_id=args.target_user_id,
                        target_email=args.target_email,
                        expected_current_role=args.expected_current_role,
                        environment=args.environment,
                        source_sha=source_sha,
                    )
            except FirstSuperadminBootstrapRefused as error:
                raise BootstrapCommandRefused(error.code) from error
        return {
            "event": "first_superadmin_bootstrap_completed",
            "target_user_id": str(result.target_user_id),
            "administrator_id": str(result.administrator_id),
            "prior_role": result.prior_role,
            "new_role": result.new_role,
            "sessions_revoked": result.sessions_revoked,
            "audit_event_id": str(result.audit_event_id),
            "source_sha": source_sha,
        }
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        with asyncio.Runner() as runner:
            result = runner.run(run(args))
    except BootstrapCommandRefused as error:
        result = {
            "event": "first_superadmin_bootstrap_refused",
            "reason": error.code,
        }
        code = 2
    except (Exception, KeyboardInterrupt):
        result = {
            "event": "first_superadmin_bootstrap_failed",
            "reason": "unexpected_failure",
        }
        code = 2
    else:
        code = 0
    print(json.dumps(result, sort_keys=True), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
