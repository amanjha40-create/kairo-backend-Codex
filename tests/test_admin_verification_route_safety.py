"""Production Admin verification routes must preserve the canonical two-gate workflow."""

from app.main import app


def test_legacy_direct_employment_verification_routes_are_not_registered() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/admin/verify" not in paths
    assert "/api/v1/admin/reject" not in paths
    assert "/api/v1/admin/review-queue" not in paths
    assert "/api/v1/admin/verifications/queue" not in paths
    assert "/api/v1/admin/verifications/{employment_id}/approve" not in paths
    assert "/api/v1/admin/verifications/{employment_id}/reject" not in paths
    assert "/api/v1/admin/verifications/{employment_id}/transition" not in paths


def test_canonical_admin_verification_review_routes_remain_registered() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/admin/verification-requests/queue" in paths
    assert "/api/v1/admin/verification-requests/{verification_request_public_id}/approve" in paths
    assert "/api/v1/admin/verification-requests/{verification_request_public_id}/finalize" in paths
