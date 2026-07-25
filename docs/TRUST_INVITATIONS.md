# Trust Invitations

This document describes the backend-owned Trust Invitation contract used by the Candidate App and the standalone HR Workspace.

## Goals

- Keep the existing Trust Invitation workflow intact.
- Preserve backward compatibility for existing invitations and public links.
- Move invitation lifecycle, delivery state, and summary calculations into the backend.

## Entity Model

`trust_invitations` persists the invitation record.

Core identity fields:

- `public_id`
- `organization_id`
- `created_by_user_id`
- `accepted_by_user_id`

Subject fields:

- `subject_name`
- `subject_email`
- `subject_phone` nullable

HR Workspace fields:

- `purpose` nullable
- `requested_verification_types` JSON array
- `message` nullable
- `delivery_method`
- `delivery_state`

Lifecycle fields:

- `status`
- `expires_at`
- `sent_at`
- `opened_at`
- `accepted_at`
- `cancelled_at`

Compatibility field:

- `token_hash`

`trust_invitation_events` persists lifecycle history for detail views and auditing.

Stored event fields:

- `invitation_id`
- `event_type`
- `actor_user_id` nullable
- `metadata_payload`
- `occurred_at`

## Field Definitions

`status` values:

- `draft`
- `pending`
- `accepted`
- `cancelled`
- `expired`

`delivery_method` values:

- `email`

`delivery_state` values:

- `queued`
- `delivered`
- `opened`
- `failed`

`requested_verification_types` values:

- `identity`
- `employment`
- `education`
- `certification`
- `professional_reference`

## Lifecycle

Supported Version 1 actions:

- `create` with `mode="send"` or `mode="draft"`
- `detail`
- `list`
- `summary`
- `send` for drafts
- `resend` for active sent invitations
- `accept`
- `cancel`
- `delete` for drafts only

Persisted event types:

- `created`
- `sent`
- `resent`
- `opened`
- `accepted`
- `cancelled`
- `expired`
- `delivery_failed`
- `deleted`

Lifecycle notes:

- Sent invitations remain `pending`; delivery progress is represented by `delivery_state`.
- `opened` is tracked as an event and delivery state, not as a separate invitation status.
- Expiration is normalized by the backend when invitations are read.
- Draft deletion is restricted to unsent invitations to avoid breaking historical records for active or completed flows.

Unsupported actions:

- non-draft delete
- non-email delivery methods
- separate frontend-owned permission inference

## Endpoints

Organization-scoped:

- `POST /api/v1/organizations/{org_public_id}/trust-invitations`
- `GET /api/v1/organizations/{org_public_id}/trust-invitations`
- `GET /api/v1/organizations/{org_public_id}/trust-invitations/summary`

Authenticated:

- `GET /api/v1/trust-invitations/by-id/{trust_invitation_public_id}`
- `POST /api/v1/trust-invitations/{trust_invitation_public_id}/send`
- `POST /api/v1/trust-invitations/{trust_invitation_public_id}/resend`
- `POST /api/v1/trust-invitations/{trust_invitation_public_id}/cancel`
- `DELETE /api/v1/trust-invitations/{trust_invitation_public_id}`

Public / candidate-facing:

- `GET /api/v1/trust-invitations/{token}`
- `POST /api/v1/trust-invitations/{token}/accept`

## Permissions

- All authenticated Trust Invitation routes require organization membership.
- Cancellation is restricted to organization managers using the existing owner/admin permission model.
- Public acceptance still requires the authenticated user email to match the invitation subject email.
- The frontend should consume backend-derived authorization outcomes and should not infer permissions from role names alone.

## Backward Compatibility

- Existing persisted invitations remain valid after migration.
- Existing public invitation links remain valid through legacy token-hash lookup.
- New invitation URLs use a backend-signed token derived from `public_id`.
- Candidate App routes remain intact.
- The existing create/list/public lookup/accept/cancel contract remains supported, with additive fields and endpoints.

## Migration Notes

Migration revision:

- `051_trust_invitation_contract_completion.py`

Migration changes:

- extends `trust_invitation_status_enum`
- adds delivery method and delivery state enums
- adds HR Workspace fields to `trust_invitations`
- creates `trust_invitation_events`
- backfills sent/opened delivery state for existing invitations
- backfills timeline events for existing invitations

Downgrade note:

- The migration removes new columns and tables, but Postgres enum values added to an existing enum are not removed during downgrade.
