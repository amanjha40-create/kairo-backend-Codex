# Milestone 7G Resume Parser Qualification

Audit date: 2026-09-05

Backend base: `b2a02472cac87d8562ca2c9b485ec436da73c85c`

iOS compatibility baseline: `dce609c3b9077aa8fac9206ca86b1e51ace01005`

This report contains only synthetic test data and sanitized operational facts. No real
Candidate resume, raw provider prompt, credential, token, or private contact value is
stored in the qualification artifacts.

## Canonical pipeline

1. `POST /api/v1/resumes/upload-intent` validates a declared PDF or DOCX, records
   Candidate consent, creates a private S3 object key, and returns a short-lived
   presigned PUT URL.
2. The client uploads directly to the private documents bucket.
3. `POST /api/v1/resumes/{resume_id}/complete-upload` verifies S3 metadata, size,
   MIME type, file signature, and SHA-256 checksum.
4. `POST /api/v1/resumes/{resume_id}/process` creates one durable processing job and
   dispatches `resume.process` through SQS (inline mode remains available for local
   development).
5. PDF input uses asynchronous Amazon Textract document-text detection, including
   scanned/image PDF OCR. DOCX input is extracted deterministically from
   `word/document.xml`; no office process or shell is invoked.
6. Extracted text is passed to Amazon Nova 2 Lite through Amazon Bedrock and validated
   against the versioned `ParsedResumeResult` Pydantic schema.
7. The Candidate creates or reopens a durable review session. Every proposed item is
   initially unselected and unverified. Review supports editing, exclusion, duplicate
   resolution, validation, import planning, cancellation, and recovery.
8. A confirmed import uses a stable client idempotency key, durable batch/result rows,
   authoritative reconciliation, and per-record provenance. Resume content never
   assigns verification status.

The native client polls processing for five minutes, can restore the latest uploaded,
processing, review, or import state after relaunch, and tells the Candidate to return
later rather than fabricating completion when the polling window ends.

## Providers and limits

| Concern | Current behavior |
| --- | --- |
| PDF text/OCR | Asynchronous Textract from private S3; `PARTIAL_SUCCESS` is a failure |
| DOCX | Deterministic ZIP/XML extraction |
| Model | Bedrock, `us.amazon.nova-2-lite-v1:0` in current Staging and Production worker definitions |
| Fallback | None; provider failure is explicit and manually retryable |
| Bedrock timeout | 60 seconds in current deployed definitions; now applied to the SDK client |
| Textract timeout | 600 seconds in current deployed definitions |
| Processing retry | Original attempt plus at most three explicitly requested retries |
| Upload limit | 10,000,000 bytes in current Staging; backend hard ceiling 50,000,000 |
| Parser input limit | Newly bounded to 120,000 extracted characters by default |
| Supported formats | PDF and DOCX only; DOC and standalone images are rejected |
| Page limit | No explicit page-count limit; byte and extracted-character limits apply |
| Malware scanning | No dedicated malware scanner is present; MIME, signature, size, ZIP structure, and checksum validation are present |

Production API processing remains disabled while the Production worker definition is
capable of consuming already-authorized jobs. No Production model, service, or data was
changed during this milestone.

## Extraction contract

- Candidate: name, professional headline, summary, location, profile links, and
  parsed-only email/phone. Candidate email/phone are deliberately excluded from the
  review/import projection.
- Employment: company, role, type, exact or partial dates, current status, work
  arrangement, structured/display location, and description.
- Education: institution, degree, field, dates, current status, and grade.
- Certification: name, issuer, issue/expiry dates, credential ID, and URL.
- Project: name, description, and URL.
- Skill: precise skill name.
- Additional backend claims: internships, freelance work, gig platforms, and portfolio
  links. The current native V1 review intentionally hides these non-MVP segments.

The schema has no separate achievement list or project technologies collection;
employment achievements remain in description text. Internship, freelance, and gig
schemas currently lack partial-date display/precision fields.

## Golden corpus

