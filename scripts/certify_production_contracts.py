"""Offline OpenAPI non-regression check against a pinned local baseline checkout."""

import argparse
import json
import subprocess
import sys

from app.main import app

BASE = "1daff01dd030775c5d70d12caae0e9b8b0ce056a"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    args = parser.parse_args()
    assert (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=args.baseline, text=True).strip()
        == BASE
    )
    assert not subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], cwd=args.baseline, text=True
    ).strip()
    old = json.loads(
        subprocess.check_output(
            [
                sys.executable,
                "-c",
                "import json; from app.main import app; print(json.dumps(app.openapi()))",
            ],
            cwd=args.baseline,
            text=True,
        )
    )
    new = app.openapi()
    for path, contract in old["paths"].items():
        assert new["paths"][path] == contract, path
    old_schemas = old["components"]["schemas"]
    new_schemas = new["components"]["schemas"]
    for name, schema in old_schemas.items():
        if name != "AdminReviewTimelineResponse":
            assert new_schemas[name] == schema, name
    # Only the Admin envelope changes its reference; added actor fields are optional.
    for original, replacement in [
        ("VerificationRequestTimelineResponse", "AdminVerificationTimelineResponse"),
        ("VerificationRequestTimelineEventResponse", "AdminVerificationTimelineEventResponse"),
    ]:
        a, b = old_schemas[original], new_schemas[replacement]
        assert a.get("required", []) == b.get("required", [])
        for key, value in a["properties"].items():
            if key == "items":
                assert b["properties"][key]["items"]["$ref"].endswith(
                    "/AdminVerificationTimelineEventResponse"
                )
            else:
                assert b["properties"][key] == value, (replacement, key)
    route = (
        "/api/v1/admin/verification-requests/{verification_request_public_id}/direct-confirmation"
    )
    assert set(new["paths"]) - set(old["paths"]) == {route}
    assert "post" in new["paths"][route]
    assert "/api/v1/integrations/digilocker/callback" in new["paths"]
    print(
        json.dumps(
            {
                "baseline": BASE,
                "unchanged_existing_paths": len(old["paths"]),
                "unchanged_existing_schemas": len(old_schemas) - 1,
                "admin_timeline": "additive_optional_actor_fields_only",
                "restored_route": route,
                "result": "PASS",
            }
        )
    )


if __name__ == "__main__":
    main()
