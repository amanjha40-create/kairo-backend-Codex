# V1.1 Integration Matrix

Frozen input: `43c4683795a7ee961a84a7c545da68e90d8f58e1`.
Production base: `473811f410b3918a4febd7dbc4fdaf20a8584893`.
Admin schema base: `aec4a41d255b9659168e2630442a89c932d043c2`.

Both source commits applied cleanly as `19eeadb5` and `2644b65b`. No conflict
resolution or schema change was needed. CLEAN_APPLY describes the integration,
not a regression PASS; runtime results are recorded in final certification.

| Fix | Classification | Preserved behavior | Regression evidence |
| --- | --- | --- | --- |
| F01 | CLEAN_APPLY | Explicit phone clear invalidates verification | test_v1_1_core_hardening / security |
| F02 | CLEAN_APPLY | UTC-normalized date/naive filter boundaries | test_v1_1_core_hardening |
| F03 | CLEAN_APPLY | Owner-before-token serialization for refresh/revocation | test_v1_1_security |
| F04 | CLEAN_APPLY | Signup capability rotation and cleared OAuth intent; destination rate budget | test_v1_1_security |
| F05 | CLEAN_APPLY | Signup completion one-shot; account collision fails closed | test_v1_1_security / google_auth_lifecycle |
| F06 | CLEAN_APPLY | Password reset consumption serialized | test_v1_1_security |
| F07 | CLEAN_APPLY | Organization evidence list applies consent filtering | test_v1_1_security |
| F08 | CLEAN_APPLY | Current/historical address proofs excluded from public Vault | test_v1_1_security |
| F09 | CLEAN_APPLY | Synthetic verification connector unavailable in Production | test_v1_1_core_hardening |
| F10 | CLEAN_APPLY | Expired/superseded manual identity excluded from current truth | test_v1_1_core_hardening |
| F11 | CLEAN_APPLY | Active owner required for public Passport; serialized suspension | test_v1_1_security |
| F12 | CLEAN_APPLY | Owner-scoped grouped share counts, no per-link query loop | test_v1_1_security |
| F13 | CLEAN_APPLY | Legacy full-list envelope no longer capped by query-input limit | test_v1_1_core_hardening |

All 13 fixed findings are accounted for. No certified fix was silently dropped
or classified superseded. The original audit's deferred D01-D10 product decisions
remain deferred unless explicitly addressed in the integration certification.
No score weights, password policy, notification behavior or historical data is
changed merely to integrate these fixes.
