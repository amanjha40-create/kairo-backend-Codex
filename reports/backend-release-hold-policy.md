# Integrated Backend Release-Hold Policy

This scoped change continues `50f885f9ce3604fd6908e6d6ba3dde0547023c71`
on `codex/backend-integrated-v1-1-hr-admin`. Schema remains 093. It is not a
Production deployment approval and does not certify the frozen frontend adapters.

## Internal Reference Projection

Current `full_name`, `designation`, `key_strength`, and `additional_comments`
map to the existing report DTO. Historical `name`, `title`/`relationship`,
`strengths`, and `comments` remain fallbacks. Only active reference versions enter
the current report; superseded nominations remain in storage and audit history.
`work_together_again` is not relabeled as an employer rehire decision.
Current HR `eligible_for_rehire` is preserved in `rehire_response`, including
negative answers. When references are ordered, the existing per-employment pair
(HR plus reporting manager) is required; a missing member is projected as pending.

The structured report remains internal to authorized organization members and
Admin readers. Public/shared Passport, owner Passport, Candidate reference
summary, and Passport PDF/export use their existing allowlists, never this
internal report serializer. Regression coverage checks both HR and manager
free-text comments against every one of these consumer surfaces.

## Finality

One policy derives report status, open items, and `hr_review_required`.
Unresolved ordered work produces INTERIM, an open item, and review required.
Pending/awaiting references, pending address, unfinished court work, discrepancies,
rejected/unable outcomes, and clarifications cannot coexist with FINAL.
Confirmed/details-matched results are resolved. NOT_ORDERED does not block.
An empty report remains INTERIM without inventing a requested check.

Ordering comes from organization/person-scoped request rows and pending/accepted
Trust Invitations, not the organization's latest mutable defaults. Existing
active reference records and court checks are also actual work. Saved personal
identity/address records do not, on their own, order those checks for an HR case.
Historical invitation snapshots containing address intent remain pending until
the address workflow completes. New explicit selections do not inherit address
intent from the defaults snapshot. Missing results for requested checks are pending,
including requested types outside the fixed summary categories.

## Invitation Lock Order

All team capability mutation uses transaction-scoped row locks in this order:
organization, invitation, then membership creation/update. Token/public-ID lookup
first discovers only the parent ID; state and token are re-read after acquiring
the organization lock. `populate_existing` prevents stale ORM identity-map data
from resurrecting a rotated/revoked/used token. No external delivery occurs while
these locks are held: existing delivery follows commit.

Admin first-HR provisioning uses the same parent-first protocol. Acceptance and
provisioning reject suspended organizations after lock acquisition. Organization
state UPDATEs serialize against this row lock. Bulk lazy-expiry inspection locks
parents/invitations in sorted order and rechecks state before expiring a row.
Acceptance never releases locks between validation and membership/token commit.
Direct member addition also locks the organization before taking the membership
foreign-key lock, avoiding lock upgrades during pending-invitation cleanup.

Deterministic tests preload stale state in the contender, hold the parent's lock
in the winner, and require PostgreSQL `pg_blocking_pids` to prove contention before
allowing the winner to commit. Both orderings cover accept/revoke, accept/resend,
resend/revoke, and first-HR acceptance/state change; duplicate acceptance and
Admin first-HR resend races are covered. Bounded lock/statement/test timeouts
fail rather than concealing a deadlock. All deliveries are in-memory test sinks.
The direct-add race additionally proves the contender has not reached membership
insertion before it obtains the parent lock, with two distinct expired invitations.

## Preference Capability Boundary

Omitted `requested_verification_types` uses a new snapshot of organization defaults.
Explicit `[]` means no types; it is permitted by the existing invitation contract.
Explicit nonempty selections remain authoritative. Existing invitations are not
rewritten. Snapshot metadata records whether defaults or explicit types were used.

Schema 093 has neither an address Trust Invitation type nor an address generic
VerificationRequest type. Permanent Address has a separate workflow. Enabling an
unsupported address default now yields a clear validation error rather than silently
dropping it. The caller can use explicit supported types or disable that default.
No enum, schema, geocoding, location collection, or workflow engine is added.

The reference pipeline supports its existing per-employment HR and manager records,
not arbitrary N-reference orchestration. A selected professional-reference request
with a nonzero default reference count now yields a clear validation error instead
of promising enforcement. A zero count uses the existing workflow without a numeric
promise; the snapshot records `reference_count_applied=false`. Preferences remain
stored intent, not an instruction to create records or send messages automatically.

## Certification Evidence

Exact source SHA, OCI digest, platform, test totals, OpenAPI comparison, and packaged
source equality belong to the immutable artifact evidence in:
`/Users/Aman/Documents/New project/artifacts/backend-integrated-hold-closure/`.
Do not infer completed certification solely from this policy document.

## Separate Frontend Release Holds

- Frozen HR `8ce365ef84372a35967648d269c696c3f8f3213e` dispatches court details using
  `court_search`, but the canonical summary key is `court_record_search`.
- Frozen Admin `d7f93efd2f61f1c253739b9da65fd793c106d5d2` lacks the new receipt,
  first-HR provisioning readback, and structured-report adapters.

Those worktrees remain unchanged. Existing deferred product work (record-level
sharing, push delivery, coordinated password policy, and V1.1 D01-D10) is not
silently closed by this backend hold-closure change.
