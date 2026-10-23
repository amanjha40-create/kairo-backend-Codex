# Resume import quality policy

Scope: new parser results and newly created review sessions. Existing saved skills,
review choices and candidate-confirmed import behavior are unchanged. Parsed Skill
claims add nullable source_section metadata; Career import payloads do not change.

## Defaults

A supported claim is selected only with finite confidence **>= 0.80 and <= 1.0**,
and the existing duplicate policy must permit selection (no match, or the existing
Employment review exception). Missing confidence and confidence below 0.80 remain
visible but unselected. Unsupported/profile suggestions remain unselected.
Candidates can explicitly select valid uncertain claims for import. Exact and
possible Employment matches still retain their existing import safety rules.

Skills recovered directly from labelled source lists receive extraction confidence
0.90 and a source reference. An existing model claim's low/missing confidence is
never upgraded by enrichment. This is extraction confidence, not verified skill level.

## Quality and equivalence

The parser prompt requires source-grounded skill concepts and calibrated confidence.
Deterministic normalization rejects conjunction-led fragments, temporal update prose,
obvious action/subject statements and percentage performance statements. Short metric
labels inferred outside explicit skills lists are rejected. Explicit lists are not
vocabulary restricted. Inferred claims require a recognized concept, verbatim
source evidence with symbol-aware boundaries, and finite confidence >= 0.80.
The conservative inferred-concept vocabulary can omit uncommon skills outside a
labelled list; it is not a global inference ban. No arbitrary prose is accepted
just because a model assigned high confidence.

Section aliases include Professional Experience, Work Experience, Core Competencies,
and Personal Information. Source section is recomputed, not trusted from the model.
Textract words within a LINE are sorted horizontally, not by tiny glyph-top offsets.
Dates, employer/title patterns, metrics and action-result fragments are rejected
even inside an explicit list. Skill list recovery stops at the next section.

NFKC, whitespace, case-folded comparison, terminal punctuation, word-hyphen/space
variants and spaced '&'/'and' variants normalize equivalently. No fuzzy/semantic
similarity merging. First occurrence is retained conservatively. C, C++, C#, .NET,
NET, Node.js and Nodejs remain distinct. Internal 'and' is not a list separator.

## Sanitized reproduction

`tests/fixtures/resume_skill_quality.json` is synthetic, not private resume content.
The three supplied incident examples are represented as model-produced Skill claims
with synthetic confidence 0.05 and synthetic EXPERIENCE source references:

| Example | Old survival/default | New decision |
| --- | --- | --- |
| ticket size | No metric-quality gate; unmatched supported claim selected | context_metric |
| market updates every Friday | No temporal-prose gate; selected regardless of confidence | temporal_prose |
| and local team inputs | No conjunction gate; selected regardless of confidence | conjunction_fragment |

The actual incident's source sections/confidences and 77/76 totals have NOT been
retrieved or inferred. The fixtures prove pipeline behavior, not private incident metadata.

Raw fixture: 24 claims / 18 skills. API47 normalization: 25 claims / 19 skills
(including a spurious NET enrichment); all 25 would be selected if unmatched.
Current section-aware normalization: 13 claims / 7 skills; 11 selected, 2 visible
unselected. The two unsupported inferred skills are no longer retained.
Every Employment/Education/Certification/Project claim is retained. No resume is
automatically imported, no existing record rewritten and no Production deployment.

## Real-CV section regression (2026-10-24)

The private supplied PDF reproduced 54 skills / 62 typed claims / 62 confidence-
eligible defaults with Nova 2 Lite and the pre-fix parser. Other typed claims were
4 employment, 3 education, 1 certification, and 0 projects. No private source
document or model output is committed. The synthetic structure is in
`tests/fixtures/resume_section_quality.json`.

Replaying that same model response after correcting OCR ordering and classification
produces 12 skills / 20 typed claims / 20 confidence-eligible defaults, retaining
10 explicit entries and 2 supported concepts. 43 old skill strings are removed
and the correctly ordered explicit phrase is recovered. This is a controlled
replay comparison, not a claim that a new model invocation is deterministic.
Actual review selection still depends on existing Career duplicate checks.

All other claim counts are preserved. This does not certify the semantic accuracy
of every Education mapping in a multi-column CV; that remains candidate-reviewed.
