"""Backend readiness verification script.

Exercises a core Kairo platform readiness path against a running backend:
1. create test users directly in the database
2. log in through HTTP
3. update/read owner profile
4. create a Trust Passport share link
5. open the public Trust Passport
6. verify view tracking analytics
7. verify analytics fail closed for a non-owner
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from app.auth.email_utils import normalize_email
from app.auth.passwords import hash_password
from app.db.session import async_session_factory
from app.models import User
from app.repositories.user import UserRepository

BASE_URL = "http://127.0.0.1:8000/api/v1"


@dataclass
class CheckResult:
    name: str
    passed: bool
    details: str


def _extract_share_token(share_url: str) -> str:
    parsed = urlparse(share_url)
    token = parsed.path.rstrip("/").split("/")[-1]
    if not token:
        raise ValueError(f"Unable to extract share token from URL: {share_url}")
    return token


async def _ensure_user(
    *,
    email: str,
    password: str,
    full_name: str,
    headline: str,
    location: str,
) -> None:
    async with async_session_factory() as session:
        repo = UserRepository(session)
        user = await repo.get_by_email(email)
        if user is None:
            user = User(
                email=email,
                password_hash=hash_password(password),
                full_name=full_name,
                profile_slug=f"backend-readiness-{uuid.uuid4().hex[:8]}",
                headline=headline,
                location=location,
                role="user",
                is_active=True,
            )
            session.add(user)
        else:
            user.password_hash = hash_password(password)
            user.full_name = full_name
            user.headline = headline
            user.location = location
            user.is_active = True
            user.deleted_at = None

        if user.email_verified_at is None:
            from datetime import UTC, datetime

            user.email_verified_at = datetime.now(tz=UTC)
        await session.commit()


async def _login(client: httpx.AsyncClient, email: str, password: str) -> tuple[str, dict[str, Any]]:
    response = await client.post(
        f"{BASE_URL}/auth/login",
        json={"email": email, "password": password},
    )
    response.raise_for_status()
    body = response.json()
    return body["access_token"], body


async def _auth_json(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    access_token: str,
    *,
    json: dict[str, Any] | None = None,
) -> httpx.Response:
    return await client.request(
        method,
        f"{BASE_URL}{path}",
        headers={"Authorization": f"Bearer {access_token}"},
        json=json,
    )


async def main() -> int:
    run_id = int(time.time())
    owner_email = normalize_email(f"backend-owner-{run_id}@example.com")
    non_owner_email = normalize_email(f"backend-viewer-{run_id}@example.com")
    owner_password = "BackendOwnerPass123!"
    non_owner_password = "BackendViewerPass123!"

    await _ensure_user(
        email=owner_email,
        password=owner_password,
        full_name="Backend Owner",
        headline="Backend Engineer",
        location="Bengaluru",
    )
    await _ensure_user(
        email=non_owner_email,
        password=non_owner_password,
        full_name="Backend Viewer",
        headline="Recruiter",
        location="Mumbai",
    )

    results: list[CheckResult] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        owner_access, _ = await _login(client, owner_email, owner_password)
        results.append(CheckResult("owner_login", True, "Owner login returned access token"))

        non_owner_access, _ = await _login(client, non_owner_email, non_owner_password)
        results.append(CheckResult("non_owner_login", True, "Non-owner login returned access token"))

        update_response = await _auth_json(
            client,
            "PATCH",
            "/users/me",
            owner_access,
            json={
                "full_name": "Backend Owner",
                "headline": "Portable Trust Profile",
                "location": "Bengaluru",
                "bio": "Backend readiness verification user",
            },
        )
        update_ok = update_response.status_code == 200
        results.append(CheckResult("profile_update", update_ok, f"status={update_response.status_code}"))

        me_response = await _auth_json(client, "GET", "/users/me", owner_access)
        me_body = me_response.json() if me_response.status_code == 200 else {}
        me_ok = me_response.status_code == 200 and me_body.get("full_name") == "Backend Owner"
        results.append(CheckResult("profile_read", me_ok, f"status={me_response.status_code}"))

        share_response = await _auth_json(
            client,
            "POST",
            "/passport-shares",
            owner_access,
            json={
                "label": "Backend Readiness Check",
                "track_views": True,
                "permissions": {
                    "include_employments": True,
                    "include_educations": True,
                    "include_internships": True,
                    "include_freelance": True,
                    "include_gig_platforms": True,
                    "include_portfolio": True,
                    "include_certifications": True,
                    "include_user_documents": False,
                    "show_employer_names": True,
                    "show_documents": False,
                    "show_trust_score": True,
                },
            },
        )
        share_body = share_response.json() if share_response.status_code == 201 else {}
        share_ok = share_response.status_code == 201 and "share_url" in share_body
        results.append(CheckResult("passport_share_create", share_ok, f"status={share_response.status_code}"))

        share_id = share_body.get("id")
        share_url = share_body.get("share_url")
        share_token = _extract_share_token(share_url) if share_ok else ""

        public_response = await client.get(f"{BASE_URL}/public/passport/{share_token}")
        public_body = public_response.json() if public_response.status_code == 200 else {}
        public_ok = (
            public_response.status_code == 200
            and "profile" in public_body
            and "vault" in public_body
            and "share" in public_body
        )
        results.append(CheckResult("public_passport", public_ok, f"status={public_response.status_code}"))

        analytics_response = await _auth_json(
            client,
            "GET",
            f"/passport-shares/{share_id}/analytics",
            owner_access,
        )
        analytics_body = analytics_response.json() if analytics_response.status_code == 200 else {}
        analytics_ok = (
            analytics_response.status_code == 200
            and analytics_body.get("share_id") == share_id
            and analytics_body.get("total_views", 0) >= 1
            and analytics_body.get("unique_views", 0) >= 1
            and isinstance(analytics_body.get("recent_views"), list)
            and len(analytics_body.get("recent_views", [])) >= 1
        )
        results.append(CheckResult("share_analytics_owner", analytics_ok, f"status={analytics_response.status_code}"))

        non_owner_analytics = await _auth_json(
            client,
            "GET",
            f"/passport-shares/{share_id}/analytics",
            non_owner_access,
        )
        non_owner_body = non_owner_analytics.json()
        non_owner_ok = (
            non_owner_analytics.status_code == 404
            and non_owner_body.get("error", {}).get("code") == "not_found"
        )
        results.append(
            CheckResult(
                "share_analytics_non_owner_blocked",
                non_owner_ok,
                f"status={non_owner_analytics.status_code}",
            )
        )

    passed = sum(1 for item in results if item.passed)
    total = len(results)

    print("Kairo Backend Readiness Verification")
    print(f"Base URL: {BASE_URL}")
    for item in results:
        status_text = "PASS" if item.passed else "FAIL"
        print(f"[{status_text}] {item.name}: {item.details}")
    print(f"Summary: {passed}/{total} checks passed")

    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
