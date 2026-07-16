# Resume Review and Import Contract

Resume parsing produces candidate-provided, unverified claims. It never verifies a claim or imports it automatically. A candidate must create a review session, resolve duplicate warnings, validate an import plan, and explicitly confirm an idempotent import.

## Lifecycle

Review sessions use `draft`, `reviewing`, `ready_to_import`, `importing`, `partially_imported`, `imported`, `cancelled`, and `failed`. Item outcomes use `pending`, `edited`, `selected`, `deselected`, `invalid`, `imported`, `skipped`, and `failed`.

Optimistic `version` values are required for edits, validation, and import. Stale versions return a conflict. Import also requires a client idempotency key and `confirmed: true`.

## Endpoints

- `POST /api/v1/resumes/{resume_id}/review-session`
- `GET /api/v1/resumes/{resume_id}/review-session`
- `GET|PATCH /api/v1/resume-reviews/{review_id}`
- `PATCH /api/v1/resume-reviews/{review_id}/items/{item_id}`
- `POST /api/v1/resume-reviews/{review_id}/validate`
- `POST /api/v1/resume-reviews/{review_id}/import`
- `GET /api/v1/resume-reviews/{review_id}/import-status`
- `GET /api/v1/resume-reviews/{review_id}/imports/{batch_id}`
- `POST /api/v1/resume-reviews/{review_id}/cancel`

All routes require the authenticated owner. They expose UUID public identifiers and never return raw extracted text, provider prompts, or unvalidated model output.

## Duplicate and Import Rules

Deterministic duplicate classifications are `exact_match`, `probable_match`, `possible_match`, `no_match`, and `conflict`. Probable, possible, and conflicting matches require an explicit candidate decision. Exact matches can be linked without modifying the canonical record.

Import actions are `create_new`, `skip`, `link_existing`, and `update_existing`. Verified records and records in an active verification workflow cannot be updated. Item-level savepoints permit honest partial import results. Successful items are linked to hashed provenance containing the resume, parsed result, review session, review item, import batch, and candidate confirmation time.

Employment, education, internship, freelance, gig-platform, certification, portfolio, and conservative profile fields map to canonical models. Projects and skills remain review-only because no canonical persistence model exists yet.

Imported records retain their canonical unverified/draft state. Import does not create verification requests, trigger employer outreach, write Trust Score values, or fabricate verified Passport claims.
