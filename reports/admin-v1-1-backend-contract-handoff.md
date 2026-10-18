# Admin V1.1 backend contract handoff

This document is the frontend integration contract for the additive Admin Operations V1.1
backend at Alembic revision `093`. All API paths below include the `/api/v1` prefix.

## Shared conventions

- Admin endpoints require a bearer token plus the named permission. Authentication by itself is
  insufficient. The `admin` and `superadmin` roles contain all seven new permissions; Candidate
  users contain none.
- Errors use `{ "error": { "code": string, "message": string, "details"?: [...] } }`.
  Common statuses are `401` unauthenticated, `403` missing permission, `404` missing or
  out-of-scope resource, `409` lifecycle/duplicate conflict, `422` invalid input, and `429`
  activation-resend cooldown (with `Retry-After`).
- UUID `idempotency_key` values must remain stable for a frontend retry of the same create action.
  A new user action must use a new UUID.
- Admin responses never return a password, activation token, invitation token, raw evidence
  payload, permanent S3 URL, or unmasked Candidate contact.
- Successful mutations should invalidate/refetch the resources identified in each section. Do not
  optimistically infer verification or ownership state.

## 1. Assisted Candidate/person creation

### Create

- **Method/path:** `POST /admin/operations/candidates`
- **Permission:** `create_person`
- **Request:**

  ```json
  {
    "full_name": "Candidate Name",
    "email": "candidate@example.com",
    "phone": "+919876543210",
    "headline": "Software Engineer",
    "location": "Bengaluru",
    "idempotency_key": "UUID"
  }
  ```

  `phone`, `headline`, and `location` are optional. Email and phone are normalized server-side.
- **Response (`201`):**

  ```json
  {
    "candidate_id": "UUID",
    "full_name": "Candidate Name",
    "email_masked": "c***@example.com",
    "phone_masked": "+91******3210",
    "claim_status": "admin_created_unclaimed",
    "password_configured": false,
    "email_verified": false,
    "phone_verified": false,
    "activation_expires_at": null,
    "activation_last_sent_at": null,
    "created_at": "ISO-8601"
  }
  ```
- **Conflicts:** `candidate_email_exists`, `candidate_phone_exists`,
  `candidate_unclaimed_exists`, `candidate_signup_pending`, or `candidate_pending_deletion`.
- **Lifecycle:** the row is active only as a managed record. It has no password, no verified
  contact, and explicit `admin_created_unclaimed` claim state. Initial field provenance is
  `admin_entered`.
- **Refetch:** invalidate Admin People/Candidate lists and fetch the status endpoint below.

### Safe status

- **Method/path:** `GET /admin/operations/candidates/{candidate_id}`
- **Permission:** `create_person`
- **Response:** the create response shape, with current claim/activation timestamps.
- **Errors:** `404` for a non-managed, deleted, or cross-resource Candidate.
- **Refetch:** after activation send/resend, claim, or assisted-profile mutation.

## 2. Candidate activation and account claim

### Send activation

- **Method/path:** `POST /admin/operations/candidates/{candidate_id}/activation`
- **Permission:** `send_candidate_activation`
- **Request:** no body.
- **Response (`201`):**

  ```json
  {
    "candidate_id": "UUID",
    "claim_status": "activation_pending",
    "email_masked": "c***@example.com",
    "expires_at": "ISO-8601",
    "last_sent_at": "ISO-8601",
    "resend_available_at": "ISO-8601",
    "delivery_state": "queued"
  }
  ```
- **Errors:** `candidate_already_claimed`, `candidate_activation_exists`, delivery failure, or
  ordinary auth/not-found errors.
- **Lifecycle:** a 48-byte URL-safe credential is generated, only its SHA-256 representation is
  stored, and the single-use link expires after 24 hours. The email CTA is exactly
  `https://app.kairoid.com/activate-account?token={opaque_token}`.
- **Refetch:** Candidate status and Admin Candidate list row.

### Resend activation

- **Method/path:** `POST /admin/operations/candidates/{candidate_id}/activation/resend`
- **Permission:** `send_candidate_activation`
- **Request:** no body.
- **Response:** activation response above.
- **Errors:** `429 rate_limited` before the 60-second cooldown; claimed/not-found/delivery errors.
- **Lifecycle:** locks the Candidate, revokes the preceding usable credential, increments token
  version, sets a fresh 24-hour expiry, and queues a new link. The old link immediately fails.
- **Refetch:** Candidate status; replace local countdown from response timestamps.

### Validate public token

- **Method/path:** `POST /candidate-activations/validate`
- **Permission:** possession of a valid token; no login required.
- **Request:** `{ "token": "opaque token" }`. The token is intentionally in the body, not query
  telemetry.
