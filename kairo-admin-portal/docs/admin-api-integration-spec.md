# Admin API Integration Specification

Status: Draft proposal  
Last updated: July 24, 2026  
Frontend application: Kairo Operations Hub / Admin Portal  
Frontend host: `admin.kairoid.com`

## Purpose

This document defines the proposed backend integration contract required by the Admin Portal frontend. It is derived from the current production-hardened frontend surface and is intended to align frontend and backend implementation before live API wiring begins.

Important:

- This is a proposed contract, not a description of an already deployed backend.
- The frontend currently supports demo mode and intentionally refuses silent production fallback.
- Endpoint names below are recommended resource paths for review and approval.

## Goals

- Provide a safe production authentication contract.
- Replace deterministic mock data behind `src/features/admin/data/*`.
- Support the current admin UI and workflows without redesigning routes, roles, or modules.
- Establish common error, pagination, filtering, authorization, and observability conventions.

## Non-Goals

- This document does not authorize backend business logic changes.
- This document does not define public Kairo APIs.
- This document does not claim that frontend permission checks are sufficient security.

## Frontend Constraints

The backend contract must satisfy these existing frontend boundaries:

- `AdminAuthProvider` and `useAdminAuth()`
- `src/features/admin/data/*`
- `src/lib/api/client.ts`
- `src/lib/query-client.ts`

Current frontend routes:

- `/admin/login`
- `/admin/forgot-password`
- `/admin`
- `/admin/verifications`
- `/admin/verifications/$caseId`
- `/admin/users`
- `/admin/users/$userId`
- `/admin/registry`
- `/admin/registry/$organizationId`
- `/admin/communications`
- `/admin/communications/$communicationId`
- `/admin/risk`
- `/admin/risk/$investigationId`
- `/admin/system`

Current admin roles:

- `operations_lead`
- `admin`
- `trust_safety`
- `reviewer`
- `read_only`

## Environment and Transport

- The frontend uses `VITE_API_BASE_URL` as the admin backend base URL.
- All requests should use `credentials: "include"` for secure cookie-based auth.
- All request and response bodies should be JSON unless explicitly documented otherwise.
- All timestamps should be ISO 8601 strings in UTC.
- All list endpoints should support cancellation through normal HTTP connection termination; the frontend already passes `AbortSignal`.

Recommended base path:

- `https://<admin-api-host>/api/admin`

## Security Requirements

- Authentication must be server-backed.
- Sessions must use secure, `HttpOnly`, same-site cookies.
- Backend authorization must be enforced on every admin endpoint.
- The backend must not trust frontend-sent role overrides or hidden-button state.
- 401 and 403 responses must be distinct.
- Correlation IDs should be returned on every response using `X-Request-Id` or `X-Correlation-Id`.

## Common Conventions

### Success response

Recommended envelope for non-list endpoints:

```json
{
  "data": {}
}
```

Recommended envelope for list endpoints:

```json
{
  "data": [],
  "page": {
    "page": 1,
    "pageSize": 25,
    "totalItems": 250,
    "totalPages": 10
  }
}
```

### Error response

