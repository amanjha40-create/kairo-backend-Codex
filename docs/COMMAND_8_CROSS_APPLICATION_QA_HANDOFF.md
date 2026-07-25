# Command 8 Cross-Application QA Handoff

## Status

Command 8 candidate-side engineering is complete and deployed to staging.

Certification status: **Command 8 — Engineering Complete — Pending Cross-Application QA**

Validated candidate-side work includes verification request grouping and filters, request acceptance, information-response persistence, ownership and state validation, idempotent submission, timeline events, the private Document Vault, presigned uploads, signed viewing, safe deletion, Vault evidence linking, in-request evidence upload, idempotent evidence retry, document replacement metadata/version history, consent persistence, and candidate-visible rejection/expiry guidance.

## Deferred Scenarios

These scenarios require a controlled HR/Admin actor and are deferred to the HR Workspace/platform integration phase:

- HR/Admin completes a verification.
- HR/Admin rejects a verification.
- HR/Admin triggers expiry or reverification.
- Candidate confirms Home, Career, Verify, Passport, and timeline refreshes after each outcome.
- Candidate validates document replacement UI end-to-end.
- Candidate removes evidence before final submission.

These are integration QA dependencies, not current candidate-side implementation blockers.

## Test Prerequisites

- Staging API is healthy; production is not used.
- One dedicated staging candidate account with an authenticated Xiaomi Android session.
- One staging HR organization and authorized HR user with access to the verification workspace.
- One staging Admin user with the required review permissions.
- A candidate employment record and verification contact/request linked to the candidate.
- Synthetic PDF or image evidence documents only. Do not upload sensitive real documents.
- No secrets, passwords, access tokens, signed URLs, or production data in test notes.

## Required Request States

Prepare requests covering:

- `pending_subject_acceptance`
- `awaiting_information`
- `accepted`
- `in_progress`
- `verified`
- `rejected`
- `expired`, when supported by the active workflow

## Execution Order

1. Candidate opens a pending request and reviews the organization, claim, requested fields, evidence scope, purpose, and consent summary.
2. Candidate accepts once; verify one acceptance event and no duplicate event on replay.
3. HR/Admin requests information with a candidate-visible explanation and deadline where available.
4. Candidate opens the request, enters a response, selects or uploads synthetic evidence, removes/replaces evidence where supported, and submits.
5. Confirm the server response, evidence association, timeline event, and status transition.
6. Candidate relaunches the app and confirms response/evidence state comes from backend truth.
7. HR/Admin completes verification; candidate refreshes Verify, Home, Career, Passport, and timeline.
8. Repeat with rejection, discrepancy/insufficient-evidence, and expiry/reverification outcomes.
9. Replace a Vault document and confirm the new version is current while the previous version and evidence history remain preserved.
10. Clean all synthetic requests, documents, S3 objects, and temporary test records after acceptance.

## Expected Outcomes

- Candidate information submission: `awaiting_information -> in_progress`.
- Successful HR verification: request becomes `verified`; related candidate surfaces refresh from backend truth.
- Rejection/discrepancy: candidate sees only the candidate-visible reason and next-step guidance; internal notes remain hidden.
- Expiry: expired request/document remains in history, is not shown as currently valid, and offers renewal/replacement guidance only when supported.
- No candidate action can set `verified`, change organization ownership, or access another user’s document.

## Security and Runtime Checks

- Candidate ownership is enforced for requests, responses, and documents.
- Duplicate submissions and duplicate evidence links are idempotent or rejected safely.
- Signed URLs are short-lived and absent from logs.
- No OTPs, tokens, passwords, resume/document contents, prompts, model output, or PII appear in logs or reports.
- Monitor Android logcat and staging logs for React/JavaScript errors, fatal Android exceptions, HTTP 5xx responses, stale query data, and unauthorized transitions.
- Confirm production remains on `kairo-backend:2` throughout testing.

## Pass/Fail Criteria

Pass only when every deferred scenario completes on the physical Xiaomi device and the backend, candidate surfaces, timeline, privacy boundaries, and cleanup checks match the expected outcomes above. Any missing HR/Admin actor, unavailable transition, stale refresh, private-data leak, duplicate event, or unclean synthetic artifact is a fail for that scenario and must remain documented as pending.

## Certification Wording

Until the deferred HR/Admin-driven scenarios pass, use exactly:

**Command 8 — Engineering Complete — Pending Cross-Application QA**

