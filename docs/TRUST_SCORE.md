# Kairo Trust Score V1

The canonical source for Version 1 scoring is `Kairo_Trust_Score_Logic.md.pdf` supplied with Command 9. The backend implementation is in `app/services/trust_score_service.py`; its response contract is in `app/schemas/trust_score.py`.

## Source-of-truth rules

- Scoring is blocked until the candidate records explicit Trust Score consent. The consent timestamp and consent version are stored on `users`.
- This consent is purpose-specific to Kairo calculating and displaying the candidate's own Trust Score; it does not consent to verification-request evidence sharing or organization screening.
- Version 1 scores only Identity, Employment, and Education. Documents are evidence, not a scored fourth domain.
- Domain weights are configurable defaults: Identity `0.25`, Employment `0.45`, Education `0.30`.
- The score is `Identity * 0.25 + Employment * 0.45 + Education * 0.30`, rounded to an integer for the overall display.
- Each result is persisted in `trust_score_snapshots` with `score_version`, status, domain details, contributors, overrides, completeness, consent timestamp, and calculation time.
- Repeated reads with unchanged inputs reuse the latest equivalent snapshot; a changed authoritative input creates a new auditable snapshot. Historical snapshots are retained when consent is withdrawn.
- Profile Completion, Passport Completion, Verification Status, and Trust Score remain separate values.
- The engine consumes existing verification outcomes. It does not create verification requests, approve records, update Passport records, or calculate in the frontend.

## Current evidence mapping

- Identity document approved/verified: authoritative identity tier; candidate-submitted identity evidence: self-attested tier.
- Verified email and phone contribute their independent binary checks.
- Approved employment claims and verified education claims contribute existing workflow outcomes; submitted but unverified claims are represented as self-attested evidence.
- Face KYC is excluded until the existing identity architecture supplies a face-match result; this follows the specification's in-person/non-applicable rule.

## Explicit engineering differences

The specification defines proposed internal point splits and several fraud signals, but the current domain models do not yet store authoritative salary, resignation, PF/UAN, face-match, government-API, blocklist, institution-list, or document-template results. The implementation therefore does not infer those facts or award those unsupported signals. It exposes empty fraud/override lists until a supported verification provider records them. This is fail-closed and avoids turning missing checks into verified evidence.

The specification's critical fraud overrides are represented by the response contract (`critical_overrides` and `critical_manual_fraud_review`) but are not raised from unpopulated signals. Adding a fraud signal must happen in the relevant verification workflow, not in the score calculator.

## API

- `GET /api/v1/trust-score` returns the current backend-owned result, status, three domain scores, domain details, contributors, overrides, version, completeness, and timestamp.
- `POST /api/v1/trust-score/consent` records explicit consent with a caller-supplied policy version. It does not calculate or alter verification state.
- `DELETE /api/v1/trust-score/consent` withdraws only Trust Score calculation consent. It does not delete historical snapshots and does not alter verification-request consent.
- `GET /api/v1/public/profile/{slug}/trust-score` uses the same versioned backend result where public Passport permissions allow it.

## Maintenance

Use a new `score_version` and migration when scoring rules change. Keep the existing snapshot rows immutable for audit and explainability. Proposed weight defaults remain environment-configurable through `TRUST_SCORE_*_WEIGHT` settings.
