# Backend V1.1 Core API Audit

## Scope and Baseline

Source-only audit dated 2026-10-18. Fresh read-only ECS service/task-definition
inspection resolved API37 to `473811f410b3918a4febd7dbc4fdaf20a8584893`, not a new
source revision. API37 and Worker12 were each desired/running/pending 1/1/0.
The deployed image reference was
`sha256:427d2612b6d98b5d3e1bd0dc588d09170cdb420c9a5e4f8d75a7bb4f3b345801`.
No Production DB access was performed; the source migration head is 091.

Worktree: `/Users/Aman/Desktop/work/kairo-backend-v1-1`.
Branch: `codex/backend-v1-1-hardening`.
Production operational and HR V2 worktrees were not edited. HR V2 already had
independent uncommitted work and migration 092; none was imported or modified.
No AWS writes, deployment, real provider requests, email/SMS or GPS occurred.

The exact route inventory is `backend-v1-1-api-inventory.md` (481 method/path
entries, including adjacent routes to make boundaries visible). The searchable
keyword occurrence ledger is `backend-v1-1-keyword-inventory.csv`. Inventory
generation imports code offline; it does not call those routes.

## Findings and Disposition

Severity describes risk; disposition separately describes whether a change fits
the authorized backwards-compatible batch. No P0 was confirmed. Source evidence
does not establish exploitation or presence of affected Production records.

| ID / Area | Finding / prior behavior | Severity | Expected / disposition | Fixed? | Web/mobile impact and follow-up |
| --- | --- | --- | --- | --- | --- |
| F01 Profile | Clearing phone retained its verification timestamp | P1 | Normalize clear to null; invalidate phone verification | Yes | Refresh onboarding/contact truth; no DTO change |
| F02 Lists | Date-only/naive bounds compared to UTC timestamps raised TypeError | P1 | Normalize comparison boundaries to UTC, date-before includes entire day | Yes | Existing filters stop returning 500 |
| F03 Sessions | Concurrent refresh consumers could rotate the same token | P1 | Lock token row and reload state before consumption | Yes | Serialize refresh client-side; duplicate replay remains invalid |
| F04 Signup | Restart reused old bearer signup ID and OAuth metadata | P1 | Rotate opaque capability, clear verified/provider identity intent | Yes | Always persist the latest start response ID |
| F05 Signup | Completed signup ID minted new sessions; collision adopted an existing user | P1 | Completion is one-shot; existing-account collision fails closed | Yes | Lost completion response requires normal sign-in, not indefinite replay |
| F06 Password reset | Reset token read/consume was not serialized | P1 | Lock one-time token until password/reset/revocation transaction completes | Yes | No shape change; repeated use fails |
| F07 Evidence | Organization evidence list bypassed consent filter used by detail | P1 | Apply same filter before metadata/URL serialization | Yes | Fewer unconsented items is deliberate authorization enforcement |
| F08 Public Vault | Address-proof metadata was public, including historical proofs | P1 | Reuse existing current/historical address privacy predicate | Yes | Private proofs absent; no file URL exposed |
| F09 Connector | Seeded mock implementation available in Production | P1 | Do not register synthetic verification implementation in Production | Yes | No fabricated connector result; missing real connector fails closed |
| F10 Identity truth | Expired/superseded approved manual evidence still counted | P1 | Only current, unexpired manual evidence supplies identity trust | Yes | Historical records retained; no weight change or extra source points |
| F11 Public Passport/account | Inactive-owner link could resolve; suspension enumeration raced issuance | P1 | Public active-owner guard; serialize suspension/restoration on owner | Yes | Generic 404 for unavailable owner; restoration cannot revive revoked link |
| F12 Dashboard | Share analytics issued two queries per share | P1 | Owner-scoped grouped counts, constant two queries per summary | Yes | Same response and counts, including zero-view shares |
| F13 Lists | Forced legacy envelope applied input size limit to whole list | P1 | Preserve all legacy items without invalid PageParams construction | Yes | Explicit pagination still bounded; no silent truncation |
| D01 Career | Education/internship/freelance edits can retain old verified status | P1 risk / PRODUCT_DECISION | Decide immutable verified claims versus new unverified revision | No | Coordinated edit/reverification UX required; no historical rewrite |
| D02 Employment | Active request and canonical employment status can diverge, permitting mid-review edits | P1 risk / PRODUCT_DECISION | Define correction window and snapshot/current-claim finalization policy | No | Coordinate with HR V2 owner before shared workflow changes |
| D03 Resume reads | Imported incomplete career fields conflict with non-null response contracts | P1 risk / PRODUCT_DECISION | Nullable DTO version/client support or explicit incomplete-record projection | No | Do not fabricate dates/names or silently hide imported records |
| D04 Corrections | Resubmit retains old claim snapshot | P1 risk / PRODUCT_DECISION | Agree preservation/versioning of original and corrected claims before replacing snapshots | No | Existing event JSON may suffice; no proven schema dependency or migration authorized |
| D05 Clarification | Second clarification round hits prior submitted timestamp | P1 risk / PRODUCT_DECISION | Agree response-history contract with round-scoped duplicate protection | No | Avoid overwriting prior response; investigate existing event history before any schema proposal |
| D06 Profile analytics | Recruiters is known-viewer proxy; companies is constant zero | P2 / PRODUCT_DECISION | Define real actor/company attribution or remove unsupported UI claim | No | Do not label proxies as measured recruiter/company activity |
| D07 Confidence | Uncalibrated confidence is null; preparation scaffolding exists | P2 / PRODUCT_DECISION | Keep honest unavailable state until calibrated implementation exists | No | Do not present null as an AI score or infer successful OCR |
| D08 Extraction worker | Legacy extraction handler emits empty payload/completed audit; current uploads skip extraction | P2 / PRODUCT_DECISION | Decide removal or explicit unsupported-job outcome with legacy producer audit | No | No current normal-path producer found; not real OCR |
| D09 Notifications | Security/login/password notifications not implemented as inbox producers | P2 / NEW_FEATURE | Define events, dedupe and delivery policy separately | No | Do not promise unsupported inbox/security events |
| D10 Completion analytics | Score completeness is evidence availability, not full profile completeness | P2 / PRODUCT_DECISION | Clarify product label/denominator | No | Do not interpret 100% as every Career section completed |

