# Backend V1.1 Source Certification

## Identity and Evidence Ledger

Baseline API37 source: `473811f410b3918a4febd7dbc4fdaf20a8584893`.
Isolated branch: `codex/backend-v1-1-hardening`.
Schema: 091; migrations, runtime dependencies and canonical Dockerfile unchanged.

The certified source is the commit containing this report. To avoid a circular
commit-hash/artifact-digest reference, the final machine-readable certificate lives
outside the source checkout:

`/Users/Aman/Documents/New project/artifacts/backend-v1-1/certification.json`

That certificate is generated only after all final test gates pass. It records
the exact full source SHA, local linux/arm64 image digest, archive checksum,
database/ARM64 test counts, packaged-source equality and OpenAPI equality. Absence
of that file, or a SHA different from this report's commit, means artifact
certification is incomplete. The image is local only, not published to ECR.
Normal Git push/parity evidence is recorded beside it in `source-preservation.json`.

## Changes and Regression Coverage

13 hardening findings are tracked F01-F13 in the audit. Changes cover phone clearing,
UTC list filters and legacy envelopes, one-shot/restarted signup capabilities,
stable privacy-safe OTP destination budgets, refresh/reset/revocation owner-first
locking, password login serialization, consent-filtered evidence, private address
proofs, inactive Passport owners, suspension races, current manual identity evidence,
Production mock connector exclusion and grouped share analytics.

New tests include real local PostgreSQL concurrency, stale capability rejection,
no token issuance on completed signup replay, historical proof privacy, other-owner
analytics isolation, expiry/supersession, constant query counts at 0/1/25 shares,
OTP cap preservation and explicit pagination boundaries. Existing Google lifecycle
coverage now rejects replay instead of codifying reusable signup login. Existing
Passport test doubles now implement the new active-owner lookup rather than bypass
the production guard.

## Test Procedure

Final host results: PostgreSQL 16.15 **2,727 passed**, PostgreSQL 18.3
**2,727 passed**, focused security/auth regressions **39 passed**. Both full runs
have zero failures/errors/skips and 34 existing warnings. Final ARM64 evidence is
recorded in the exact-SHA external certificate described above.

- PostgreSQL 16.15 and 18.3 are disposable local containers named `kairo-v11-pg16`
  and `kairo-v11-pg18`; Redis is also local. No HR test container is changed.
- Exact versions are checked. Each fresh database is migrated locally through
  074, 075, 090, 091 in separate transactions to respect existing enum migration
  prerequisites. One head 091 is required. This is not a Production rehearsal call.
- Host runtimes use only synthetic credentials and a loopback-only Python socket
  guard. Newly added destructive fixtures require explicit disposable DB opt-in
  plus known local host/database/user, or the explicit GitHub ephemeral service.
- CI receives only that explicit test opt-in; no deployment workflow is changed.
- Full-suite JUnit evidence: `pg16-full.xml`, `pg18-full.xml`, `arm64-full.xml`.
  Finalization requires zero failures/errors/skips in all three, not merely a
  selected subset. `pg18-regression.xml` records the focused security run.
- ARM64 uses the unchanged cached baseline dependency image and offline test tools;
  build networking is disabled. Runtime tests use packaged `/app` code, prove its
  byte equality to committed source and exercise local `/live` and `/ready` 200/200.
- OpenAPI is compared against API37's cached baseline image with the same runtime
  dependencies. Entire schema equality is required, not just route-count equality.
- Ruff uses the repository's exact CI gate, `ruff check . --select F`. The new
  helper/test files additionally pass default E/F/I/B rules. No claim is made that
  unrelated inherited style debt was rewritten. Compile and `git diff --check`
  are separate gates.

Early failures remain described honestly: six initial phone/date regressions
reproduced defects before fixes; first full PG18 run had 2,705 passes/12 failures
from Passport test doubles missing the new scalar owner lookup. Final passing
ledgers supersede those runs, not the reported root causes.

## Compatibility and Remaining Risks

Wire contracts are unchanged; success responses remain compatible. Signup
completion replay deliberately becomes a conflict and requires normal sign-in.
No client source was modified. The Web/Android/iOS handoff names this behavior and
does not claim device certification or ideal client recovery UI already exists.

The audit records five further P1-risk workflow/contract findings and five P2
findings needing product/client/history decisions. They are not silently fixed,
not removed from the risk list and not covered by a blanket rollout approval.
No schema dependency is proven and no migration is added. HR V2-specific ownership
is untouched. Production connector execution now fails closed if only the seeded
mock is available; a real connector is an explicit future operational dependency.

## Return Matrix Location

The audit supplies requested area findings F-T and severity U-Y; the handoff
supplies AD-AF/BG-BI and unresolved BJ/BK. The external certificate supplies final
SHA/digest AV-AW and test gates AG-AU. Git readback supplies AX-AZ. Baseline A-E is
above. Implementation Z-AC: no P0, 13 P1 hardening fixes, no schema migration,
unchanged OpenAPI. Production operational worktree, HR V2, AWS, Production DB,
deployed services and provider boundaries BA-BF were not mutated/accessed by this
work except the initial read-only ECS metadata baseline. No real email/SMS/GPS.

This is source/artifact hardening certification, not permission to deploy.

Independent-lane readback: HR V2 advanced itself from its initially dirty baseline
to clean `5b6edb13c4b09c64a146d9759046fc182afeff3b` during this task. This audit made
no HR worktree writes and did not copy its changes. Thus "HR untouched by this
task" must not be misread as "the independent HR lane did not advance."
