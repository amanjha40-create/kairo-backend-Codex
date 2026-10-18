# HR V2 backend contract handoff

This document describes the additive backend contracts introduced at Alembic revision `092` for the certified HR V2 frontend. All paths below include the `/api/v1` prefix.

## Permission conventions

- **Active organization member**: authenticated user with a membership in the path organization; neither the organization nor membership may be suspended. This matches the existing `modify_person` / `modify_verification` workspace convention.
- **Organization manager**: authenticated active organization owner or admin. This matches the existing `manage_team` / `save_settings` convention.
- Cross-organization resources resolve as `404` where possible so membership and resource existence are not disclosed.

## 1. Employee lifecycle and Last Working Day

### Change lifecycle

- **Method/path:** `PATCH /organizations/{org_public_id}/people/{person_public_id}/lifecycle`
- **Permission:** active organization member.
- **Request:** `{ "employment_status": "active" | "ex_employee", "last_working_day": "YYYY-MM-DD" | null }`.
- **Response:** `{ person_public_id, employment_status, last_working_day, updated_at }`.
- **Errors:** `401` unauthenticated; `403` suspended organization/membership; `404` organization, membership, or person outside the organization; `409` attempted `ex_employee -> active`; `422` missing/invalid/future Last Working Day, or a Last Working Day before `joining_date`.
- **Semantics:** `active -> ex_employee` locks the person row, requires Last Working Day, changes the People relationship to `former_employee`, and writes `employee_marked_ex_employee`. It changes no verification, evidence, reference, note, report, Candidate-account, or Passport rows.
- **Reactivation:** deliberately unsupported in V1. The exact backend reason is: `Reactivation is not supported in HR V2 V1 because historical exit data requires a deliberate rehire lifecycle`.

### Read compatibility

Existing People list/detail endpoints remain unchanged and gain optional fields:

`employment_status`, `role_id`, `role`, `department`, `joining_date`, and `last_working_day`.

Existing rows deterministically read as `employment_status=active`. Existing client fields and route shapes were not removed.

## 2. Organization job-role CRUD

Job roles are employee job titles such as `Software Engineer`; they are not workspace authorization roles.

### List roles

- **Method/path:** `GET /organizations/{org_public_id}/job-roles`
- **Permission:** active organization member.
- **Request:** none.
- **Response:** array of `{ public_id, name, description, is_active, assigned_people_count, created_at, updated_at }`.
- **Errors:** `401`, `403`, `404` under the permission conventions above.
- **Compatibility:** counts are database-derived across the complete organization, not from a paginated frontend page. Inactive roles remain visible and retain their assignments.

### Create role

- **Method/path:** `POST /organizations/{org_public_id}/job-roles`
- **Permission:** organization manager.
- **Request:** `{ "name": string, "description": string | null }`.
- **Response:** role object above; HTTP `201`.
- **Errors:** `401`; `403` non-manager; `404` organization/membership; `409` case/whitespace-normalized duplicate within the same organization; `422` invalid length/empty name.

### Update role

- **Method/path:** `PATCH /organizations/{org_public_id}/job-roles/{role_public_id}`
- **Permission:** organization manager.
- **Request:** one or more of `{ name, description, is_active }`.
- **Response:** updated role object with current organization-wide count.
- **Errors:** `401`, `403`, `404`, `409` normalized duplicate, `422` empty update or invalid values.

### Deactivate role

- **Method/path:** `DELETE /organizations/{org_public_id}/job-roles/{role_public_id}`
- **Permission:** organization manager.
- **Request:** none.
- **Response:** role object with `is_active=false` and its preserved assignment count.
- **Errors:** `401`, `403`, `404`.
- **Compatibility:** this is a safe deactivation, not a hard delete. Existing People and Trust Invitation references remain valid; inactive roles cannot receive new assignments.

## 3. Role assignment and counts

### Assign employment profile

- **Method/path:** `PATCH /organizations/{org_public_id}/people/{person_public_id}/employment-profile`
- **Permission:** active organization member.
- **Request:** one or more of `{ "role_id": UUID | null, "department": string | null, "joining_date": "YYYY-MM-DD" | null }`.
- **Response:** `{ person_public_id, role_id, role, department, joining_date }`.
- **Errors:** `401`, `403`, `404` for an out-of-organization person/role, `409` for assigning an inactive role, `422` for an empty or invalid request.
- **Counts:** People directory `summary.by_role` and role list `assigned_people_count` are based on all matching organization People before page slicing. `summary.by_employment_status` is also additive.
- **Trust Invitations:** `POST /organizations/{org_public_id}/trust-invitations` accepts optional `role_id`. Responses add `role_id` and `role`. The legacy `purpose` field remains supported and is populated from the role name only when the caller did not provide a purpose.

