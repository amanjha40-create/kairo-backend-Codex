# Organization Person Registry

## Purpose

The Organization Person Registry is the canonical organization-scoped representation of every person known by an organization in Kairo HR Workspace.

Each organization gets its own people namespace. The same real-world person may appear in multiple organizations, but each organization resolves that person independently.

## Architecture

The registry centers on `organization_people`.

Source records attach to one canonical person through nullable `organization_person_id` columns on:

- `trust_invitations`
- `verification_requests`
- `employments` where the organization association is unambiguous

Supporting tables:

- `organization_person_identifiers`
- `organization_person_notes`
- `organization_person_passport_access`

## Resolution Rules

Resolution is deterministic and organization-scoped.

Priority order:

1. Existing `organization_person_id`
2. Linked authenticated user
3. Normalized email
4. Normalized phone
5. Create a new organization person

Rules:

- Never merge across organizations.
- Relationship updates reuse the existing organization person.
- Email and phone aliases are stored in `organization_person_identifiers` for durable future resolution.

## Entity Model

`organization_people` stores:

- stable public identifier
- organization ownership
- optional linked user
- primary name, email, phone
- relationship summary
- invitation summary
- verification summary
- passport summary
- trust state
- added-by and activity timestamps
- resolution metadata

The record is intentionally backend-owned. Frontends consume authoritative summaries instead of reconstructing them client-side.

## Relationship Model

Supported relationship values:

- `candidate`
- `employee`
- `former_employee`
- `contractor`
- `future_employee`

Relationship promotion is monotonic. Stronger employment-backed relationships do not get downgraded by weaker invitation-only states.

## Trust State

Trust state is derived from backend-owned source status:

- `unknown`
- `pending`
- `verified`
- `partially_verified`
- `revoked`

Current derivation:

- completed verification drives `verified`
- active or historical shared passport access, or accepted invitation, drives `partially_verified`
- in-flight invitations or verification workflows drive `pending`
- revoked passport access drives `revoked`

## Endpoints

Authenticated organization-scoped endpoints:

- `GET /api/v1/organizations/{org_public_id}/people`
- `GET /api/v1/organizations/{org_public_id}/people/{person_public_id}`
- `POST /api/v1/organizations/{org_public_id}/people/{person_public_id}/notes`
- `PATCH /api/v1/organizations/{org_public_id}/people/{person_public_id}/notes/{note_public_id}`
- `DELETE /api/v1/organizations/{org_public_id}/people/{person_public_id}/notes/{note_public_id}`

The list endpoint returns:

- paginated items
- search, sorting, and filter support
- directory summary counts

The detail endpoint returns backend-composed sections for:

- summary
- passport preview
- verification summary
- linked employment verifications
- shared evidence
- activity
- internal notes
- organization relationship metadata

## Authorization

All registry endpoints are organization-scoped.

Rules:

- caller must belong to the target organization
- suspended memberships fail closed
- suspended organizations fail closed
- internal notes remain organization-private
- only the note author may edit or delete that note
- passport preview respects stored sharing permissions

## Backfill Strategy

Migration `053` backfills canonical people from:

- trust invitations
- verification requests
- employments linked through organization-scoped verification requests

Backfill preserves deterministic resolution and avoids duplicate people within the same organization.

Employment `organization_person_id` is populated only where organization ownership is applicable from existing verification links.

`organization_person_passport_access` is introduced as the canonical organization-scoped passport-access table. Existing backend data did not previously carry an organization-owned passport-share relation, so historical rows are not fabricated during backfill.

## Future University Reuse

The registry model is organization-scoped rather than HR-specific. Future University Workspace and other organization products can reuse the same pattern:

- canonical person per organization
- durable email and phone alias resolution
- organization-private notes
- backend-composed activity
- source-record attachment by `organization_person_id`