The deterministic corpus contains 30 fictional resumes and 39 generated documents
(PDF/DOCX), including one-, two-, and three-page layouts; multi-column and table-like
content; OCR noise; current, partial, numeric, and missing dates; promotions and
overlaps; Indian and US conventions; Unicode; certifications, projects, and dense
skills; contact/reference negative evidence; sparse/empty input; malformed URLs; and a
prompt-injection attempt.

Files:

- `tests/fixtures/resume_golden/corpus.json`: source text and machine-readable truth.
- `tests/fixtures/resume_golden/documents/`: generated PDF/DOCX inputs.
- `tests/fixtures/resume_golden/documents/manifest.json`: deterministic sizes and
  SHA-256 hashes.
- `scripts/generate_resume_golden_documents.py`: deterministic generator.
- `scripts/qualify_resume_parser.py`: metric evaluator.

## Measured quality

Both model runs used the current Staging/Production parser model in `us-east-1` and sent
only the synthetic extracted-text fixtures. They did not upload to S3, call Textract,
touch a database or queue, or mutate any deployed environment.

| Metric | Canonical baseline | Hardened result | V1 target |
| --- | ---: | ---: | ---: |
| Overall record recall | 100.00% | 100.00% | Core records >= 95% |
| Overall record precision | 99.24% | 100.00% | Hallucination <= 1% |
| Employment recall | 100.00% | 100.00% | >= 95% |
| Employment precision | 97.06% | 100.00% | >= 99% implied by hallucination target |
| Education recall | 100.00% | 100.00% | >= 95% |
| Education precision | 100.00% | 100.00% | >= 99% implied by hallucination target |
| Certification recall | 100.00% | 100.00% | >= 90% |
| Project recall | 100.00% | 100.00% | >= 90% |
| Skills precision | 100.00% | 100.00% | Precision favored |
| Date accuracy | 92.66% | 92.44% | >= 90% |
| Hallucination rate | 0.76% | 0.00% | <= 1% |
| Duplicate rate | 0.00% | 0.00% | <= 1% |
| Omission rate | 0.00% | 0.00% | Core thresholds above |
| Invalid import acceptance | 1.53% | 0.00% | 0% |
| Catastrophic parse failure | 6.67% | 0.00% | <= 2% |
| Negative-evidence leaks | 2 | 0 | 0 |

The slight aggregate date movement reflects additional correctly recovered claims in
the denominator, not a regression in core Employment/Education extraction. The
remaining misses are partial dates on non-MVP internship/freelance/gig claims whose
current schema supports exact dates only. Employment and Education date accuracy stays
above the launch threshold, and month/year Employment values retain their true
precision rather than inventing a day.

## Proven defects and targeted corrections

| Priority | Proof | Correction |
| --- | --- | --- |
| P0 | Two model outputs returned `warnings: null`, causing schema-level catastrophic failures | Normalize nullable model collections and warnings before validation |
| P0 | The adversarial fixture induced a fictional employer/title | Remove only high-confidence embedded parser directives before the provider call and strengthen untrusted-data instructions |
| P0 | Employment with only company or only role could pass review validation but fail persistence | Require both company and role before Employment import |
| P0 | A queued/extracting/parsing job could remain active forever | Mark an active job stale after the configured interval and allow one bounded explicit retry path |
| P0 | Concurrent process requests could dispatch duplicate work | Lock the owned ResumeDocument row while making the idempotency/retry decision |
| P1 | Editing another field could convert a month/year Employment date into invented boundary-day precision | Keep exact date null and preserve display/precision for partial Employment dates |
| P1 | Bedrock timeout setting was not applied and implicit SDK retry could duplicate a costly call | Apply connect/read timeouts and set one SDK attempt; application retry remains explicit |
| P1 | Provider/model metadata was generic and token usage was not safely observable | Persist accurate provider/model/extractor metadata and log only provider/model/token counts |

No parser rewrite, broad prompt tuning, or iOS schema change was made.

## Truth, privacy, idempotency, and recovery

- All claims remain Candidate-provided, `selected_for_import=false`, self-declared, and
  unverified until a canonical verification workflow acts on them.
