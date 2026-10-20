# Education current-study normalization — Production deployment

Date: 2026-10-21 (Asia/Kolkata). Authorized scope: certified backend fix only; API rollout, no worker rollout or Production migration.

## Source control

- Certified runtime source: `badb8318c0733a82c11117174c093e4ca25ac77f`.
- Actual prior Production source: `12ffa525af33f154f22fc7f0519acd7d55578907`.
- Branch: `codex/backend-education-current-date-fix`.
- Initial normal branch push: `d459d1c2bc25e6abde870cbba159e2be956e488a`, comprising the certified fix plus the preceding Staging certification report only. Local/remote equality and 0/0 verified before deployment.
- The runtime was built from a separate clean detached checkout at exactly `badb831...`, not from the later report commit or a dirty checkout.
- Runtime code delta: only `app/resumes/education_review.py` and `app/services/resume_review_service.py`. The fix commit also adds regression tests. No migration, dependency manifest, Dockerfile, mobile, or unrelated backend source changes.
- This report is a subsequent documentation-only closure commit. Its pushed SHA is returned separately; it is not the deployed runtime SHA.

## Packaging discrepancy caught and resolved

The Staging image was **not promoted**. Offline inventory comparison found that its ordinary unpinned rebuild resolved 10 versions differently from the current Production image:

| Package | API42 | Staging artifact |
| --- | --- | --- |
| boto3 | 1.43.114 | 1.43.116 |
| botocore | 1.43.114 | 1.43.116 |
| certifi | 2026.7.22 | 2026.10.19 |
| fastapi | 0.143.3 | 0.156.2 |
| pip | 26.2.1 | 26.2.2 |
| pydantic-settings | 2.16.0 | 2.16.1 |
| pypdf | 6.21.0 | 6.21.1 |
| s3transfer | 0.19.2 | 0.19.3 |
| starlette | 1.8.0 | 1.9.0 |
| websockets | 17.2 | 17.3 |

To honor source-only scope, the Production artifact inherits the exact immutable API42 runtime layers and copies only the two certified runtime source files. No dependency installation or OS package update occurs in that runtime stage. Build instructions were kept outside the repository; no new application source change was made.

- Base digest: `sha256:4adb25f13a1522f6bd2d04affc1d003201d85d8d4aadb3599298b40628c9ee91`.
- Production digest: `sha256:3c4b7fa04a5d3d9a94fb49a5a955c8b8cf6483b2ec8be457e98556310b891636`.
- ECR tag: `285515885083.dkr.ecr.us-east-1.amazonaws.com/kairo-backend:badb8318c0733a82c11117174c093e4ca25ac77f-production-api42-runtime`.
- Deployment is pinned to the digest; the existing Staging SHA tag was not overwritten.
- Linux/ARM64; all base runtime layers retained.
- All **654 tracked runtime/source/migration/config files** match the exact source checkout byte-for-byte.
- All **60 runtime Python distributions** match API42 versions; **0 dependency differences**. All underlying OS/runtime layers remain inherited unchanged.
- Image environment differs only in `APP_GIT_SHA` and `APP_BUILD_ID`; no Staging configuration baked in.

## Re-certification of the Production-runtime-preserving artifact

- Full packaged ARM64/PostgreSQL suite: **2,931 PASS**, 35 warnings, 61.70 seconds.
- Separate test image adds only test tooling; all 60 application/runtime distribution versions remain unchanged there too.
- Initial test-image attempt: 2,930 PASS, one harness failure because Git was absent from the minimal runtime. Git was added only to the test stage, then the complete suite was rerun successfully. No source/test assertions were changed or weakened.
- Prior certification remains: 118 focused PASS; 29 new regressions; native PostgreSQL suite 2,931 PASS; OpenAPI PASS; no new Ruff findings; one migration head 093.
- Pure in-memory diagnostic in the exact Production artifact, with networking disabled: valid current-study payload retains `end_date=null`; contradictory end display returns `current_claim_has_end_date`; original input preserved; no automatic current-state change.
- Local regression used only disposable local databases. No Production migration command was executed.

## Pre-deployment live gate

- API42 and Worker13: both desired/running/pending 1/1/0, deployment COMPLETED.
- Production liveness/readiness 200/200; ALB target healthy.
- API42 image digest and `APP_GIT_SHA=12ffa525...` matched the expected baseline; no unexpected source/runtime drift.
- Its old `APP_VERSION=git-ee9220e7367d` was stale; new build provenance now identifies the correct deployed source.
- Fifteen-minute pre-deployment observation: no target-5xx datapoints and zero ERROR/CRITICAL/Traceback log events; request metrics were present. Raw application log messages were not printed or included.