Counts: 0 P0; 13 implemented P1 hardening findings; 5 additional P1-risk findings
held behind product/contract/history decisions; 5 P2 findings. Dispositions are
9 PRODUCT_DECISION, 0 proven SCHEMA_DEPENDENCY, 1 NEW_FEATURE. These unresolved findings
remain visible risks, not certified as fixed and not a blanket promotion approval.

## Contract and Area Review

- Auth: password/email/mobile normal login requirements retained. Existing-account
  mobile-binding recovery is unchanged. OTP expiry, attempt limit, cooldown and
  destination checks remain enforced. No bypass account or OTP was used.
- Onboarding: email/phone truth and explicit onboarding completion drive state.
  Profile incompleteness is distinct from authenticated Home access; no new
  mandatory field or client redirect rule was introduced.
- Profile: PATCH omitted fields remain unchanged; explicit phone clearing now
  removes stale verification. Name/DOB/profile revision continues to invalidate
  mismatched DigiLocker identity truth through existing rules.
- Career: owner-scoped CRUD, soft deletion, dates, document associations and
  existing primary/supporting/legacy-null semantics reviewed. No automatic
  backfill, category inference, imported-record rewrite or HR V2 model edits.
- Documents: owner checks, upload MIME/size/completion and object-version binding
  remain; no storage or download URL was generated against real infrastructure.
  Address-proof exclusion now also covers the legacy public Vault route.
- Verify: subject/organization access, terminal transitions, stale review version,
  certificate replay, evidence ownership and consent were reviewed. Consent-filter
  repair applies before presigning; D01-D05 are explicit remaining workflow risks.
- Passport: token hashing, expiry, revocation, narrowing permissions and recipient
  allowlists retained. JSON/photo resolution now checks active/nondeleted owner.
  Public projections still exclude private notes and source identifiers.
- Home: stored/current calculations retained, no fictional new counters added.
  Share counts are aggregated without cross-owner leakage. D06/D10 qualify labels.
- Notifications: existing completion/admin-review/trust-safety producers retained;
  list/read/unread/read-all are owner scoped. Email-only invitations are not falsely
  presented as existing user inbox notifications. No delivery was exercised live.
- Settings/sessions: refresh-family revocation and current-session metadata remain.
  Sessions represent token families/rows, not a guaranteed inventory of physical
  devices; updated_at is not a device last-seen heartbeat. No raw refresh token
  appears in the session projection.
- Authorization: focused regressions plus existing local suites cover other-owner
  career, documents, requests, shares, notifications, address and DigiLocker state.
  Subagent source assertions alone are not counted as HTTP/database proof.
- Errors: existing application exception envelopes and normal 404/409/422 behavior
  retained. No global status-code rewrite, route rename or ID-format change.
- Pagination: explicit limit/page behavior retained; legacy list/envelope behavior
  preserved. UTC comparison repair does not alter stored timestamps.

## Trust Score: Existing v2 Algorithm

Weights remain Identity 25%, Employment 45%, Education 30%.
Identity numerator: authoritative identity 40 + verified phone 15 + verified email
15, divided by 70. Multiple verified sources never stack identity points.
Employment averages 80 for approved/verified, 0 for rejected/cancelled, 7.5 for
other states. Education averages 70 for approved/verified, 0 for rejected/cancelled,
17.5 otherwise. Missing Career categories contribute zero. Weighted output is
rounded by the existing implementation; maximum under these defaults is 82.
Consent gates calculation; withdrawal preserves historical snapshots.

No standalone score boost for e-Aadhaar, Permanent Address/GPS, reference completion,
document packs, connection, listing or retrieval. Current manual evidence filtering
is a truth correction, not a weight redesign or historical snapshot rewrite.

## Integrations: Source/Mocked Tests Only

DigiLocker: authorization/code/PKCE/state, bounded routing, encrypted tokens,
consent, integrity, parser, profile-version matching, expiry and safe diagnostics
reviewed. Disconnect preserves historical verified provenance. No activation,
OAuth, refresh, revoke, entitlement probe or document retrieval was performed.

Permanent Address: approved matching document plus three successful user-initiated
checks on separate server-authoritative India-calendar days remains required within
the existing active cycle/window rules. Encrypted targets, pending manual review,
owner binding, consent and safe telemetry are retained. No threshold relaxation,
address read, geocode, GPS collection or real session occurred.

## Recommended Next Batch

Resolve D01-D05 with explicit correction/revision/history contracts and released
client handling, coordinated with HR V2. Then address truthful analytics labels,
unsupported extraction jobs and security notification policy. This source-only
certificate must not be used to claim those risks are absent or authorize rollout.
