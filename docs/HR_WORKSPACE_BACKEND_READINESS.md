# HR Workspace Backend Readiness

This document captures the backend additions made to support the standalone HR Workspace using authoritative backend state instead of frontend-only mock state.

## Authentication Decision

- No auth bridge was added.
- No JWT exchange endpoint was added.
- No Supabase compatibility layer was added.
- The backend continues to authenticate through `/api/v1/auth/*`.
- The existing auth model remains:
  - short-lived backend JWT access tokens
  - opaque refresh tokens with rotation
  - server-side user lookup on authenticated routes

### Audit conclusion

The current auth contract is workspace-agnostic because tokens identify the authenticated user, not a single product surface. That makes it reusable for:

- Candidate App
- HR Workspace
- future University Workspace
- future Admin Portal

No backend auth redesign was required for HR Workspace readiness.

## Bootstrap Endpoint

New endpoint:

- `GET /api/v1/workspace/bootstrap`

Purpose:

- answer "what workspace should this authenticated user see?"

The response is an authoritative aggregation of backend state and includes:

- current user summary
- active organization
- membership role
- organization verification state
- organization suspension state
- membership suspension state
- setup completion
- pending organization invitation, if any
- backend-derived permission flags

### Access state derivation

`state` is derived server-side from organization, membership, and invitation state:

- `no_org`
- `invitation_pending`
- `setup_incomplete`
- `verification_pending`
- `org_suspended`
- `membership_suspended`
- `ready`

This keeps the frontend from reconstructing workspace state from low-level fields.

## Organization Schema

The existing HR onboarding fields belong on `Organization` because they describe the organization profile and verification posture, not a single user account.

Added organization fields:

- `website`
- `industry`
- `location`
- `work_email`
- `domain`
- `domain_verified_at`
- `verification_state`
- `setup_completed_at`
- `suspended_at`
- `suspension_reason`

Added user field:

- `users.active_organization_id`

Added membership fields:

- `organization_members.suspended_at`
- `organization_members.suspension_reason`

### Setup persistence

The backend now supports onboarding/profile persistence through:

- `POST /api/v1/organizations`
- `PATCH /api/v1/organizations/{org_public_id}`

Setup completion is inferred when the required organization onboarding fields have been persisted. Existing verified organizations are not downgraded automatically.

## Invitation Bootstrap

New persistence model:

- `organization_invitations`

New endpoints:

- `GET /api/v1/workspace/invitations`
- `POST /api/v1/workspace/invitations/{invitation_public_id}/accept`
- `POST /api/v1/workspace/invitations/{invitation_public_id}/decline`

Invitation bootstrap now supports backend-owned discovery of:

- pending organization invitations
- invited role
- inviting organization
- invitation status

Expired pending invitations are normalized to `expired` by the backend when read.

## Permission Model

The frontend should not infer permissions from role names.

The bootstrap response now exposes backend-derived permission flags. These are derived from:

- organization membership
- organization role
- organization suspension state
- membership suspension state

Current flags:

- `invite_candidate`
- `modify_person`
- `modify_invitation`
- `modify_verification`
- `manage_team`
- `save_settings`
- `transfer_ownership`

Manager-only actions are derived from existing `owner` / `admin` organization roles. Ownership-only actions remain restricted to `owner`.

## Backward Compatibility

The readiness changes are additive:

- existing auth routes are unchanged
- existing organization routes remain valid
- new organization fields are nullable
- organization onboarding/profile persistence is supported without changing prior request shapes
- bootstrap and invitation routes are new endpoints

### Legacy organization backfill

The migration backfills existing organizations that already have memberships so they continue to behave as active organizations:

- `verification_state` backfilled to `verified`
- `setup_completed_at` backfilled from `created_at`
- `users.active_organization_id` backfilled from the user's earliest membership

This avoids locking existing organization users behind the new setup gate.

## Migration Notes

Migration added:

- organization verification enum
- organization invitation status enum
- `background_verification_partner` organization type
- organization profile and readiness columns
- user active organization pointer
- membership suspension fields
- organization invitations table

Migration revision:

- `050_hr_workspace_backend_readiness.py`

## Validation Notes

Validated locally in Docker:

- targeted route-contract tests
- full backend pytest suite
- Alembic current/head alignment
- OpenAPI document generation
- rebuilt Docker image

Deployment automation in this repository is production-oriented (`deploy_ec2.sh`, `.github/workflows/cd.yml`). A dedicated staging deployment path is not defined in-repo, so staging rollout must use the external staging environment and credentials that are not present in this workspace.
