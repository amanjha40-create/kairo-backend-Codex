# API Contract

This document defines the current backend contract for Kairo's FastAPI service.

Base path: `/api/v1`

Primary goals:

- keep request and response shapes stable for frontend integration
- expose `public_id` values externally instead of internal relational keys where platform engines support it
- make error and pagination behavior predictable across modules

## Auth Flow

Authentication uses bearer access tokens plus refresh tokens on the auth lifecycle endpoints.

Core auth endpoints:

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `POST` | `/auth/register` | No | Start signup and send OTP |
| `POST` | `/auth/signup/start` | No | Alias for signup start |
| `POST` | `/auth/signup/verify` | No | Verify OTP and issue tokens |
| `POST` | `/auth/signup/resend` | No | Resend signup OTP |
| `POST` | `/auth/login` | No | Login with email and password |
| `POST` | `/auth/forgot-password` | No | Request password reset with generic response |
| `POST` | `/auth/reset-password` | No | Reset password using one-time token |
| `POST` | `/auth/refresh` | Refresh payload | Rotate refresh token |
| `POST` | `/auth/logout` | Refresh payload | Revoke refresh token |
| `POST` | `/auth/set-password` | Bearer | Set password for current user |
| `POST` | `/auth/change-password` | Bearer | Change password for current user |

Auth notes:

- authenticated APIs use bearer JWT access tokens
- access control is enforced in route dependencies and service-layer authorization checks
- auth endpoints are rate-limited
- forgot-password always returns a generic success message and does not reveal whether an account exists

## Error Response Format

The shared error envelope is:

```json
{
  "error": {
    "code": "not_found",
    "message": "Trust Passport not found",
    "details": [
      {
        "location": ["query", "page"],
        "message": "Input should be greater than or equal to 1",
        "error_type": "greater_than_equal"
      }
    ]
  }
}
```

Rules:

- `error.code` is a stable machine-readable value
- `error.message` is the primary client-facing message
- `error.details` is optional and primarily used for validation failures
- framework `401`, `403`, `404`, `409`, `422`, `429`, `500`, and `503` responses use the shared envelope

Common codes:

- `unauthorized`
- `forbidden`
- `not_found`
- `conflict`
- `validation_error`
- `rate_limited`
- `service_unavailable`
- `internal_error`

## Pagination Format

