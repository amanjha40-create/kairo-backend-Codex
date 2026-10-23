# Resume import quality policy

Scope: new parser results and newly created review sessions. Existing saved skills,
review choices, API shape and candidate-confirmed import behavior are unchanged.

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
labels inferred outside explicit skills lists are rejected; ambiguous explicit terms
are preserved. This is not a vocabulary allowlist or a word-count cutoff.

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
Corrected normalization: 15 claims / 9 skills; 11 selected, 4 visible unselected.
Every Employment/Education/Certification/Project claim is retained. No resume is
automatically imported, no existing record rewritten and no Production deployment.
