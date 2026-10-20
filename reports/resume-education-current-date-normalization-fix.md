# Resume Education current-study date normalization

Date: 2026-10-21. Scope: backend correctness, Staging certification only.

## Source and provenance

- Branch: `codex/backend-education-current-date-fix`.
- Actual starting API42 image source: `12ffa525af33f154f22fc7f0519acd7d55578907`.
- Certified code/deployment SHA: `badb8318c0733a82c11117174c093e4ca25ac77f`.
- Isolated worktree: `/private/tmp/kairoid-backend-education-current-date-fix`.
- Starting worktree clean; source commit contains only the three files below. This report is a subsequent documentation-only addition, not a different deployed implementation.
- Important provenance correction: API42's `APP_VERSION=git-ee9220e7367d` is stale. Its `APP_GIT_SHA` and the cached exact deployed image revision label both identify `12ffa525...`. The image digest is `sha256:4adb25f13a1522f6bd2d04affc1d003201d85d8d4aadb3599298b40628c9ee91`. The earlier `ee9220e7367d994c9d4e1597f1ae00c14355f859` is an ancestor; the intervening auth/Admin changes are preserved. The relevant Resume modules are unchanged between those revisions.
- Immutable new ARM64 ECR digest: `sha256:abd469d67c108f5c2d13d8c93d74f8d9f6075056df9b5414564da21b788e0173`.
- ECR tag: `285515885083.dkr.ecr.us-east-1.amazonaws.com/kairo-backend:badb8318c0733a82c11117174c093e4ca25ac77f`.
- Signed-off test source and runtime image module hashes match. Deployment is digest-pinned, not a floating tag.

## Proven root cause and flow

`ResumeReviewService.create` previously called `_review_payload` (schema validation), then `_normalize_review_payload` (date/display mapping), then stored the result without final schema validation. The normalizer could derive `end_date` from `end_date_display` after `is_current=true` had passed the earlier check. `_build_plan` did not run the dated-claim invariant. `_import_item` eventually validated through `review_claim_adapter`, where `current_claim_has_end_date` failed and the enclosing importer reduced it to `item_import_failed`.

This is DATE_CONTRACT / BACKEND_NORMALIZATION, not an iOS defect. No tester content was needed for implementation or Staging proof, and the tester's Production import was not replayed.

Relevant source boundaries:

| Role | Path |
| --- | --- |
| Parsed date/display/precision fields | `app/resumes/schemas.py` |
| Review schema and current/range invariants | `app/resumes/review_schemas.py` |
| Shared year/month date conversion | `app/resumes/normalization.py` |
| New Education-only final normalization | `app/resumes/education_review.py` |
| Review creation/edit, plan, import and persistence | `app/services/resume_review_service.py` |
| Existing Education CRUD contract | `app/schemas/education.py` |
| Stored Education fields | `app/models/education.py` |

`is_current`, both date fields, both display aliases and both precision fields are now examined together in the Education-only helper. Generic date utilities, parser behavior, Employment normalization, Education CRUD schema/model and unrelated Resume logic remain unchanged.

## Files changed

1. `app/resumes/education_review.py`: safe Education-only normalization and final validation.
2. `app/services/resume_review_service.py`: use helper at review creation/edit, review plan validation, and import boundary; preserve explicit skip and prior-import idempotency ordering.
3. `tests/test_resume_education_current_dates.py`: 29 focused regression cases including real PostgreSQL imports.
4. This report (documentation only, after the code commit).

## Contract and behavior

- Current study with no end date remains valid; start dates normalize as before.
- Current study with an actual end date or date-bearing end display returns `current_claim_has_end_date`. No end date is discarded and current-study status is never flipped automatically.
- Existing ongoing display markers such as `Present` are non-date labels, remain preserved, and cannot generate an end date.
- A valid standalone precision without a date remains non-authoritative metadata and cannot invent a date. It is retained rather than silently erased. This deliberately preserves supplied metadata; the old generic normalizer cleared precision when no date could be derived.
- Non-current date/display values use the existing year/month boundary conversion. Malformed dates, conflicting aliases, inconsistent precision and reversed ranges fail before persistence.
- Final `EducationReviewClaim` validation runs after normalization, not just before it. Errors expose only bounded safe codes, not exception text or field values.
- New contradictory claims are rejected during review creation; invalid edits are rejected before saving. Parsed source data remains untouched. Existing stored contradictory review items remain readable and retain original/edited payloads; their selected non-skip plan item carries the safe blocker and the plan is not importable.
- Explicit resolution is required: mark not current, or clear all end-date representations. Both explicit-edit paths are tested. Original review payload is retained after correction.
- Prior successful provenance is checked first at the import boundary. Explicit skip stays skipped and cannot introduce a partial-import failure. Valid import retry retains the same batch and one Education record.
- No bulk rewriting, migration, new column, enum or database constraint.

## Certification

