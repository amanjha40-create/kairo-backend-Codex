# Production iOS DigiLocker completion-return contract

Date: 2026-10-14. Scope: local backend release-candidate source and image only.
Baseline RC: `2d144c3888d4b061ea21297450cfa42bad1a8680`.
The successor commit containing this report is the source checkpoint. Its exact SHA,
image manifest digest, runtime regression results, and image inventory are recorded
outside the source tree under `/private/tmp/kairoid-ios-return-rc-evidence` after
committing and building. This report does not claim a live Production certification.

## Approved contract

| Environment | iPhone auth-session callback |
| --- | --- |
| Production success | `com.kairoid.digilocker://complete?result=connected` |
| Production failure | `com.kairoid.digilocker://complete?result=failed` |
| Staging success | `com.kairoid.staging.digilocker://complete?result=connected` |
| Staging failure | `com.kairoid.staging.digilocker://complete?result=failed` |
| Development, test, unknown | No iPhone custom-scheme action |

The mapping is a fixed allowlist selected by the existing typed `APP_ENV`; no new
setting or request-derived destination is introduced. Unknown completion outcomes
map to `failed`. Return URLs contain only the fixed scheme, `complete` host, and
safe `result` enum. They carry no OAuth state/code, credentials, Candidate/provider
identity, or raw error text. The existing iPhone button label remains
“Return to KairoID on iPhone”.

## Architecture and security

The native app starts `ASWebAuthenticationSession`; backend-owned authorization,
PKCE, single-use state consumption, and code exchange remain unchanged. The browser
callback redirects to credential-free completion HTML. The user taps the iPhone
action; the active native session receives the custom-scheme result and consumes
it at most once. The app must then read authenticated server state. A `connected`
hint never grants authentication, verification, or a Connected state by itself.

Production backend callback remains
`https://api.kairoid.com/api/v1/integrations/digilocker/callback` and completion
remains `https://api.kairoid.com/api/v1/integrations/digilocker/complete`.
No provider configuration was modified. The renderer uses the existing validated
server redirect origin for Android, never an incoming Host value.

Existing no-store, no-referrer, CSP, nosniff, escaped web action, safe failure copy,
and browser-close fallback are preserved. Staging HTML remains byte-identical to
the pinned baseline. Production HTML differs only by adding the approved iPhone
action; the Android/web actions and response security headers remain unchanged.

Android Production remains `com.kairoid.app`; Staging remains
`com.kairo.app.staging`. Android's HTTPS completion App Link is unchanged.

## iOS handoff and certification boundary

The current iOS checkpoint `92e59118b6445e147ffdadf88015ebb6ddb2b2d9` still uses
the Staging-only parser. Its separately scoped implementation must select the
Production scheme only in Production and retain the Staging scheme in Staging.
Both the session's callback configuration and strict return parser must agree.
Keep cancellation, duplicate-return protection, and authoritative refresh behavior.

No Universal Links, Associated Domains, AASA publication, or Apple Team ID is
required by this active-session custom-scheme return mechanism. Do not register a
global scheme or claim cold-start recovery merely because the active-session
callback works. Apple Organization enrollment/signing and cold-start behavior
remain independent iOS release/certification gates. No temporary Personal Team
identity is published or associated with Production by this change.

## Regression evidence

- iPhone contract: 26 tests pass (both environments, success/failure, hostile or
  unexpected results, URL allowlist, safe HTML, and unsupported environments).
- Android return contract: 10 tests pass.
- DigiLocker suite: 573 tests pass.
- Offline old/new HTML comparison: 30 cases pass; Staging unchanged byte-for-byte;
  Production adds only the fixed iPhone action.
- Full host backend: 2,482 passed (30 warnings); focused RC: 1,885 passed
  (25 warnings), covering Production safety, auth/security, Admin direct-confirmation,
  Employment References, Permanent Address, deletion/privacy, Passport, and worker.
- OpenAPI contract regression: PASS (407 baseline paths and 639 baseline schemas
  checked against the established RC reconciliation contract).
- API/worker imports and OpenAPI generation: PASS. The initial standalone harness
  command shadowed its FastAPI variable with the `app` package; correcting that
  command passed without a product-source change.
- Exact-image regression results are recorded in the companion evidence directory
  after the commit is built, and must pass before the final certification claim.
- Ruff: changed Python files must have zero findings; existing CI F-rule gate must
  pass. Full repository baseline is 2,169 pre-existing findings, not a clean lint
  result. Files containing these findings are byte-identical to the pinned RC.
- Ruff CI F-rule gate and changed-file checks: PASS. No configuration suppression.
- No migrations: verified sole Alembic head remains `090`; no migration files changed.

## Boundaries

No Production/Staging deployment, cloud DB migration, provider/Authpartner setup,
Production credentials, real OAuth/Aadhaar call, Android/iOS/Admin/HR source edit,
Git push, or image-registry push is performed. Tests use local disposable services
and synthetic/mocked provider data. Exact-image test dependencies are installed
only in a disposable test container, not added to the release image.
