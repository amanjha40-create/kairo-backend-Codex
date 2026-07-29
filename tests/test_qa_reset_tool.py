from __future__ import annotations

import pytest

from app.config.settings import AppEnvironment
from scripts.reset_test_data import (
    ResetMode,
    ResetSafetyError,
    _owned_delete_order,
    build_parser,
    confirm_full_reset,
    normalize_emails,
    parse_mode,
    validate_environment,
)


def test_production_is_always_refused() -> None:
    with pytest.raises(ResetSafetyError, match="forbidden"):
        validate_environment(app_env=AppEnvironment.PRODUCTION, full_reset=False)


def test_full_reset_is_staging_only() -> None:
    with pytest.raises(ResetSafetyError, match="staging"):
        validate_environment(app_env=AppEnvironment.DEVELOPMENT, full_reset=True)


def test_full_reset_requires_explicit_confirmation() -> None:
    with pytest.raises(ResetSafetyError, match="FULL STAGING RESET"):
        confirm_full_reset(confirmed=False)
    confirm_full_reset(confirmed=True)


def test_email_list_is_normalized_and_deduplicated(tmp_path) -> None:
    path = tmp_path / "emails.txt"
    path.write_text(" QA@Example.com\nqa@example.com\n", encoding="utf-8")
    mode = parse_mode(email=None, emails_file=str(path), full_reset=False)
    assert mode.emails == ("qa@example.com",)


def test_modes_are_mutually_exclusive() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        parse_mode(email="qa@example.com", emails_file=None, full_reset=True)


def test_empty_email_input_is_rejected() -> None:
    with pytest.raises(ValueError, match="email"):
        normalize_emails([" "])


def test_dry_run_flag_is_available_without_changing_reset_mode() -> None:
    args = build_parser().parse_args(["--full-reset", "--dry-run"])
    mode = ResetMode(full_reset=args.full_reset, dry_run=args.dry_run)
    assert mode.full_reset is True
    assert mode.dry_run is True


def test_owned_delete_order_deletes_verification_requests_before_employments() -> None:
    import app.models  # noqa: F401
    from app.db.base import Base

    order = _owned_delete_order(Base.metadata, {"employments": [], "verification_requests": []})
    assert order.index("verification_requests") < order.index("employments")