- **Response:** `{ candidate_id, claim_status, full_name, email_masked, expires_at,
  password_required: true, email_verification_via_activation: true }`.
- **Errors:** `404` invalid/unknown token, `410` expired token, `409` revoked/used/undelivered token.
- **Refetch:** none; render the claim page from this safe projection.

### Claim account

- **Method/path:** `POST /candidate-activations/claim`
- **Permission:** possession of the Candidate-bound token; no login required.
- **Request:** `{ "token": string, "password": string, "confirm_password": string }`; password
  length is 12–128 and both values must match.
- **Response:** `{ candidate_id, claim_status: "claimed", claimed_at, email_verified,
  phone_verified, next_action: "sign_in" }`.
- **Errors:** the validate-token errors plus request validation errors.
- **Lifecycle:** the Candidate, not Admin, selects the password. Consumption and password hashing
  occur in one locked transaction, sibling tokens are revoked, and reuse is denied. The emailed
  opaque link legitimately proves that email contact; phone verification remains unchanged.
- **Refetch:** clear all activation state and navigate to Candidate sign-in. An Admin screen should
  refetch Candidate status when next viewed.

## 3. Admin CV upload, parse, review, and selected import

These endpoints deliberately wrap the existing Candidate Resume/Review engine; there is no second
parser and no auto-import of parser output. Every endpoint requires `manage_assisted_profile` and
first verifies that `{candidate_id}` is an Admin-managed Candidate.

| Action | Method and path | Request / response |
|---|---|---|
| Upload intent | `POST /admin/operations/candidates/{candidate_id}/resumes/upload-intent` | Existing `ResumeUploadIntentRequest` → `ResumeUploadIntentResponse` (`201`) |
| Complete upload | `POST /admin/operations/candidates/{candidate_id}/resumes/{resume_id}/complete-upload` | Existing `ResumeCompleteUploadRequest` → `ResumeResponse` |
| Process | `POST /admin/operations/candidates/{candidate_id}/resumes/{resume_id}/process` | no body → `ResumeProcessResponse` |
| Read parsed draft | `GET /admin/operations/candidates/{candidate_id}/resumes/{resume_id}/parsed-result` | no body → `ResumeParsedResultResponse` |
| Create review | `POST /admin/operations/candidates/{candidate_id}/resumes/{resume_id}/review-session` | no body → `ReviewSessionResponse` (`201`) |
| Edit/select review item | `PATCH /admin/operations/candidates/{candidate_id}/resume-reviews/{review_id}/items/{item_id}` | existing `ReviewItemUpdateRequest` → `ReviewItemResponse` |
| Validate import plan | `POST /admin/operations/candidates/{candidate_id}/resume-reviews/{review_id}/validate` | existing `ReviewValidateRequest` → `ReviewPlanResponse` |
| Commit selected items | `POST /admin/operations/candidates/{candidate_id}/resume-reviews/{review_id}/import` | existing `ReviewImportRequest` → `ImportBatchResponse` (`201`) |

- **Errors:** existing Resume ownership, lifecycle, MIME/size/storage, parser, review validation,
  duplicate, and verified-record protection errors; `404` also covers a Candidate outside Admin
  assisted scope.
- **Provenance:** committed rows keep `source=cv_extracted`,
  `confirmation_source=admin_confirmed_for_profile`, and `confirmed_by_user_id=<Admin>`. This is
  not source verification.
- **Refetch:** poll processing using existing Resume rules; after import, invalidate Candidate
  profile, Career lists, review session, and import history.

## 4. Assisted profile/Career mutation and Candidate confirmation

### Basic profile

- **Method/path:** `PATCH /admin/operations/candidates/{candidate_id}/profile`
- **Permission:** `manage_assisted_profile`
- **Request:** at least one of `full_name`, `phone`, `current_role`, `industry`,
  `years_of_experience`, `location`, `location_city`, `location_region`, `location_country`,
  `headline`, or `bio`; `source` is `admin_entered` or `cv_extracted`.
- **Response:** `{ candidate_id, claim_status, updated_fields, provenance_source,
  candidate_confirmation_required: true }`.
- **Errors:** duplicate phone, invalid normalized field, unmanaged Candidate, or
  `source_verified_field_protected`.
- **Lifecycle:** changed phone loses any prior phone-verification timestamp. Every non-null field
  adds append-only value-hash provenance; source-verified fields cannot be lowered.
- **Refetch:** Candidate status/profile and provenance-review UI.

### Career create/update

- **Method/path:** `POST /admin/operations/candidates/{candidate_id}/career` (`201`) or
  `PATCH /admin/operations/candidates/{candidate_id}/career/{record_id}`.