## 4. Organization logo

The organization persists a private logical object key, content type, and byte count. It never persists or returns a permanent public URL.

### Initialize upload

- **Method/path:** `POST /organizations/{org_public_id}/logo/upload-intents`
- **Permission:** organization manager.
- **Request:** `{ "content_type": "image/png" | "image/jpeg" | "image/webp", "byte_size": 1..5000000 }`.
- **Response:** `{ upload_id, upload_url, expires_in_seconds, headers_required: { "Content-Type": ... } }`; HTTP `201`.
- **Errors:** `401`, `403`, `404`, `422` unsupported MIME (including SVG), empty/oversized file, or unavailable upload configuration.
- **Security:** the backend creates a random key under the authorized organization prefix. Callers never submit an object key.

### Confirm or replace logo

- **Method/path:** `POST /organizations/{org_public_id}/logo/confirm`
- **Permission:** organization manager.
- **Request:** `{ "upload_id": UUID }`.
- **Response:** `{ has_logo, display_url, display_url_expires_in_seconds, content_type, byte_size, updated_at }`.
- **Errors:** `401`, `403`, `404` cross-organization/unknown intent; `409` expired or already-used intent; `422` uploaded object missing, wrong size, or wrong Content-Type.
- **Semantics:** a row lock makes confirmation single-use. Storage HEAD metadata must match the intent. The previous object is removed best-effort only after the new reference commits. `organization_logo_changed` is recorded.

### Read logo

- **Method/path:** `GET /organizations/{org_public_id}/logo`
- **Permission:** active organization member.
- **Response:** the logo response above. `display_url` is a short-lived signed GET URL; no private object key is exposed.
- **Errors:** `401`, `403`, `404`, or `422` when display storage is not configured.

### Remove logo

- **Method/path:** `DELETE /organizations/{org_public_id}/logo`
- **Permission:** organization manager.
- **Response:** `{ "has_logo": false, "updated_at": ... }`.
- **Errors:** `401`, `403`, `404`.
- **Semantics:** clears the database reference atomically and then removes the former object best-effort.

## 5. Verification preferences

### Read preferences

- **Method/path:** `GET /organizations/{org_public_id}/verification-preferences`
- **Permission:** active organization member.
- **Response:** `{ version, checks, reference_count, updated_at }`.
- **Deterministic V1 defaults:** all supported checks are `false` and `reference_count=0`.
- **Supported write keys:** `identity`, `employment`, `education`, `references`, `address`.
- **Future-safe reads:** unknown stored check keys are preserved in reads so a newer writer is not silently destroyed by an older reader.

### Replace preferences

- **Method/path:** `PUT /organizations/{org_public_id}/verification-preferences`
- **Permission:** organization manager.
- **Request:** `{ "checks": { ...boolean keys... }, "reference_count": 0..10 }`.
- **Response:** normalized preferences with all V1 keys.
- **Errors:** `401`, `403`, `404`, `422` unknown write key, invalid boolean/count, or a positive reference count while references are disabled.
- **Compatibility:** writes affect defaults for new Trust Invitations only. Existing invitations, verification requests, and cases are not rewritten. Each new Trust Invitation stores an immutable preference snapshot; an explicitly supplied `requested_verification_types` list continues to win.
- **Court search:** the platform has no authoritative court-search order flow in this batch, so it is not accepted as a preference write key and is reported as `NOT_ORDERED`.

## 6. Team invitation create, resend, and accept

### Create

- **Method/path:** `POST /organizations/{org_public_id}/invitations`
- **Permission:** organization manager.
- **Request:** `{ "invitee_email": Email, "role": "member" | "reviewer" | "admin" }`. `owner` is rejected.
- **Response:** the existing invitation response plus additive `token_expires_at`, `token_used_at`, `last_sent_at`, and `delivery_failed_at` fields; HTTP `201`.
- **Errors:** `401`, `403`, `404`; `409` existing membership or actionable invitation; `422` invalid email/role or truthful email-queue failure.
- **Delivery:** generates a cryptographically secure 32-byte URL-safe token, persists only its SHA-256 hash, sets a seven-day expiry, queues exactly one existing email-adapter message, and records `team_invitation_created`. The raw token is neither returned by the API nor logged.