Recommended error envelope:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Some fields need attention before this request can be completed.",
    "details": {},
    "requestId": "req_123"
  }
}
```

Expected status handling already mapped in the frontend:

- `401` unauthenticated or expired session
- `403` authenticated but not authorized
- `404` resource not found
- `409` state conflict
- `422` validation error
- `429` rate limited
- `5xx` backend failure

### Pagination

Recommended query parameters:

- `page`
- `pageSize`
- `sort`
- `direction`

### Filtering

Recommended filter encoding:

- Repeated query params for multi-select filters
- Plain strings for singular filters
- ISO timestamps for date boundaries

Example:

```text
GET /api/admin/verifications?page=1&pageSize=25&status=pending_review&status=resubmitted&priority=high&priority=urgent&query=jonas
```

### Idempotency

Recommended for state-changing admin actions:

- Accept `Idempotency-Key` on `POST` action endpoints.

## Authentication and Session Contract

### 1. Create session

`POST /api/admin/auth/session`

Purpose:

- Log an admin user in.

Request:

```json
{
  "email": "operator@kairo.internal",
  "password": "string",
  "remember": true
}
```

Response:

```json
{
  "data": {
    "account": {
      "id": "adm_123",
      "email": "operator@kairo.internal",
      "name": "Aman Jha",
      "initials": "AJ",
      "roleKey": "operations_lead",
      "role": "Operations Lead",
      "permissions": ["verification.verify", "communications.view"]
    },
    "signedInAt": "2026-07-24T12:00:00.000Z",
    "expiresAt": "2026-07-24T20:00:00.000Z"
  }
}
```

### 2. Read current session

`GET /api/admin/auth/session`

Purpose:

- Restore session on load and refresh.

Behavior:

- `200` with session payload when authenticated
- `401` when not authenticated or expired

### 3. Delete session

`DELETE /api/admin/auth/session`

Purpose:

- Sign out the current admin session.

Response:

- `204 No Content`

### 4. Forgot password request

`POST /api/admin/auth/forgot-password`

Request:

```json
{
  "email": "operator@kairo.internal"
}
```

Response:

- Always return a non-enumerating success payload.

```json
{
  "data": {
    "accepted": true
  }
}
```

## Authorization Model

The backend session payload must return:

- `roleKey`
- human-readable `role`
- fully resolved `permissions`

The frontend already consumes permission strings such as:

- `verification.verify`
- `verification.assign`
- `users.view`
- `communications.view`
- `risk.review`
- `system.alerts.manage`

Backend responses should treat permissions as the source of truth, even if roles remain stable.

## Domain Contracts

### 1. Overview

#### `GET /api/admin/overview`

Must provide:

- business metrics
- attention items
- onboarding funnel
- verification status summaries
- recent activity feed
- platform summary cards

Frontend adapter target:

- `src/features/admin/data/overview.ts`

### 2. Verifications

#### `GET /api/admin/verifications`

Must support:

- search by candidate, organization, role, reference
- filtering by status, priority, assignee, organization status, SLA state, attention flag, verification type
- sorting by submitted date, updated date, priority, SLA risk

#### `GET /api/admin/verifications/{caseId}`

Must provide the case workspace payload, including:

- summary
- claim data
- evidence
- organization resolution data
- contact candidates
- communications timeline
- corrections
- internal notes
- attention flags
- decision metadata
- case timeline

Frontend adapter targets:

- `src/features/admin/data/verifications.ts`
- `src/features/admin/data/cases.ts`

#### Proposed action endpoints

These map directly to the current case workflow surface:

- `POST /api/admin/verifications/{caseId}/actions/request-correction`
- `POST /api/admin/verifications/{caseId}/actions/approve-outreach`
- `POST /api/admin/verifications/{caseId}/actions/verify`
- `POST /api/admin/verifications/{caseId}/actions/reject`
- `POST /api/admin/verifications/{caseId}/actions/unable-to-verify`
- `POST /api/admin/verifications/{caseId}/actions/request-clarification`
- `POST /api/admin/verifications/{caseId}/actions/record-clarification-response`
- `POST /api/admin/verifications/{caseId}/assignment`
- `POST /api/admin/verifications/{caseId}/priority`

Each action response should return the updated case detail payload.

### 3. Users

#### `GET /api/admin/users`

Must support:

- search by name, email, phone, employer, education
- filtering by account status, profile type, passport status, onboarding state

#### `GET /api/admin/users/{userId}`

Must provide:

- profile summary
- account status
- passport overview
- onboarding summary
- career records
- documents
- shares
- security events
- activity timeline
- verification relationships

Frontend adapter target:

- `src/features/admin/data/users.ts`

#### Proposed action endpoints

- `POST /api/admin/users/{userId}/actions/prepare-password-reset`
- `POST /api/admin/users/{userId}/actions/resend-verification`
- `POST /api/admin/users/{userId}/actions/disable-account`
- `POST /api/admin/users/{userId}/actions/enable-account`
- `POST /api/admin/users/{userId}/actions/revoke-sessions`
- `POST /api/admin/users/{userId}/actions/flag-risk`
- `POST /api/admin/users/{userId}/actions/prepare-data-export`
- `POST /api/admin/users/{userId}/actions/prepare-deletion`

These can remain “prepared action” endpoints initially if the backend prefers explicit human review flows.

### 4. Registry

#### `GET /api/admin/registry`

Must provide:

- canonical organizations
- verified and unverified states
- duplicate review state
- org type and location metadata
- aggregate registry metrics

#### `GET /api/admin/registry/{organizationId}`

Must provide:

- organization profile
- aliases
- contacts
- activity trail

Frontend adapter target:

- `src/features/admin/data/registry.ts`

### 5. Communications

#### `GET /api/admin/communications`

Must support:

- search by communication reference, case reference, candidate, organization, template, subject
- filtering by channel, type, status, assignee, verification type
- follow-up visibility
- failed-only and awaiting-response views

#### `GET /api/admin/communications/{communicationId}`

Must provide:

- communication metadata
- delivery events
- follow-ups
- failure records
- employer responses
- internal notes
- template reference

Frontend adapter target:

- `src/features/admin/data/communications.ts`

#### Proposed action endpoints

- `POST /api/admin/communications/{communicationId}/notes`
- `POST /api/admin/communications/{communicationId}/follow-ups`
- `PATCH /api/admin/communications/{communicationId}/follow-ups/{followUpId}`
- `POST /api/admin/communications/{communicationId}/failure-review`
- `POST /api/admin/communications/{communicationId}/manual-contact-log`

### 6. Risk / Trust & Safety

#### `GET /api/admin/risk`

Must support:

- filtering by risk level, status, category, subject kind, country, verification type, investigator
- search by investigation reference, subject, related case, related user, related organization

#### `GET /api/admin/risk/{investigationId}`

Must provide:

- investigation summary
- risk signals
- document anomalies
- duplicate review candidates
- evidence references
- notes
- recommended actions
- timeline

Frontend adapter target:

- `src/features/admin/data/risk.ts`

#### Proposed action endpoints

- `POST /api/admin/risk/{investigationId}/notes`
- `POST /api/admin/risk/{investigationId}/duplicate-review`
- `POST /api/admin/risk/{investigationId}/status`
- `POST /api/admin/risk/{investigationId}/prepare-action`

### 7. System

#### `GET /api/admin/system`

Must provide:

- service health
- background jobs
- feature flags
- message logs
- audit events
- alerts
- deployments
- configuration reference
- system overview metrics

Frontend adapter target:

- `src/features/admin/data/system.ts`

#### Proposed action endpoints

- `POST /api/admin/system/jobs/{jobId}/actions`
- `POST /api/admin/system/flags/{flagId}/changes`
- `POST /api/admin/system/alerts/{alertId}/actions`
- `POST /api/admin/system/incidents`

Recommended behavior:

- Preserve “prepare” semantics where the UI currently represents session-only operational prep.
- If execution is not yet allowed, return explicit prepared-state records rather than silently mutating infrastructure.

## Data Shape Expectations

The backend payloads should preserve stable identifiers and enum values already modeled by the frontend.

Critical examples:

- verification statuses such as `pending_review`, `resubmitted`, `awaiting_employer`, `verified`
- priorities such as `low`, `normal`, `high`, `urgent`
- role keys such as `operations_lead`, `admin`, `trust_safety`, `reviewer`, `read_only`

For precise shape references, review:

- `src/features/admin/data/types.ts`
- `src/features/admin/data/verifications.ts`
- `src/features/admin/data/cases.ts`
- `src/features/admin/data/users.ts`
- `src/features/admin/data/registry.ts`
- `src/features/admin/data/communications.ts`
- `src/features/admin/data/risk.ts`
- `src/features/admin/data/system.ts`

## Query-Key Mapping

Recommended backend resource alignment with current frontend query keys:

- `["admin", "overview", "metrics"]`
- `["admin", "verifications", "list"]`
- `["admin", "verifications", "detail", caseId]`
- `["admin", "cases", "detail", caseId]`
- `["admin", "users", "list"]`
- `["admin", "users", "detail", userId]`
- `["admin", "registry", "list"]`
- `["admin", "registry", "detail", organizationId]`
- `["admin", "communications", "list"]`
- `["admin", "communications", "detail", communicationId]`
- `["admin", "communications", "metrics"]`
- `["admin", "risk", "list"]`
- `["admin", "risk", "detail", investigationId]`
- `["admin", "system", "overview"]`

## Observability

Recommended backend behavior:

- Return correlation IDs on all responses.
- Log auth failures, permission denials, and state conflicts with request IDs.
- Do not return sensitive internal exception detail to the client.

## Open Decisions Requiring Approval

- Final backend host and deployment topology
- Final endpoint path naming
- Whether action endpoints execute immediately or create reviewable “prepared actions”
- Session duration and refresh strategy
- Rate limits for sensitive admin actions
- Audit retention requirements
- Whether some list endpoints require cursor pagination instead of page/pageSize

## Minimum Contract Needed To Exit Demo Mode

Before the frontend can disable demo mode in production, the backend must provide at minimum:

1. `POST /auth/session`
2. `GET /auth/session`
3. `DELETE /auth/session`
4. `POST /auth/forgot-password`
5. `GET /overview`
6. `GET /verifications`
7. `GET /verifications/{caseId}`
8. Resolved permission claims in the session payload
9. Distinct `401` and `403` handling
10. Correlation IDs on responses

## Recommended Next Step

Review this document jointly with backend, security, and operations owners, then convert approved sections into a versioned API contract such as OpenAPI.