- **Permission:** `manage_assisted_profile`
- **Request:** `{ "claim_type": "employment" | "education" | "internship" | "freelance" |
  "certification", "payload": { ...canonical claim fields... }, "source": "admin_entered" |
  "cv_extracted" }`.
- **Response:** `{ candidate_id, claim_type, record_id, updated_fields, provenance_source,
  verification_status }`.
- **Errors:** canonical claim validation, cross-user/missing record, protected active/verified
  record, or `source_verified_field_protected`.
- **Lifecycle:** the canonical Resume Review validators/builders are reused. An Admin mutation does
  not set a verification result.
- **Refetch:** the affected Career collection, profile completion, and provenance-review UI.

### Candidate confirmation

- **Method/path:** `POST /candidate/profile/provenance/confirm`
- **Permission:** authenticated Candidate; only their own provenance is addressable.
- **Request:** `{ "items": [{ "record_type": string, "record_id": "UUID",
  "field_name": string }] }` (1–100 items).
- **Response:** `{ confirmed_count, confirmed_at }`.
- **Errors:** `404` when an item does not exist for the current Candidate; validation errors.
- **Lifecycle:** appends `candidate_confirmed` lineage with the same value hash. It does not erase
  Admin/CV history or replace `source_verified`.
- **Refetch:** Candidate profile/Career detail and outstanding-confirmation count.

## 5. Admin organization provisioning

### Create organization

- **Method/path:** `POST /admin/operations/organizations`
- **Permission:** `create_organization`
- **Request:** `{ name, organization_type, website?, industry?, location?, work_email?, domain?,
  organization_size?, idempotency_key }` using existing organization enum values.
- **Response (`201`):** `{ organization_public_id, name, organization_type,
  lifecycle_state: "awaiting_first_hr_claim", verification_state, setup_completed: false,
  owner_membership_present: false, created_at }`.
- **Errors:** `organization_name_exists`, `primary_hr_invitation_exists`, or input/auth errors.
- **Lifecycle:** exact normalized-name duplicates are rejected. Creation makes no owner/member,
  does not imply verified ownership, and records `admin_organization_created`.
- **Refetch:** Admin organization list/detail and provisioning workflow.

## 6. First-HR secure activation

### Invite first HR owner

- **Method/path:** `POST /admin/operations/organizations/{org_public_id}/first-hr-invitations`
- **Permission:** `invite_first_hr`
- **Request:** `{ "full_name": string, "email": Email, "role": "owner" }`. `owner` is the only
  accepted initial role and cannot be escalated by arbitrary client input.
- **Response (`201`):** `{ invitation_public_id, organization_public_id, invitee_email_masked,
  role: "owner", status, expires_at, last_sent_at,
  acceptance_path: "/team-invitations/accept?token={opaque_token}" }`.
- **Errors:** pending invitation conflicts, an already-owned/member organization, missing
  Admin-provisioned organization, or truthful email delivery failure.
- **Lifecycle:** reuses the certified HR V2 Team Invitation hash/expiry/email infrastructure. No HR
  password is accepted, created, returned, or emailed. The production email route is exactly
  `https://hr.kairoid.com/team-invitations/accept?token={opaque_token}`.
- **Refetch:** provisioning detail/invitation status.

### Resend first HR

- **Method/path:** `POST /admin/operations/organizations/{org_public_id}/first-hr-invitations/{invitation_public_id}/resend`
- **Permission:** `invite_first_hr`
- **Request:** the same name/email/`owner` body; email cannot change on resend.
- **Response:** first-HR invitation response.
- **Errors:** missing/non-pending invitation, email mismatch, or existing membership.
- **Lifecycle:** the certified Team Invitation rotation increments version and invalidates the old
  token.
- **Refetch:** provisioning detail/invitation status.

### Existing HR acceptance APIs

- Public preview: `GET /workspace/team-invitations/{token}`.
- Authenticated accept: `POST /workspace/team-invitations/{token}/accept`.
- The accepting account's normalized email must match. Acceptance atomically consumes the token,
  creates the deliberate owner membership, and selects the active organization.
- After acceptance, refetch `/workspace/bootstrap` and Admin provisioning state.

## 7. Court/private evidence upload

- **Upload intent:** `POST /admin/operations/candidates/{candidate_id}/evidence/upload-intent`.
- **Complete:** `POST /admin/operations/candidates/{candidate_id}/evidence/{document_id}/complete-upload`.
- **Permission:** `manage_court_check`.
- **Contracts:** existing `UserDocumentUploadIntentRequest/Response` and
  `UserDocumentCompleteUploadRequest`/`UserDocumentResponse` are reused.
- **Validation:** PDF, JPEG, PNG, or WebP; positive size up to 50 MiB; safe filename; completed
  SHA-256 checksum. The managed Candidate owns the private evidence row.