### Explicitly approved schema-only read-only task

- Task: `95e14c5e439a4b8085e481d5cc14d723`, using existing API42, not a new service or schedule.
- `SET TRANSACTION READ ONLY` enforced before the schema query and rechecked afterward.
- Queried only `alembic_version` and transaction read-only status; **one head: 093**.
- No Candidate, session, Resume, or other business table read; no migration or data mutation.
- Non-database network connections blocked in the diagnostic process.
- STOPPED, exit 0, network attachment DELETED/released.
- No additional Production schema/audit task was launched.

## API-only rollout

- Previous task definition: `kairo-backend:42`.
- New task definition: `kairo-backend:43`.
- Rollout started: `2026-10-20T21:45:28.864764+00:00`.
- Image: exact Production digest above.
- Worker remains `kairo-resume-worker:13`. Source inspection confirms the worker invokes Resume processing, not `ResumeReviewService` or the new Education review normalizer; no worker rollout is necessary.
- CPU/memory, IAM roles, secrets/references, runtime platform, health checks, command, ports, tags, and all functional environment values preserved.
- Only image and build-provenance fields changed: `APP_GIT_SHA`, `APP_BUILD_ID`, `APP_VERSION`, `APP_DEPLOYED_AT`.
- Service update specifies only the new task definition. No ALB, VPC, security group, subnet, IAM, or secret configuration change.
- Initial strict registration comparison stopped before service mutation because ECS reordered environment entries. Semantic name/value comparison proved only the intended changes; the already-registered API43 revision was reused. No additional task-definition revision was created to work around it.

## Post-deployment verification

- API43 rollout COMPLETED; desired/running/pending **1/1/0**.
- Worker13 remains COMPLETED, **1/1/0**.
- `/api/v1/health/live` **200**, `/api/v1/health/ready` **200**; environment `production`, version `git-badb8318c073`.
- The target belonging to the exact running API43 task is **healthy**. One retired target was still in normal `Target.DeregistrationInProgress` during the first final snapshot; it is not an unhealthy API43 target.
- Actual running container digest verified equal to `sha256:3c4b7fa04a5d3d9a94fb49a5a955c8b8cf6483b2ec8be457e98556310b891636`.
- Deployed code identity follows the exact digest/source inventory verification above. No runtime code injection, ECS Exec, real import, or Production business fixture was used to test it.
- Post-deployment observation: `2026-10-20T21:45:28.864764+00:00` through `2026-10-20T21:49:46.701877+00:00`.
- Target 5xx: **no datapoints/events observed** (zero observed sum); RequestCount metrics present (2 requests summed over 4 returned datapoints). This is a bounded low-traffic observation, not a load test or guarantee about future traffic.
- CloudWatch ERROR/CRITICAL/Traceback events: **0** in that window. No startup error or 5xx spike observed; no raw messages/account details printed.

## Negative controls

- Production schema: fresh pre-deployment query confirmed 093; no schema-changing action or Production migration executed afterward.
- No Production Candidate/account/business-data mutation performed by this task.
- No tester Resume import replay; no Production synthetic business rows.
- No provider, Google, DigiLocker, OCR/parser, GPS, email/SMS, login/logout, OTP, or session-revocation action.
- iOS and Android untouched; original dirty iOS checkout still has its 19 modified files and was not edited.
- No changes to main branch, no force push, no mobile build/release.
- Staging API254 and Staging Worker20 are not redeployed by this task.
- Temporary local test containers/network removed after the passing run; source, runtime image, report and evidence retained.

Evidence directory: `/private/tmp/kairoid-education-production.izFRSN`.

## Final status

**PRODUCTION DEPLOYMENT COMPLETE**

Remaining blockers: none for this deployment. Existing contradictory review claims remain preserved and require explicit correction; this task did not repair or replay the tester's claim.

Source-control closure uses a normal documentation-only commit/push on the same approved branch, with local/remote equality, ahead/behind 0/0 and clean worktree rechecked before handoff. No force push or merge. The final report-commit SHA is returned in the handoff; deployed source remains exactly `badb8318c0733a82c11117174c093e4ca25ac77f`.

KAIROID BACKEND — EDUCATION NORMALIZATION PRODUCTION DEPLOYMENT
