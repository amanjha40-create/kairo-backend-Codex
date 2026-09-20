# DB-first account deletion (Phase 9C)

Local implementation based on `e0ad27b4a69dd481d64e90112a4600b084d17e6a`.
Migration 079 follows 078. No deployment or infrastructure changes are included.

## API and transaction

`DELETE /api/v1/users/me` retains the confirmation/password checks and returns 204
only after logical erasure, capability removal and the durable ledger commit.
The route obtains the target exclusively from the authenticated principal.
Candidate write authentication locks the owner before child records, serializing
uploads/share creation with deletion. Resume background processing uses the same
owner guard. Duplicate in-flight deletion is a no-op; subsequently authenticated
requests fail closed because the user is inactive/deleted and refresh families
are removed. OTP/reset DB records are removed; leftover Redis OTP entries have no
usable signup row and are also durably scheduled for cleanup.

No storage call is made by the deletion transaction. A rollback preserves the
account and leaves storage untouched. Database failures return a sanitized
retryable service error, never SQL parameters. Queue publication occurs only
after commit and cannot change the API outcome.

`requested_at` and `db_committed_at` are transaction markers persisted atomically;
they are not a second, separately committed post-commit clock measurement.

## Ledger and states

`account_deletions` holds a unique user tombstone, immutable environment/ownership
context and progress. `account_deletion_items` holds exact object identities,
owned reconciliation namespaces, Redis signup cleanup and unresolved evidence.
The unique `(deletion_id, identity_hash)` prevents duplicate work. References to
source records deliberately do not cascade away the cleanup obligation.

The internal states are `purge_pending`, `purge_partial`, `operator_review`, and
`complete`; item states are `pending`, `retry`, `review`, and `complete`. There is
no committed intermediate state where access remains enabled. An account is never
reactivated because cleanup fails. Sanitized retry categories and timestamps are
queryable in the DB; progress logs contain only status/counts/categories.

Completed object rows discard raw keys and retain only hashed tombstones. Unsafe
legacy URLs/references are not persisted as URLs and are never passed to storage.

## Inventory and policy

Inventory covers Resume originals, Vault replacement history, Employment,
Education, Internship, Freelance, Certification, Portfolio attachments, immutable
Document Pack copies/version-bound sources and canonical avatar filenames.
Resume parsing/import results are DB-owned JSON rows and are deleted in the same
transaction. Passport PDF exports are generated in memory, not persisted in S3.
Project rows have no storage-key column; Portfolio attachment bytes are included
without changing the Project/Portfolio product model.

Only canonical owner namespaces are reconciled. Organization roster-source
prefixes are never scanned. Uploaded-by identity alone does not establish
ownership of another person's career record. Candidate evidence metadata is
erased and references detached. Retained verification decisions remain behind
existing organization/admin authorization, without Candidate payloads, reviewer
free text or public outreach access. Event types/statuses/timestamps remain as
non-content tombstones. Organization-owned registry/roster facts are not blindly
deleted; Candidate links are removed.

Education historical bindings remain a separate known limitation. Missing exact
evidence bindings create `legacy_evidence_unresolved` review items. The current
Education file is never substituted as historical proof. Known owned objects are
still erased, and access is revoked regardless of ambiguity. Such requests are
not reported complete until the unresolved obligation is reviewed separately.

## Worker and recovery

`account.deletion.purge` is optional SQS acceleration carrying only a deletion
request UUID. A fresh DB session and `FOR UPDATE SKIP LOCKED` serialize duplicate
deliveries. Physical deletion is idempotent: exact-key versions and delete markers
are removed; missing objects succeed; prefix siblings cannot be deleted.

Independent sweeper:

```sh
python -m app.workers.account_deletion_sweeper
python -m app.workers.account_deletion_sweeper --execute
```

The first command is aggregate read-only status. The second processes one bounded
due request. A periodic independently supervised schedule is **mandatory** for
rollout, including when the queue is empty/down. Scheduling and live execution
require separate Phase 9D approval. An early queue delivery may be acknowledged
before cleanup is due; recovery must never depend on another queue delivery.

New namespace discoveries are committed before a later sweep deletes their bytes.
A crash after storage deletion but before bookkeeping commit repeats a safe
missing-object deletion. Successful objects stay complete during partial failure;
transient failures back off to at most one hour. Permission/configuration failures
remain in operator review, not silently marked successful. Review resolution must
not guess object identities or broaden namespaces.

Existing presigned PUTs cannot be cryptographically revoked by a DB write. Initial
purge waits for the larger of the configured PUT TTL and the existing 900-second
Certification TTL. Hourly reconciliation of proven owner namespaces continues
after completion to catch late-finishing PUTs. This is technical capability
quiescence, not an invented legal retention period. No new recipient capability is
issued by cleanup. Previously issued external URLs remain subject to their own
expiry; Kairo-authenticated and Passport/Pack access are checked against DB state.

## Migration and release gates

Upgrade is additive. Downgrade refuses any nonempty deletion ledger so rollback
cannot discard unfinished cleanup or tombstones. Application rollback must retain
the ledger; no automated database downgrade is appropriate after use.

Before staging rollout, separately approve migration 079, exact backend SHA,
worker/sweeper scheduling, monitoring for aged pending/review rows, and narrowly
scoped storage-version list/delete permissions if absent. Preserve SQL logging
disabled for private values. Do not enable a worker with a different bucket from
the captured deletion context. No IAM change is included here.

No Android/iOS source or rebuild is required by this compatible API change.
After staging approval, repin the backend in the mobile RC matrix and rerun
deletion/session/Passport/Document Pack physical QA using disposable accounts.

## Local qualification

September 20, 2026: full backend regression **1,268 passed**, no failures/skips,
18 deprecation warnings. Focused selection **209 passed**: deletion/workflow 44,
auth/session 40, Passport/share 85, Document Pack/source matrix 40. The 33 new
workflow tests include storage, queue, sweeper, rollback, concurrency, legacy
Education and cross-user safety; these counts overlap the deletion total.

Local PostgreSQL 16 only, with synthetic users/files and fake storage. The test
process used fake AWS credentials and disabled shared AWS config/credential files.
An existing host DNS stall in Python `email.utils.make_msgid` was bypassed only
in the test launcher by supplying `domain="localhost.test"`; no application email
source, transport, or assertion was weakened. Full tests passed with this narrow
test-environment substitution. The final unmodified-source test command remains
the repository's `pytest -q` when local hostname resolution is working normally.

Migration **078 -> 079 -> 078 -> 079** passed on the disposable database. The
nonempty-ledger downgrade guard also passed and preserved head 079. Exactly one
Alembic head, ORM mapper registration, compatible OpenAPI, canonical
`ruff check . --select F`, full lint on new modules, scoped formatting and
`git diff --check` passed. No staging/production database or storage was used.