- **Errors:** unmanaged Candidate, invalid MIME/size/name/checksum, unavailable storage, or
  cross-owner document.
- **Refetch:** retain only returned `document_id` for court/in-person payload association. Do not
  persist the presigned URL client-side after upload.

## 8. Structured court-record result

### Create/start

- **Method/path:** `POST /admin/operations/organizations/{org_public_id}/people/{person_public_id}/court-checks`
- **Permission:** `manage_court_check`
- **Request:**

  ```json
  {
    "status": "pending | no_match_found | match_found | review_required | unable_to_complete",
    "searched_at": "ISO-8601 or null",
    "jurisdiction": "Delhi District Courts",
    "coverage": "Publicly accessible indexed records",
    "search_period": "2016-2026",
    "source": "named court index/source",
    "finding": "required for match/review_required",
    "remarks": "optional",
    "limitations": "required scope limitations",
    "evidence_document_ids": ["UUID"],
    "idempotency_key": "UUID"
  }
  ```

- **Response (`201`):** all structured fields plus `public_id`, organization/person IDs,
  `reviewer_user_id`, evidence IDs, `finalized_at`, timestamps, and the semantic notice that
  no-match is not police verification or criminal clearance.
- **Errors:** invalid organization/person association, invalid/cross-owner/incomplete evidence,
  missing searched date for a result, missing finding, or idempotency conflict.
- **Refetch:** court-check list/detail and the HR Verification Report.

### Update

- **Method/path:** `PATCH /admin/operations/organizations/{org_public_id}/people/{person_public_id}/court-checks/{check_public_id}`
- **Permission:** `manage_court_check`
- **Request:** any mutable structured field above except idempotency key. New evidence IDs append;
  public projections contain IDs, never storage URLs.
- **Response:** Court response above.
- **Errors:** `court_check_finalized`, scope/validation/evidence errors, or `404` for cross-person or
  cross-organization access.
- **Refetch:** court detail/list and Verification Report.

### Finalize

- **Method/path:** `POST /admin/operations/organizations/{org_public_id}/people/{person_public_id}/court-checks/{check_public_id}/finalize`
- **Permission:** `manage_court_check`
- **Request:** no body.
- **Response:** finalized Court response; repeating finalize is idempotent.
- **Errors:** `court_check_result_required` for pending, missing searched date, or scoped `404`.
- **Lifecycle/report:** finalized rows are immutable. The existing
  `GET /organizations/{org_public_id}/people/{person_public_id}/verification-report` automatically
  replaces `NOT_ORDERED` with the truthful status and preserves source, scope, search period/date,
  finding, first evidence ID, reviewer, remarks, and limitations. `no_match_found` displays only
  “No match found within the stated court-record scope”; it never says “cleared.”
- **Refetch:** court detail/list and Verification Report after every mutation, especially finalize.

## 9. Generalized in-person observation

- **Method/path:** `POST /admin/operations/organizations/{org_public_id}/people/{person_public_id}/in-person-verifications`
- **Permission:** `perform_in_person_verification`
- **Request:** `{ verification_type: "identity_observation" | "document_observation",
  performed_at, person_met?, relationship?, result: "observed_consistent" | "discrepancy" |
  "unable_to_complete", notes?, evidence_document_ids: UUID[], idempotency_key: UUID }`.
- **Response (`201`):** persisted fields plus `public_id`, `performed_by_user_id`,
  `method: "in_person"`, `changes_canonical_verification_status: false`,
  `permanent_address_check_credit: 0`, and `created_at`.
- **Errors:** unsupported verification type, invalid/cross-owner evidence, cross-org/person scope,
  or idempotency conflict.
- **Lifecycle:** this is an auditable observation, never a generic “mark verified.” It does not
  confirm employment, education, identity, or a document in their canonical state machines.
  Permanent Address is intentionally unsupported and receives zero Check1/2/3 credit; its existing
  approved-document plus three server-day checks policy is unchanged.
- **Refetch:** in-person activity/history only. Do not optimistically change any verification badge,
  Permanent Address progress, Trust Score, or report check status.

## Frontend cache/invalidation summary

| Mutation | Invalidate/refetch |
|---|---|
| Candidate create | Admin Candidate/People list; Candidate status |
| Activation send/resend | Candidate status and activation timers |
| Candidate claim | Candidate session/sign-in state; Admin status on next view |
| Profile/Career/CV import | Candidate profile, affected Career collection, provenance review |
| Organization create | Admin organization list/detail; provisioning state |
| First-HR send/resend/accept | provisioning state; invitation; after accept HR workspace bootstrap |
| Evidence upload complete | local evidence attachment state only |
| Court create/update/finalize | Court list/detail and HR Verification Report |
| In-person record | observation activity/history only; no canonical verification cache |
