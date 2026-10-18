# Backend Integration Validation: Release HOLD

This report does not certify the combined frontend/backend release. The founder
explicitly chose to preserve the frozen HR SHA and report its court-detail blocker.
No conditional post-certification push or deployment may be inferred from local
test success. See `backend-integrated-release-handoff.md` for all release holds.

## Source and Isolation

Production API37 source was positively established as
`473811f410b3918a4febd7dbc4fdaf20a8584893`, image
`sha256:427d2612b6d98b5d3e1bd0dc588d09170cdb420c9a5e4f8d75a7bb4f3b345801`.
Read-only ECS service/task metadata showed API37 at 1/1/0, Linux ARM64.
Production DB was not accessed. There are zero Production-only source commits
above that SHA in the deployed image mapping.

Independent worktree: `/Users/Aman/Desktop/work/kairo-backend-integrated-v1-1`.
Branch: `codex/backend-integrated-v1-1-hr-admin`.
Schema base: Admin `aec4a41d255b9659168e2630442a89c932d043c2`, head093.
The two V1.1 commits applied as `19eeadb5` and `2644b65b`; no overlapping changed
files or textual conflicts. HR and Admin are already linear; nothing was blindly
overwritten. The accompanying DAG and all-13 matrix record exact inputs.

All tests use disposable synthetic local PostgreSQL 16.15/18.3 and Redis on an
internal Docker network with a loopback-only socket guard. No real credentials,
provider traffic, Production records, messages, or existing HR test containers
are used. Prior failed harness attempts remain in external evidence.

## Integrated Changes

- All 13 V1.1 fixes preserved, with no new migration or schema rewrite.
- Six additive Admin GET operations: court list/detail, in-person list/detail,
  masked organization/first-HR status, and permission-guarded internal report.
- Organization/person scope is retained for receipts; current response DTOs reused.
  Paginated reads use bounded SQL limits. Reads do not create notifications/events
  or alter canonical verification, Trust Score, or Permanent Address progress.
- Suspended organization managers/members are rejected by manager mutation gates.
- Partial employment-profile patches preserve role unless `role_id` is explicitly
  supplied; explicit null still clears it.
- Assisted claim passwords normalize outer whitespace like existing Candidate
  login. This is credential interoperability, not a new strength policy or rewrite.
- Regression coverage adds fresh-session reads, wrong-scope denial, all new read
  routes rejecting anonymous/Candidate/HR/Institution callers, and comment-redaction
  checks through actual synthetic public/shared/owner Passport and PDF projections.

## Validation Evidence

External evidence directory:
`/Users/Aman/Documents/New project/artifacts/backend-integrated-v1-1`.

| Gate | Result |
| --- | --- |
| Focused integration, references/privacy, new route guards, PDF | 197 PASS |
| PG16.15 full suite | 2,781 PASS; zero failures/errors/skips; see pg16-full.xml |
| PG18.3 full suite | 2,781 PASS; zero failures/errors/skips; see pg18-full.xml |
| 091 -> 092 -> 093, 092 -> 093, fresh093 | PASS on both PostgreSQL versions |
| Migration witness/data preservation | PASS; new claim-status default, original fields unchanged |
| Alembic heads | Exactly [093]; no migration094 or merge revision |
| Ruff existing CI F gate | PASS |
| Python compilation / diff whitespace | PASS |
| Scoped default Ruff on new read code and touched regression tests | PASS |
| Independent read-only new-endpoint review | No newly introduced findings |
| OpenAPI baseline comparisons | Additive only; no removed operations or existing property changes |
| Packaged ARM64 suite/provenance/health | Exact-SHA external artifact-evidence.json is authoritative when present |

The first full run found six old fixture failures (missing organization
`suspended_at`) and one harness-environment failure (migration-only URL supplied
to a test requiring absent migrator configuration). The fixture now includes the
real nullable field; runtime tests no longer inherit migration-only configuration.
No assertions or access rules were weakened. Prior failure logs are retained.

OpenAPI compared against Production473811, V1.1 43c468, HR5b6edb and Adminaec4a41.
Production/V1.1 differences are optional HR fields and optional People filters.
HR's existing court item gained optional fields. Against Admin, every existing
operation and schema is unchanged. New read methods are additive. Structural
compatibility does not resolve the frozen HR application's court-key dispatch bug.

Reference privacy passes for external tested surfaces; internal Admin retains HR
and manager comments. The structured HR report preserves its legacy comment field
but does not map all current manager keys. That incompleteness remains a release
hold, not a claim that internal HR rendering is fully correct.

## Requested Return Matrix

| Fields | Result |
| --- | --- |
| A-D | API37=473811f410b3918a4febd7dbc4fdaf20a8584893; isolated worktree/branch above; schema093 base |
| E-H | No Production-only deltas; V1.1 file sets disjoint; Admin descends HR; no textual conflicts |
| I-J | All13 accounted for; focused hardening regressions PASS |
| K-O | Linear091/092/093, single093, no new migration; both migration rehearsals PASS |
| P-R | Existing lifecycle/roles/logo contracts plus partial-role/access regressions PASS |
| S-T | Existing preferences/team sequential tests PASS; orchestration/concurrency holds remain |
| U | Existing report tests PASS; frozen court rendering and report completeness NOT certified |
| V-Z | Existing assisted Candidate, claim, provenance, provisioning and first-HR tests PASS |
| AA-AC | Existing court/in-person tests PASS; no PA or canonical-verification credit added |
| AD-AF | Backend additive receipt, masked status and internal report reads implemented/tested |
| AG | Frozen Admin adapters/renderer absent; UI refresh closure deferred |
| AH-AI | External tested comment projections safe; internal Admin retained; HR mapping hold |
| AJ | Existing cross-tenant plus new read-scope/permission regressions PASS |
| AK | BACKEND_PASSPORT_RECORD_LEVEL_SHARING_REQUIRED |
| AL | Device registration/delivery/client handling missing; no real push |
| AM | Strength policy unchanged; coordinated policy/client work remains; claim normalization aligned |
| AN-AU | See validation table and exact-SHA external evidence; no unrun gate is implied PASS |
| AV | HR8ce365 NOT fully compatible; founder retained SHA and accepted blocker reporting |
| AW | Admind7f93 existing contracts preserved; new read UI integration incomplete |
| AX | Android045ed45 existing OpenAPI backwards compatible; no new physical QA claimed |
| AY-AZ | Final source/digest, if built, recorded in external artifact-evidence.json; local only |
| BA | Schema093 |
| BB-BC | Push held; remote parity not claimed |
| BD | Cleanliness recorded after local commit/artifact validation; no cleanup of unrelated work |
| BE-BH | NO Production deployment, Production DB access, AWS runtime change, real messages/providers |
| BI-BK | Rollout HOLD; blockers and proposed order documented in release handoff; nothing executed |

## Release Decision

Keep all frozen frontend SHAs. Do not substitute a backend key alias to hide the
HR mismatch. Full integration release certification is BLOCKED, regardless of
local source/artifact tests. Source push remains held under the brief's
post-certification condition. No frontend, Android, iOS, AWS or Production change.