- Reference contacts do not become Career records or overwrite Candidate contact data.
- Full resume text and raw model prompts/results are not logged. Runtime logs contain
  identifiers, stage, provider, duration, safe record counts, warning counts, error
  types, and now token counts.
- Review creation/reopening, import double-submit, batch reconciliation, and provenance
  are durable and idempotent; database-backed integration tests cover duplicate-free
  import.
- Failed and stale jobs have explicit terminal failure codes/timestamps. Retry count is
  bounded and an in-flight job is returned rather than redispatched.
- Empty, malformed, unsupported, password-protected/unreadable, Textract failure,
  provider timeout/error, malformed JSON, and schema failure paths remain truthful
  failures—never empty success.

## Storage-retention audit

Both deployed documents buckets use server-side AES-256 encryption and all four S3
public-access blocks. Neither bucket has versioning enabled. The backend writes a
`ResumeDocument.expires_at` value, and explicit Candidate/account deletion removes the
object, but neither source nor the current buckets contain an automated expiry cleanup
or S3 lifecycle rule.

That is a proven retention-enforcement gap requiring a separately reviewed
infrastructure/operations change. It is not silently changed here because a safe fix
must define per-environment retention, cleanup scheduling, database-row semantics, and
failure reconciliation rather than merely deleting objects opportunistically.

## Cost and abuse posture

- Upload size and parser-input size are bounded.
- Processing is durable and deduplicated at the ResumeDocument/job/SQS-consumer layers.
- SDK retries are disabled for the model call; Candidate retry remains explicit and
  bounded.
- Native polling is read-only and does not trigger new provider calls.
- Safe Bedrock input/output/total token counters are now emitted for cost attribution.
- Qualification used 30 baseline plus 30 hardened Nova calls. No qualification
  Textract calls were made because the model-quality measurement deliberately used
  deterministic extracted text.

Cost is usage-dependent. The official references used for planning are the
[Amazon Textract pricing page](https://aws.amazon.com/textract/pricing/), the
[Amazon Bedrock pricing page](https://aws.amazon.com/bedrock/pricing/), and AWS's
[Nova 2 Lite document-processing cost example](https://aws.amazon.com/blogs/machine-learning/pair-nova-2-lite-with-claude-for-cost-optimized-document-processing/).
Operational budgets must use the new measured token counters and actual page counts,
not a corpus-wide guessed dollar total.

## Verification gates completed before checkpoint

- Hardened 30-fixture provider scorecard: pass.
- Focused backend resume/qualification tests: pass.
- Full backend suite with isolated PostgreSQL and Redis: 757 passed.
- Ruff functional checks on all touched files: pass. Repository-wide pre-existing
  formatting debt is intentionally not rewritten by this milestone.
- New qualification files: Ruff formatted.
- Deterministic document regeneration: byte-for-byte manifest match.
- iOS Resume Import mapper/service/state tests: 52 passed.
- Unchanged iOS Staging simulator build: pass.
- iOS source SHA and worktree: unchanged and clean.

## Controlled Staging plan (approval required)

1. Build one immutable image from the checkpoint and verify its embedded commit.
2. Deploy only the Staging API and Resume worker definitions; preserve all existing
   environment and secret bindings. Do not alter Production.
3. Read-only audit `resumeqa@kairoid.com`; if it is absent, valuable, or unsuitable,
   stop and propose a purpose-built disposable Candidate rather than creating one.
4. Establish exact Career/Passport/verification/resume/S3 baselines and cleanup scope.
5. Through the native Staging app, run exactly three synthetic inputs: simple PDF,
   complex multi-role PDF, and OCR/noisy scanned-style PDF.
6. For each, verify upload, processing, durable recovery, review, edit/remove,
   validation, single import, Career projection, Passport truth, and no duplicate on
   retry/re-entry.
7. Delete only the exact synthetic imports, Resume rows, and S3 objects after proof;
   verify the actor and all unrelated Staging state return to baseline.

No Staging deployment or data mutation is authorized by this checkpoint report.
