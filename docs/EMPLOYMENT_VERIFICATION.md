# Employment Verification Contract

This document describes the backend contract that supports the HR Workspace employment verification experience.

## Scope

The HR Workspace consumes the canonical verification request workflow under `/api/v1/verification-requests/*`.

This contract does not replace:

- candidate-owned employment submission flows
- platform-admin review workflows under `/api/v1/admin/verification-requests/*`
- public employer magic-link flows under `/api/v1/public/employer-verifications/*`

## Authorization

Organization access is allowed only when all of the following are true:

- the request belongs to the organization
- the authenticated user is a member of that organization
- the organization is not suspended
- the membership is not suspended

Subject access remains unchanged for subject-owned routes.

Organization-private state is never exposed to:

- subject-facing request detail
- subject-facing timeline
- public employer verification links

## Detail Response

`GET /api/v1/verification-requests/{verification_request_public_id}`

The authenticated detail response now includes backend-owned employment verification context needed by the HR Workspace:

- employment claim summary
- organization summary
- verification target summary
- evidence summary
- reviewer summary when viewed by an authorized organization member
- derived `review_status`
- `is_assigned_to_current_user`
- `organization_internal_note` for authorized organization members only

## Reviewer State

Reviewer assignment is stored on the canonical verification request using the existing `assigned_to_user_id` field.

Supported reviewer metadata:

- assigned reviewer identity
- derived review status
- whether the current viewer owns the assignment

Endpoint:

- `PUT /api/v1/verification-requests/{verification_request_public_id}/reviewer`

Request body:

```json
{
  "organization_member_public_id": "uuid-or-null"
}
```

Notes:

- the backend resolves the organization member to the assigned user internally
- assignee must be an active member of the same organization
- `null` clears the assignment
- legacy clients may continue sending `assignee_user_id`
- clients must send only one identifier field per request

## Internal Notes

HR internal notes are persisted on `verification_requests.organization_internal_note`.

Endpoint:

- `PUT /api/v1/verification-requests/{verification_request_public_id}/internal-note`

Request body:

```json
{
  "note": "Private note for the responding HR team."
}
```

Notes:

- note visibility is organization-internal only
- subject and public flows do not receive this field
- timeline events for note updates are filtered from non-organization viewers

## Evidence

`GET /api/v1/verification-requests/{verification_request_public_id}/evidence`

Organization-authorized evidence listing now supports:

- evidence metadata
- document metadata
- short-lived presigned download URLs
- both employment-document-backed and user-document-backed evidence

Evidence responses do not expose raw storage keys or bucket paths.

Returned document metadata fields:

- `document_type`
- `original_filename`
- `mime_type`
- `file_size`
- `upload_status`
- `download_url`
- `download_url_expires_in_seconds`

## Timeline Privacy

The authenticated timeline endpoint continues to return immutable workflow events.

The following organization-private events are hidden from subject viewers:

- reviewer assignment events
- internal note update events
- existing internal admin note events

## Migration

Revision `052` adds:

- `verification_requests.organization_internal_note`

The change is additive and backward compatible.

## Backward Compatibility

Existing endpoints remain valid.

Existing response fields remain valid.

New fields are additive and optional for clients that do not need the HR Workspace experience.