| Gate | Result |
| --- | --- |
| New Education regression module | 29 cases, included in passing runs |
| Focused Resume review/import, Education/Career and Trust | 118 PASS |
| Full PostgreSQL suite, native Python 3.14 / PostgreSQL 16 | 2,931 PASS; 34 warnings |
| Full packaged Linux/ARM64 suite, Python 3.12 / PostgreSQL 18 | 2,931 PASS; 35 warnings |
| OpenAPI/application import | PASS, OpenAPI 3.1.0, 453 paths |
| Migration heads | One head: 093; no migration changed |
| Runtime Linux/ARM64 image | PASS; source SHA and module hashes verified offline |
| `git diff --check` | PASS |
| New-file Ruff | PASS, 0 findings |
| Full-repository Ruff | 2,182 pre-existing findings on baseline and fix; 0 new |
| Modified legacy service Ruff | 92 pre-existing findings on both revisions; 0 new |

Ruff is **not** globally clean. No findings were suppressed, ignored, reformatted away, or configuration weakened. Comparison used relative file, rule, message and source line to account for line-number movement. The earlier historical 2,119 figure does not apply to the actual current API42 source; measured baseline here is 2,182.

Initial full-suite attempts failed disposable-DB guards (Unix-socket URL had no logical localhost host; security tests require explicit `V11_DISPOSABLE_DB=1`, user `qa`, database `v11`). Only isolated harness configuration was corrected. No test safety check or assertion was weakened. Final runs above are complete green reruns.

Evidence directory: `/private/tmp/kairoid-education-cert.JWzSsw` (ephemeral local artifacts).

## Staging deployment and synthetic proof

- API transition: `kairo-staging-backend:253` → `kairo-staging-backend:254`.
- Staging worker stays `kairo-staging-resume-worker:20`: API review/import-only fix does not require a worker rollout.
- Production services share the ECS cluster name `kairo-production`; deployment was explicitly restricted to the Staging service/family/container.
- Staging rollout: COMPLETED, API254 desired/running/pending = 1/1/0; worker20 = 1/1/0. Public liveness/readiness = 200/200, database and Redis reachable. Liveness reports `git-badb8318c073`.
- Synthetic verification task: `bff5b95c54b14e678391da2c01528ded`; STOPPED, exit 0, network attachment DELETED/released. No service or schedule was created for the proof.
- Valid current Education: review → validate → import → actual persisted draft Education with `is_currently_studying=true`, `end_date=null`: PASS. Repeating the idempotency key returns the same batch: PASS.
- Contradictory historical synthetic Education: review plan exposes `current_claim_has_end_date`; import rejects with `review_not_importable`; original/edited payload preserved; no second Education persisted: PASS.
- Staging DB head: 093. Outer transaction rollback verified; remaining synthetic owner rows = 0; remaining synthetic Education rows = 0. Provider calls = 0; S3 objects created = 0.
- Synthetic harness uses a unique disposable owner and parsed Resume fixture, no actual document upload, S3 object, extraction, parser/provider, OTP or authentication flow.
- Service commits are contained in savepoints under an outer transaction. The harness checks actual persisted Education rows inside the transaction, then rolls back the outer transaction and checks zero remaining synthetic owner/Education rows. This is a service-path/database integration proof, not an end-to-end PDF/parser/UI test.
- The exact harness was first proven against the disposable local database. Its Staging package checks environment, database name, source SHA and module hashes, and blocks all non-database network access.

## Production negative controls and boundaries

- Post-deployment Production API42 and Worker13 remain unchanged at 1/1/0 each; public liveness/readiness = 200/200. No Production task or deployment launched by this fix task.
- DB093 is the established Production head; no migration was run against Production. Production DB was not reopened for this task.
- No Production account/data mutation, tester import replay, provider call, Google/login/session action or persistent audit infrastructure.
- iOS and Android unchanged. Original dirty iOS checkout retains 19 modified files, untouched by this work.
- Main backend checkout remains clean at `7197b2481742525e25880c29290ca1dffa4ccc16`; all implementation occurred in the isolated worktree.
- No Git push, Production deployment or client release performed.
- Disposable local ARM64 PostgreSQL/Redis containers and their internal network were removed after successful tests. Native task-specific PostgreSQL/Redis servers were stopped. Source, reports, logs and local certification images were retained.

## Release decision

**READY_FOR_PRODUCTION_DEPLOYMENT_APPROVAL**

Source certification, packaged ARM64 regression, Staging deployment, and synthetic service/database proof are complete. No remaining blocker for requesting Production deployment approval. Existing repository Ruff debt remains explicitly recorded above, not presented as clean lint.

Production deployment requires separate approval. Historical contradictory claims are intentionally not repaired automatically and still require explicit review edits. No Production import replay or account repair is included in this approval-ready result.

KAIROID BACKEND — EDUCATION CURRENT-STUDY NORMALIZATION
