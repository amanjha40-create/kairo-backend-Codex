#!/usr/bin/env python3
"""Backfill canonical Trust Registry links for workspace organizations."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if __name__ == "__main__" and os.getenv("APP_ENV", "").strip().lower() == "production":
    print("organization-registry backfill refused when APP_ENV=production", file=sys.stderr)
    raise SystemExit(2)

from app.config import get_settings
from app.config.settings import AppEnvironment
from app.db.session import async_session_factory, dispose_engine
from app.models.organization import Organization
from app.services.organization_registry_sync_service import (
    OrganizationRegistrySyncService,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill canonical Trust Registry links for workspace organizations.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist the planned organization->Registry links.",
    )
    parser.add_argument(
        "--organization-public-id",
        action="append",
        default=[],
        help="Limit the run to one or more specific organization public IDs.",
    )
    return parser


def validate_environment() -> None:
    app_env = get_settings().app_env
    if app_env == AppEnvironment.PRODUCTION:
        raise RuntimeError("organization-registry backfill is forbidden in production")
    if app_env not in {
        AppEnvironment.DEVELOPMENT,
        AppEnvironment.TEST,
        AppEnvironment.STAGING,
    }:
        raise RuntimeError(f"organization-registry backfill is unsupported for APP_ENV={app_env}")


async def run(*, apply: bool, public_ids: list[UUID]) -> list[dict[str, object]]:
    async with async_session_factory() as session:
        stmt = select(Organization).order_by(Organization.created_at.asc())
        if public_ids:
            stmt = stmt.where(Organization.public_id.in_(public_ids))
        else:
            stmt = stmt.where(Organization.registry_record_id.is_(None))
        organizations = list((await session.execute(stmt)).scalars().all())
        sync = OrganizationRegistrySyncService(session)

        results: list[dict[str, object]] = []
        for organization in organizations:
            plan = await sync.plan_sync_organization(organization)
            payload: dict[str, object] = {
                "organization_public_id": str(organization.public_id),
                "organization_name": organization.name,
                "organization_type": (
                    organization.organization_type.value
                    if hasattr(organization.organization_type, "value")
                    else str(organization.organization_type)
                ),
                "workspace_domain": organization.domain,
                "action": plan.action,
                "resolution_method": plan.resolution_method,
                "registry_record_public_id": (
                    str(plan.registry_record_public_id)
                    if plan.registry_record_public_id is not None
                    else None
                ),
                "request_links_pending": plan.request_links_pending,
            }
            if apply:
                result = await sync.sync_organization(
                    organization,
                    actor_user_id=None,
                    commit=True,
                )
                payload["applied"] = True
                payload["action"] = result.action
                payload["registry_record_public_id"] = str(result.registry_record_public_id)
                payload["request_links_synced"] = result.request_links_synced
            else:
                payload["applied"] = False
            results.append(payload)
        return results


def parse_public_ids(values: list[str]) -> list[UUID]:
    parsed: list[UUID] = []
    for value in values:
        parsed.append(UUID(value))
    return parsed


async def main() -> int:
    validate_environment()
    args = build_parser().parse_args()
    results = await run(
        apply=args.apply,
        public_ids=parse_public_ids(args.organization_public_id),
    )
    print(json.dumps(results, indent=2))
    await dispose_engine()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