### Resend

- **Method/path:** `POST /organizations/{org_public_id}/invitations/{invitation_public_id}/resend`
- **Permission:** organization manager.
- **Request:** none.
- **Response:** updated invitation response.
- **Errors:** `401`, `403`, `404`, `409` invitation no longer actionable or user already a member, `422` truthful email-queue failure.
- **Semantics:** rotates the token hash and increments its version, immediately invalidating the previous link; resets expiry to seven days; queues exactly one message; records `team_invitation_resent`.

### Public token lookup

- **Method/path:** `GET /workspace/team-invitations/{token}`
- **Permission:** possession of a valid opaque token; no authentication required.
- **Response:** `{ organization_name, invited_role, status, expires_at }` only.
- **Errors:** `404` invalid/short token without account enumeration; `409` expired, revoked, cancelled, declined, or consumed token.

### Accept

- **Method/path:** `POST /workspace/team-invitations/{token}/accept`
- **Permission:** authenticated account whose normalized email matches the invitation (and whose user ID matches when the invitation was already bound).
- **Request:** none.
- **Response:** `{ organization_public_id, membership_public_id, role, accepted_at }`.
- **Errors:** `401`; `403` invited-email/user mismatch; `404` invalid token; `409` expired/revoked/used token, suspended membership, or conflicting existing membership role.
- **Semantics:** membership creation, token consumption, accepted state, active organization selection, and `team_invitation_accepted` event commit together. A token is single-use.
- **Legacy compatibility:** the older authenticated UUID acceptance route remains available only for historical rows whose new `token_hash` is null. Tokenized invitations must use the secure-token route.

### Required frontend acceptance URL

Production invitation email CTA must resolve to exactly:

`https://hr.kairoid.com/team-invitations/accept?token={opaque_token}`

That frontend route must authenticate or sign up the recipient as appropriate, retain the token through authentication, and then call the token acceptance endpoint above.

## 7. Structured Verification Report

### Read authoritative report

- **Method/path:** `GET /organizations/{org_public_id}/people/{person_public_id}/verification-report`
- **Permission:** active organization member.
- **Request:** none.
- **Response content type:** JSON only; no HTML.
- **Errors:** `401`, `403` suspended access, `404` organization/membership/person outside the organization.
- **Compatibility:** read-only additive projection for both on-screen and print/PDF rendering. Existing verification APIs are unchanged.

The response has `schema_version=hr_verification_report_v1` and includes:

- `header`: authoritative person name, role, person ID, initiation time, requesting organization, masked contact, consent time, Trust Score, update time, and backend-derived `INTERIM`/`FINAL`.
- `check_summaries[]`: `CONFIRMED`, `DETAILS_MATCHED`, `DISCREPANCY`, `PENDING`, `AWAITING_RESPONSE`, `UNABLE_TO_VERIFY`, `REJECTED`, or `NOT_ORDERED`.
- typed arrays for `identity`, `employment`, `education`, `references`, `address`, and `court_search`.
- `open_items[]` with machine-readable reason code, check, safe display text, and request ID.
- `hr_review_required`, derived from discrepancy/rejection/unable-to-verify states.

`FINAL` is returned only when at least one verification request exists and every request is terminal. A never-requested check is `NOT_ORDERED`; it is never implied complete. Court search is currently returned as a typed `NOT_ORDERED` item because no authoritative court-search data source exists.

### Report privacy and provenance

The projection only selects safe fields from canonical records. It masks contact and employee identifiers and never exposes full Aadhaar, OAuth/access tokens, raw provider responses, raw private S3 URLs, permanent-address coordinates, ciphertext, encryption key IDs, or internal notes. Address output is restricted to display-safe address components plus method, date, status, scope, physical-visit boolean, and evidence ID. Pending reference/non-response states remain neutral.

## Migration and rollout notes

- Alembic head: `092`, a single successor to `091`.
- The migration is additive: nullable references and token state, deterministic `active`/empty JSON defaults, new role/upload/activity tables, and no historical case rewrite.
- HR V2 frontend and backend need not deploy simultaneously. Existing Candidate, HR, Admin, Institution, mobile, Public Passport, and Document Pack contracts keep their existing routes and required fields.
- No Production feature flag, schema, data, provider, or deployment action is part of this source handoff.
