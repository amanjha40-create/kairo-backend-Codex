# Passport Sharing Policy V2

No migration. The Alembic head remains 077. Owner Passport and owner PDF are unchanged.

## Authenticated contract

- `GET /api/v1/passport-shares/capabilities` advertises policy version, modes,
  eligible section keys, derived-score support and narrow-only updates.
- `POST /api/v1/passport-shares` requires `label` (trimmed, 1-120 characters).
  `sharing_mode` is `verified_only` by default or explicitly
  `verified_and_candidate_provided`. Legacy mode is not a create option.
- Default V2 permissions enable only `include_employments`, `include_educations`
  and `show_employer_names`. Mixed mode enables no record categories implicitly.
- Responses include `policy_version` (1 or 2), `sharing_mode` and resolved
  `permissions`. The secret recipient URL remains create-response-only.
- `PATCH /api/v1/passport-shares/{id}` accepts partial permissions. Omitted
  fields remain unchanged. Explicit null booleans and blank purposes are 422;
  null purpose is also 422 for V2. Existing legacy null labels remain readable.
- Existing links may only narrow disclosure. Enabling a previously hidden field
  or changing verified-only to mixed returns 409 and requires a new link.
  Owner-scoped row locks serialize concurrent edits and revocation.

## Disclosure

V2 snapshots use a strict boolean `verified_only` marker in the existing JSONB.
An absent marker resolves with frozen legacy defaults (`legacy_mixed`, version 1).
Malformed marked snapshots fail closed, without a fallback to legacy.

Only Employment and Education with authoritative `verification_status=verified`
qualify for verified-only. No `approved` exception. Mixed mode can explicitly
select Employment, Education, Certifications, Skills, Projects and Documents.
Portfolio, Internship, Freelance and Gig remain legacy-only. Record query filters
precede document projection and serialization. Unsupported verification claims on
Candidate-provided categories are normalized only in the public projection.

`include_profile` and `show_photo` are mixed-only. Photo requires Profile.
Hidden headline/location/slug/avatar are null. Owner name is attribution, not a
verified identity claim. Email and phone are never in the public DTO.

`show_documents` governs attached document metadata. `include_user_documents`
also requires `show_documents`. Attachments never qualify a parent as verified.
Storage URLs are not projected. Opted-in photos use the token-checked, no-store
`GET /api/v1/public/passport/{token}/photo` endpoint, not an S3 redirect.

Trust Score is off by default and explicitly disclosed as an account-wide derived
aggregate, not recalculated for selected sections. Public projection allowlists
overall, status, score_version, last_calculated_at and completeness percentage;
no contributors, domain details, overrides or manual-review details.

## Client integration (Android and future iOS)

Require confirmed capabilities before creating V2 shares. Reset optional selections
when switching modes; mixed categories require explicit opt-in. Photo is disabled
until Profile is selected. Review exact selections and exclusions before creating.
Label legacy history `Legacy sharing policy`; never present it as verified-only.
Do not provide expansion editing on existing links. Copy, QR, native Share and
Preview must all use the unmodified create-response recipient URL.

Public consumers must use the filtered public endpoint, not owner Passport/PDF.
Expired, revoked, unknown or malformed-policy links remain neutral 404 responses.
Do not log recipient credentials. No iOS source changes are included here.

## Rollout safeguard

The pre-V2 task is a rollback checkpoint only before any V2 row is created.
Its permission DTO does not understand V2 snapshots. Once V2 shares exist,
including revoked shares, use a V2-compatible rollback image or a forward fix;
do not silently reinterpret or rewrite those snapshots as legacy policy.
