# India higher-education catalogue v1

Local backend implementation only. No deployment, database migration, mobile or
Admin UI modification. Current clients require explicit picker wiring; they do
not automatically consume this new endpoint.

GET /api/v1/catalogues/institutions?q=college&state=Gujarat&limit=20&offset=0

Frozen client request: `search` (string, max160, default empty), `state` and
`district` (strings, max100 each, default empty), `page` (1..2001, default1),
`limit` (1..50, default20). Compatibility aliases: `q` for search and `offset`
(0..100000) instead of page. Supplying page with offset, or conflicting q/search,
returns422. Offset-based responses report floor(offset/limit)+1 as page.

Response200 shape:

```json
{
  "version": "india-he-v1",
  "scope": "India higher education; incomplete historical snapshot",
  "available": true,
  "manual_entry_allowed": true,
  "fallback_label": "Institution not listed / Enter manually",
  "items": [{"id": "<stable snapshot ID>", "name": "<source name>",
             "state": "<state>", "district": "<district>", "city": "<city>"}],
  "total": 1, "limit": 20, "offset": 0, "page": 1
}
```

`total` is the filtered match count before pagination. Empty query/no matches
returns an empty items array. Missing/invalid bundled catalogue returns200 with
available=false, empty items and manual_entry_allowed=true. No internal source
IDs, addresses, hashes of credentials, or database identifiers are returned.

This public, read-only endpoint shares the same suggestions with Candidate iOS,
Android and Admin. Query length <=160, page size 1..50, offset 0..100000. State and
district are optional exact normalized filters. Search is case-insensitive,
punctuation-insensitive, token-substring matching; exact/prefix name matches rank
first. It is not fuzzy matching or an accreditation/verification service.

## Client contract

- Show name plus city/district/state to distinguish institutions.
- Show suggestions only when searching; blank input returns no suggestions.
- Keep "Institution not listed / Enter manually" available at all times.
- On API errors/unavailability, keep the typed/saved value and manual entry.
- Choosing a suggestion supplies its display name to existing institution_name.
- Never coerce existing manual or Resume-extracted names into catalogue matches.
- Existing Education/Resume/Admin text-field write contracts remain unchanged.
- IDs identify this snapshot, not registered KairoID organizations or verified AISHE IDs.
- No navigation or four-tab changes are required by the endpoint.

## Input and reproducibility

Run from repository root:

    PYTHONPATH=. python scripts/import_institution_catalogue.py /path/colleges-api-master.zip

Only colleges-api-master/data/colleges.csv is read, never SQL/Go/web assets.
43,121 input rows, zero rejected, two clearly equivalent rows removed, 43,119
suggestions. Addresses/postcodes participate in equivalence and ID generation but
are not shipped as suggestion fields. Source IDs remain in the local data asset.
Whitespace/NFKC and safe comma spacing normalized; a small common-word casing
map preserves acronyms/proper-name casing. Full name AND all location/address
fields must agree after case folding to deduplicate. Distinct addresses survive.
No institution is invented or inferred. Source/CSV checksums and counts are stored
in app/data/institutions_india_v1.json. Docker's existing COPY app includes it.

The archive README attributes the data to the data.gov.in AISHE survey. This claim
has not been independently verified; the survey year is unknown and the archived
CSV timestamp is February 2023. Coverage is India-focused higher education, not
all Indian institutions, schools, or a global registry; entries may be stale.
No explicit licence file accompanies this archive. Review redistribution rights
and attribution requirements before release; local ingestion is not legal clearance.

Archive inspection found no licence file, explicit attribution requirement or
redistribution terms. The README's stated upstream reference is
`data.gov.in/catalog/institutions-aishe-survey`; its public-availability statement
does not establish redistribution rights. `Dump20221218.sql` suggests a December
2022 export but does not establish the CSV's survey vintage. Snapshot version is
`india-he-v1`; individual IDs hash normalized full source fields deterministically.
CATALOGUE_LICENSING_REVIEW_REQUIRED=YES. Committing is authorized; Production
deployment remains blocked until founder licensing review is complete.

## Validation boundaries

Backend tests cover loading, normalization, conservative deduplication, search,
pagination, bounds, manual values and unavailable-data fallback. Existing Education
and Resume regression tests validate unchanged write/read contracts. No client UI
or simulator certification is claimed: frontend wiring remains separate scope.

Local focused performance sanity (23 October 2026, one run, no network): cold
load/index185.39ms; exact6.87ms; partial21.81ms; state14.54ms; district13.15ms;
page2 offset22.73ms. Warm searches returned1,25833,1517,116,25833 total matches
respectively. These measurements support normal debounced mobile search usage,
not a production latency SLA or concurrency/load certification.
# Optional Education provenance (DB095)

Education create/update/response and Resume Education review claims now accept
`institution_catalogue_id` (nullable string, maximum 80 characters) and
`institution_catalogue_version` (nullable string, maximum 32 characters).
`institution_name` remains the display value. Both metadata fields may be null;
manual and legacy institutions remain valid without a catalogue lookup.

Explicit selections must supply the exact name, ID and version returned by
`GET /api/v1/catalogues/institutions`. Unknown/mismatched selections return
`invalid_institution_selection`; catalogue loading failure permits manual entry
and returns `institution_catalogue_unavailable` only for new linked selections.
No name or fuzzy matching automatically creates a link.

Changing the name without a new selection clears both fields, including when a
full-form client echoes the previous selection. Unrelated Candidate/Admin PATCH
updates preserve the selection. Explicitly sending both fields null clears it.
Resume parser-derived names remain unlinked; explicit review selections survive
draft edits and Career import. Admin-assisted Education uses the same resolver.

Migration 095 adds two nullable columns to `educations`, with no default,
backfill, index, foreign key, organization link or routing change. Apply 095
before deploying the new ORM. Old API clients may omit both fields. Stop new
code before downgrading; downgrade removes only these provenance columns.

Passport, HR and verification continue using submitted institution names.
Catalogue IDs never identify an organization or select a verification route.
Client picker wiring and physical/simulator validation remain separate work.
The existing licensing review gate still blocks Production catalogue deployment.
