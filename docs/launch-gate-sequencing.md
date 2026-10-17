# Three-feature launch gate sequencing

Schema remains 091. This contract authorizes no deployment, provider call or
operator execution by itself.

## Existing gates and resolution

- `DigiLockerService._enabled` and `_read_context` require base DigiLocker and an
  active, unexpired, consent-valid, owner-bound encrypted connection.
- `DigiLockerEAadhaarService._aadhaar_enabled` still gates Candidate availability
  and verification on e-Aadhaar enabled and Production entitlement certified.
- The operator-only `app.ops.digilocker_aadhaar_entitlement_check` accepts only
  Production State B, with base DigiLocker ON and both e-Aadhaar flags OFF. It is
  not registered as an HTTP route. Invocation requires authorized host/task access
  to the existing runtime DB/keyring, not Candidate API authentication.
- `PermanentAddressService.state` retains the Candidate OFF response.
  `admin_state` reuses canonical state projection under persisted Admin permission
  checks. `admin_read_actor` is separate from feature-gated `manual_actor`.
- Admin discovery/detail, manual-review read projections and document metadata
  projections can run before activation. Mutation paths and protected document
  content still require Address ON. Readiness is not permission to test decisions.

## Operator entitlement command

The operator must record a single-use approval in the operational ledger binding
the exact Candidate UUID, existing connection UUID, Candidate's explicit e-Aadhaar
consent v1 and one invocation. UUIDs are internal identifiers, not email or Aadhaar.
Do not reuse an approval after a failed, timed-out or interrupted invocation.
The CLI does not introduce a durable approval/entitlement table; the operator
ledger is the execution-budget control. No automatic retries or resubmission.

```sh
python -m app.ops.digilocker_aadhaar_entitlement_check \
  --execute \
  --candidate-id APPROVED_CANDIDATE_UUID \
  --connection-id EXISTING_CONNECTION_UUID \
  --approval-id OPERATOR_APPROVAL_UUID \
  --consent-confirmed --consent-version v1
```

These placeholders are not executable account selections. Never pass email,
Client Secret, access token, Aadhaar, code, state or verifier on the command line.
The consent flag is an operator attestation to actual Candidate consent, not a
substitute for obtaining it. Do not expose this command through an HTTP route,
scheduled job or Candidate-controlled execution environment.

The command uses canonical owner locking, connection expiry/consent validation and
token decryption. It does not create OAuth, refresh, revoke or retrieve other
documents. It calls User Details exactly once; only Y permits one e-Aadhaar fetch.
The common verification path checks HMAC before bounded hardened XML parsing and
commits the existing minimized consent/provenance row only after validation. No
raw Aadhaar, photo, XML or address is persisted. Identity mismatch is retained as
truthful derived provenance, not falsely converted to Verified. Entitlement
confirmation means authorized retrieval/integrity/parse/persistence succeeded,
not that identity matching necessarily succeeded.

Output is fixed safe outcome metadata only. No account/connection UUID is printed.
Application/HTTP/SQL logger output is suppressed for this isolated CLI process;
SQL echo must be disabled. Unexpected failures do not print exception details.
Interrupted/unknown persistence is reported as null, never permission to retry.

| Outcome | Meaning and required action |
|---|---|
| ENTITLEMENT_CONFIRMED | 200, integrity/parser/minimization/persistence succeeded; retain evidence for later explicit flag change |
| ENTITLEMENT_DENIED | 403/access denial; keep e-Aadhaar OFF, no retry |
| ACCOUNT_NOT_LINKED | User Details N or XML404; not evidence of requester entitlement denial |
| ACCOUNT_UNAVAILABLE | User Details404; do not infer requester entitlement |
| CONTROLLED_SESSION_RECONNECT_REQUIRED | Expired/unavailable stored connection or provider401; no automatic reconnect |
| PROVIDER_TEMPORARY_FAILURE | Provider500/503/transport failure; no automatic retry |
| SECURITY_FAILURE | HMAC/integrity failure; stop |
| PROVIDER_RESPONSE_INVALID | Unsupported/unsafe/invalid response; stop |
| CONTROLLED_ACCOUNT_REFUSED | Ownership, exact connection or other controlled-input refusal; no provider retry |
| CERTIFICATION_FAILED / CERTIFICATION_REFUSED_OR_INTERRUPTED | Stop; inspect authorized safe state before any new approval |

Success returns exit0; all other terminal outcomes exit2. No flag is flipped.
Candidate e-Aadhaar remains OFF after success. The operator evidence supports a
later explicit deployment mutation to enable e-Aadhaar and certify entitlement.
Do not call availability first: this command already performs the one User Details
call, and Candidate verify would repeat it. The launch ledger counts the command's
User Details as the base/entitlement User Details proof for the same session.

## Admin pre-activation reads

Authenticated active email-verified Admin/Superadmin with canonical
REVIEW_VERIFICATION permission is required even while Address OFF. No Candidate,
HR, Institution, unknown account or self-review access is introduced. Discovery
and candidate detail retain the existing database-enforced read-only repeatable
snapshot. No response shape changes or new feature metadata fields were added.

Historical progress, document state and manual-review state are projected without
creating records or decrypting targets. Empty data returns an empty queue or
NOT_STARTED detail. No Places/S3 operation is performed. Existing privacy allowlists
remain intact. While OFF, approval eligibility and content preview availability
are false; all decision/upload/location mutation gates remain enforced.

## Revised rollout dependency order

DB074 -> 075 -> COMMIT/CLOSE -> fresh091; activate deletion operations; new pinned
worker and API State A; Company360; exact Admin deployment and read-only Address
readiness while OFF; State B; one controlled OAuth and base PAN/DL gate; one
operator command covering User Details and e-Aadhaar entitlement while OFF; State C
only after confirmed evidence; recheck Admin Address reads while OFF; State D;
full smoke; reopen; 60-minute watch.

Source certification closes sequencing, not infrastructure repinning or live
entitlement. New source requires new digest-pinned API/worker/reconciliation/
migrator definitions under a separate approval. Do not deploy superseded pins.
No migration beyond091, new IAM, secret, operator task, provider call or GPS is
authorized by this document. A future operator task must be separately approved,
use the final State-B API runtime credentials/config, and run once without a
service update, listener, OAuth or retry. No new access path is implied.
