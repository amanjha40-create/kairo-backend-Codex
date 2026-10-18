# Backend Integration DAG Audit

Audit date: 2026-10-18. Source/artifact certification only; no rollout.

## Exact Production Provenance

Read-only ECS `describe-services` confirms `kairo-backend:37`, desired/running/
pending 1/1/0. `describe-task-definition` confirms Linux ARM64 and:

- APP_GIT_SHA and OCI revision: `473811f410b3918a4febd7dbc4fdaf20a8584893`.
- Image: `285515885083.dkr.ecr.us-east-1.amazonaws.com/kairo-backend@sha256:427d2612b6d98b5d3e1bd0dc588d09170cdb420c9a5e4f8d75a7bb4f3b345801`.
- Local Production release evidence independently maps API36/37 to this source;
  those revisions enabled feature configuration, not newer source.
- No Production database access or AWS mutation was performed.

## DAG

```text
473811f (API37 source, schema091)
|-- 598929b (13 core hardening fixes)
|   `-- 43c4683 (deterministic audit inventory; V1.1 frozen tip)
`-- f0786fc (HR V2 contracts, schema092)
    `-- 5b6edb1 (self-certifying development image; HR frozen tip)
        `-- aec4a41 (Admin Operations contracts, schema093)
```

`git merge-base` for both frozen lines with Production is exactly `473811f`.
Production has zero commits missing from the Admin base. There are no additional
post-473811 Production source changes to replay. HR/Admin is already linear.

## Overlap and Base Decision

The V1.1 changed-file set and Production-to-Admin changed-file set have no common
paths. The anticipated overlap in the historical Admin handoff was precautionary,
not an actual conflict in these frozen SHAs. Semantic interactions still require
regression: new Candidate claim/HR invitations versus core token/password rules,
organization report permissions/consent, and inherited public projections.

Use exact `aec4a41d255b9659168e2630442a89c932d043c2` as the integration base.
Apply reviewed `598929b` then `43c4683` without replacing HR/Admin services.
Expected graph remains 091 -> 092 -> 093; no new migration is authorized.

Independent worktree: `/Users/Aman/Desktop/work/kairo-backend-integrated-v1-1`.
Branch: `codex/backend-integrated-v1-1-hr-admin`. All frozen worktrees are read-only
inputs; unrelated main-checkout changes are preserved.

Integration and runtime certification results are recorded in the companion
integration matrix and certification report; this audit alone is not a PASS claim.
