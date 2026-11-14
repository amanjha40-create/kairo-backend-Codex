# Staging Resume extraction evidence (2026-11-14)

Status: **FAILED**. This document is privacy-safe and does not contain source
names, contact details, raw Resume text, Textract blocks, or model output.

## Recoverable evidence

| Stage | Recoverable | Evidence boundary |
| --- | --- | --- |
| PDF layout and embedded text | Yes | The locally supplied one-page source remains available outside Git. |
| Textract blocks | No | Raw blocks were not retained after canonical cleanup. |
| Model response | No | Raw output was intentionally not retained. |
| Normalized claims | Partial | Redacted UI state, counts, and retained provenance establish the final claim set. |
| Validation decisions | Partial | Final warnings, held/imported outcomes, and UI state remain; intermediate decisions do not. |
| Import payloads | Partial | Imported record/provenance outcomes remain; the exact serialized request was not retained. |

Raw model-versus-normalizer attribution is therefore not claimed where the
underlying provider evidence is unavailable.

## Manually checked source-to-output comparison

| Record | Source truth | Latest output | Disposition |
| --- | --- | --- | --- |
| Employment A | Employer A, repeated role title, Jan 2025-Jun 2025, historical | Apr 2023-Jan 2024 attached | Wrong association |
| Employment B | Employer B, same role title, Apr 2023-Jan 2024, historical | Dates absent and marked current | Wrong association/current semantics |
| Employment C | Employer C, distinct role, Jun 2022-Apr 2023, historical | Correct | Grounded |
| Employment D | Employer D, distinct role, Dec 2020-Jun 2022, historical | Correct | Grounded |
| Education A | Qualification A + Institution A, 2021 | Institution B attached | Wrong block association |
| Education B | Qualification B + Institution B, 2016 | Institution C attached | Wrong block association |
| Education C | Qualification C + Institution C, 2014 | Correct | Grounded |
| Professional candidacy | Explicit candidacy/exam-progress wording | Omitted | Non-earned attention item lost |

The source contains no current Employment. A missing end date is not evidence
that a role is current.

## Confirmed deterministic risks

- PDF column flattening can place the first Employment row before the visual
  section heading.
- The previous Employment reconciler could use a global list-order fallback
  after one anchor matched, allowing reordered model claims to inherit another
  record's date range.
- Repeated role titles are not record identity and cannot safely associate a
  date range without an exact employer or source-reference anchor.
- No post-model Education block reconciliation existed, so incorrect
  qualification/institution pairings could pass through normalization.
- Source candidacy recovery only handled model-emitted claims; an omitted
  candidacy could disappear from the final review set.

The exact historical stage that first introduced each wrong Education pairing
cannot be recovered without the deleted raw model response. Local regression
fixtures reproduce the unsafe normalization behavior without personal data.