List endpoints use the shared page envelope where supported:

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 20,
  "total_pages": 0,
  "offset": 0,
  "limit": 20
}
```

Query parameters:

- `page`
- `page_size`
- legacy-compatible `offset`
- legacy-compatible `limit`
- `paginate=true` for routes that preserve backward-compatible list behavior when pagination is not explicitly requested
- optional list filters where supported:
  - `search`
  - `status`
  - `created_after`
  - `created_before`
  - `sort_by`
  - `sort_order`

Rules:

- timestamps are ISO8601 strings
- sort order defaults to descending when supported
- some older modules still use simpler `PageParams` only; newer platform engines use the richer `ListQueryParams`

## `public_id` Rules

Kairo platform engines use `public_id` as the stable external identifier for API paths and response payloads where supported.

Rules:

- `public_id` is the preferred external identifier for organization, invitation, verification request, evidence, corrections, and review objects
- internal database joins may still use internal UUID primary keys
- clients should treat internal numeric or relational identifiers as implementation details
- legacy modules may still expose `id` where they predate the `public_id` contract; new platform-facing integrations should prefer engines already using `public_id`

## Passport APIs

### Authenticated owner-facing

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| `GET` | `/passport/me` | Bearer | Canonical owner-facing Trust Passport aggregation |
| `GET` | `/dashboard` | Bearer | Backend-owned dashboard aggregation |
| `GET` | `/onboarding/status` | Bearer | Backend-owned onboarding state |
| `GET` | `/trust-score` | Bearer | Current trust score breakdown |
| `GET` | `/passport-shares` | Bearer | Share links owned by current user |
| `POST` | `/passport-shares` | Bearer | Create share link; raw share URL returned once |
| `GET` | `/passport-shares/{share_id}` | Bearer | Read owned share link |
| `PATCH` | `/passport-shares/{share_id}` | Bearer | Update owned share link |
| `POST` | `/passport-shares/{share_id}/revoke` | Bearer | Revoke owned share link |
| `GET` | `/passport-shares/{share_id}/analytics` | Bearer | Owner-only analytics |

### Public Trust Passport

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| `GET` | `/public/passport/{token}` | No | Token-based public Trust Passport; fail-closed for unknown, expired, or revoked links |

Public Trust Passport notes:

- response is backend-authoritative
- sharing permissions are enforced server-side
- successful views may be tracked for analytics

## Organization APIs

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| `POST` | `/organizations` | Bearer | Create organization |
| `GET` | `/organizations/me` | Bearer | List organizations for current user |
| `GET` | `/organizations/{org_public_id}` | Bearer | View organization details if member |
| `POST` | `/organizations/{org_public_id}/members` | Bearer | Add member; owner/admin only |
| `GET` | `/organizations/{org_public_id}/members` | Bearer | List members for an organization |
| `PATCH` | `/organizations/{org_public_id}/members/{member_public_id}` | Bearer | Update role; owner/admin only |

Organization notes:

- organization membership is enforced server-side
- platform-supported roles are `owner`, `admin`, `member`, and `reviewer`
- list endpoints support the shared pagination/filter contract

## Trust Invitation APIs

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| `POST` | `/organizations/{org_public_id}/trust-invitations` | Bearer | Create invitation |
| `GET` | `/organizations/{org_public_id}/trust-invitations` | Bearer | List invitations for organization |
| `GET` | `/trust-invitations/{token}` | No | Public sanitized lookup |
| `POST` | `/trust-invitations/{token}/accept` | Bearer | Accept invitation; email match enforced |
| `POST` | `/trust-invitations/{trust_invitation_public_id}/cancel` | Bearer | Cancel invitation; owner/admin only |

Trust invitation notes:

- raw invitation token/URL is returned only once at creation
- only hashed token state is stored server-side
- unknown, expired, accepted, and cancelled tokens fail closed

## Verification Request APIs

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| `POST` | `/organizations/{organization_public_id}/verification-requests` | Bearer | Organization-created request |
| `GET` | `/organizations/{organization_public_id}/verification-requests` | Bearer | List organization requests |
| `POST` | `/verification-requests` | Bearer | Subject-initiated request |
| `GET` | `/verification-requests/me` | Bearer | List subject-owned requests |
| `GET` | `/verification-requests/{verification_request_public_id}` | Bearer | Read one request |
| `POST` | `/verification-requests/{verification_request_public_id}/accept` | Bearer | Subject acceptance |
| `POST` | `/verification-requests/{verification_request_public_id}/submit-for-review` | Bearer | Submit to admin review |
| `POST` | `/verification-requests/{verification_request_public_id}/resubmit` | Bearer | Subject resubmission after corrections |
| `POST` | `/verification-requests/{verification_request_public_id}/request-information` | Bearer | Organization/admin-side action where permitted |
| `POST` | `/verification-requests/{verification_request_public_id}/verify` | Bearer | Verification workflow action |
| `POST` | `/verification-requests/{verification_request_public_id}/reject` | Bearer | Verification workflow action |
| `POST` | `/verification-requests/{verification_request_public_id}/cancel` | Bearer | Verification workflow action |
| `GET` | `/verification-requests/{verification_request_public_id}/timeline` | Bearer | Immutable event timeline |

### Evidence and corrections

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| `GET` | `/verification-requests/{verification_request_public_id}/evidence` | Bearer | List evidence |
| `POST` | `/verification-requests/{verification_request_public_id}/evidence` | Bearer | Add evidence |
| `PATCH` | `/verification-requests/{verification_request_public_id}/evidence/{evidence_public_id}` | Bearer | Update evidence |
| `GET` | `/verification-requests/{verification_request_public_id}/corrections` | Bearer | List correction requests |

Verification request notes:

- the workflow object is the canonical record for trust verification lifecycle
- status transitions are owned by the workflow service, not mutated directly in routes
- evidence and correction objects use stable `public_id` values

## Admin Review APIs

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| `GET` | `/admin/verification-requests/queue` | Admin reviewer roles | Review queue |
| `GET` | `/admin/verification-requests/{verification_request_public_id}` | Admin reviewer roles | Review detail |
| `POST` | `/admin/verification-requests/{verification_request_public_id}/assign` | Admin reviewer roles | Assign reviewer |
| `POST` | `/admin/verification-requests/{verification_request_public_id}/notes` | Admin reviewer roles | Add review note |
| `POST` | `/admin/verification-requests/{verification_request_public_id}/request-corrections` | Admin reviewer roles | Return request for correction |
| `POST` | `/admin/verification-requests/{verification_request_public_id}/approve` | Admin reviewer roles | Approve review stage |
| `POST` | `/admin/verification-requests/{verification_request_public_id}/reject` | Admin reviewer roles | Reject review stage |
| `POST` | `/admin/verification-requests/{verification_request_public_id}/resolve-organization` | Admin reviewer roles | Resolve target organization |
| `GET` | `/admin/verification-requests/{verification_request_public_id}/timeline` | Admin reviewer roles | Review timeline view |

Admin review notes:

- admin review is a stage in the verification lifecycle, not a separate product workflow
- notes, corrections, decisions, and timeline entries are auditable
- queue and timeline endpoints use the shared pagination contract

## Frontend Integration Notes

- the backend should be treated as the source of truth for Trust Passport, dashboard, onboarding status, and verification lifecycle state
- clients should rely on documented response shapes rather than sample fallback payloads
- route consumers should expect the shared error envelope across protected, not-found, conflict, validation, and infrastructure-related responses
- list consumers should handle the shared page envelope and not infer pagination metadata client-side
- newer platform APIs prefer `public_id` in paths and payloads; integrations should use those values directly
- public Trust Passport rendering should be driven by `/public/passport/{token}` rather than frontend-assembled data
