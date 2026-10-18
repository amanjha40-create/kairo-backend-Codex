# Integrated Release Handoff: HOLD

This is an integration candidate, not authorization to deploy. The founder chose
to retain frozen frontend SHAs and report the HR court-detail blocker. Do not
label the entire release certified or push under the conditional post-certification
approval while blockers remain.

## Frozen Inputs

| Consumer | Frozen source | Disposition |
| --- | --- | --- |
| HR | 8ce365ef84372a35967648d269c696c3f8f3213e | BLOCKED: court summary/detail key mismatch |
| Admin | d7f93efd2f61f1c253739b9da65fd793c106d5d2 | Existing contracts preserved; new read adapters absent |
| Android | 045ed450c14fe2cd6b84f3fed88220159bf7a2aa | Existing OpenAPI preserved; activation UI is a future dependency |

All frozen worktrees remain untouched. Integration source is on
`codex/backend-integrated-v1-1-hr-admin`, derived from Admin `aec4a41d` plus
V1.1 `598929b8` and `43c46837`. Exact artifact provenance, when built, belongs
in the external immutable-SHA evidence manifest, not a self-referential commit.

## Confirmed Frontend Blocker

HR `src/lib/verification-report.ts`, `getCheckDetails`, only dispatches court
details for `court_search`. The backend's canonical check summary uses
`court_record_search`; the detail array is named `court_search`. Consequently
the summary key does not select the court fields/evidence/notes. Do not rename
the backend key to conceal this frozen-consumer mismatch. A separately approved
frontend adapter and regression test, with a new HR SHA, are required.

## Admin Read Contracts

New GET operations provide organization/person-scoped paginated court and
in-person receipts, exact receipt details, masked first-HR provisioning state,
and an authorized internal Admin verification report. They do not create events,
send notifications, presign files, mutate status, or grant Permanent Address credit.

The frozen Admin frontend has no adapters for those reads. Receipts still live
in component state, the initial first-HR invitation state is not rehydrated, and
the structured report has no direct Admin renderer. Backend read closure must
not be reported as completed frontend refresh behavior. A masked first-HR status
does not eliminate the existing explicit recipient-input requirement for resend.

## Additional Audit Holds

- Structured HR reference projection reads legacy `name`, `title`, `strengths`
  and `comments` keys, whereas current manager records store `full_name`,
  `designation`, `key_strength` and `additional_comments`. The existing internal
  Admin reference report retains full answers; the structured HR report does not
  faithfully project all current manager fields. No external comment exposure was
  found. Mapping/current-history policy needs correction and specific tests.
- Report finality is derived from generic requests and court checks, not outstanding
  reference/address items. Pending reference/address summaries can coexist with
  FINAL. Product truth requires a defined completion/open-items policy and tests.
- Team acceptance and resend/cancel read capability state without a common row-lock
  protocol. Sequential replay tests pass, but concurrent accept/rotate/revoke safety
  is not certified. Establish consistent lock order, including Admin first-HR
  organization locking, and race-test before release; do not apply isolated locks
  that introduce an organization/invitation deadlock.
- Verification preferences preserve an address flag and reference count, but current
  invitation type mapping omits address and reference count is not an execution
  policy. Explicit empty requested types also fall back to defaults. Resolve the
  intended orchestration semantics rather than invent a new verification pipeline.
- Existing V1.1 deferred D01-D10 remain as documented in the core API audit,
  including verified-claim edits, correction history and incomplete resume DTOs.

## Product Dependencies

`BACKEND_PASSPORT_RECORD_LEVEL_SHARING_REQUIRED`: existing sharing permissions
select whole sections/categories, not individual Employment record IDs. Public
slug projection is a separate surface. Do not promise per-job exclusion or add
an unreviewed schema redesign here.

Push delivery is not end-to-end: no Candidate device registration/token lifecycle
or push delivery implementation, no Android push registration, and no dedicated
invitation destination in its notification router. Existing email invitation and
HTTPS deep-link support do not constitute push delivery. No real push was sent.

Candidate signup/reset/change and assisted claim use 12-128 characters, without
composition rules. Claim normalization was aligned with existing login's trimming
to avoid creating unusable credentials; no existing hashes are rewritten. Android
does not trim consistently. First-HR acceptance uses a normal authenticated account;
new recipients use ordinary signup. Separate Admin staff invitation policy remains
8-255 and needs coordinated review against login's maximum. Stronger password policy
requires a shared versioned backend/client decision, not Android-only validation.

## Conditional Promotion Order (NOT EXECUTED)

1. Resolve release holds and certify exact final backend/HR/Admin/Android contracts.
2. Obtain rollout approval; publish the exact certified ARM64 artifact.
3. Prepare digest-pinned API, Worker and dedicated migrator definitions.
4. Confirm live DB/source anew; snapshot DB091 and control writers/maintenance.
5. Migrate 091 to 092; prove exactly one head092 and preserved data.
6. Migrate 092 to 093; prove exactly one head093 and preserved data.
7. Deploy compatible Worker, then API, without older-binary revival.
8. Certify backend authentication, authorization and health smoke checks.
9. Deploy corrected certified HR; perform authenticated HR smoke.
10. Deploy certified Admin adapters; perform authenticated Admin smoke.
11. With separate recipient/budget approval, send one controlled Team email and
    one Candidate activation email. No automatic resends.
12. Perform separately approved Court/in-person smoke with synthetic evidence,
    preserving canonical verification and Permanent Address rules.
13. Observe traffic/health and record rollback constraints. Do not downgrade schema
    or revive incompatible pre-092/093 binaries without a reviewed recovery plan.

No Production deployment, DB access, ECR publication, AWS runtime change, real
email/SMS/push, provider/geocoder call, or GPS collection occurred in this task.
