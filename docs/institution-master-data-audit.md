# Shared institution master-data integration: schema decision gate

Audit date: 23 October 2026. Backend baseline: 3ed3c2f736bfa81e7924a8cded506ccbc8c1d3b1.
No application, schema, deployment or Production data changes in this audit.

## Shared semantic contract

Use GET /api/v1/catalogues/institutions for optional name suggestions across
Candidate, Resume, Admin and organization clients. It is India higher education
snapshot master data, not a global registry or evidence of identity, affiliation,
accreditation, authorization or verification status. The current IDs identify
snapshot records; cross-version identity continuity would require explicit alias
mapping and must not be assumed from a hash that includes source address fields.

Keep institution_name as the display/history snapshot and manual fallback.
No automatic matching/backfill of legacy records; no catalogue-only validation.
Manual text changes must clear any previously selected catalogue association.
Unavailable search, non-Indian institutions and absent results must retain typed
and saved text. Do not silently replace Resume extraction with a suggested name.
Selection requires user action; search/autocomplete itself does not mutate data.

## Surface inventory

| Surface | Located code / contract | Integration disposition |
| --- | --- | --- |
| Candidate web / Android Education create/edit | src/routes/add-education.tsx, edit-education.tsx; educations.types.ts | Shared autocomplete with manual fallback; preserve edited/saved text. |
| iOS Career Education | CareerMutationSheetView.swift, CareerMutationState.swift, CareerDTOs.swift | Replace name-entry widget with optional catalogue suggestions, retain name binding and manual mode. |
| iOS manual onboarding | ManualProfileScreenView.swift, ManualProfileFlowState.swift, ManualProfileMapper.swift | Same selection policy; no extra mandatory onboarding requirement. |
| Resume web / Android claim editor | features/resume/components/ReviewItemCard.tsx | Education claim institution field only; preserve original extraction and reviewed edit separately. |
| iOS Resume | ResumeImportMapper.swift and generic review field renderer | Same Education editor semantics; do not change parser output or auto-select matches. |
| Backend Resume import | resume_review_service.py create/update Education; resume_duplicate_service.py | Currently persists institution_name only. Optional ID must survive review/import/update deliberately, not as an unvalidated JSON extra. |
| Admin assisted Career | AdminCareerMutationRequest and canonical Education service contracts | Use same catalogue for Education entry; preserve provenance and audit attribution. |
| Admin institution organization creation | AdminOrganizationCreateRequest / organizations.name | Suggestions only for institution-type organizations; do not replace legal/display names or employer entries indiscriminately. |
| Admin verification review | features/admin/runtime/verification-review.production.ts; directory service | Preserve submitted claim text; no editable picker needed in read-only evidence displays. |
| HR verification/report | hr_v2_service._education_items; HR report schemas | Read-only Education projection, not a new institution entry point. Do not alter verified reports by catalogue refresh. |
| Institution workspace signup/settings | organization create/update contracts; institution.signup and settings UI | Optional name suggestion only. Any organization catalogue association needs its own nullable schema field. |
| Institution student/roster profiles | InstitutionPersonProfile.organization_id | Already scoped to a real organization; never replace with catalogue ID or allow student-row reassignment via a picker. |
| Education verification contact/request | verification_request.py; public_institution_verification_service.py | Preserve contact and real organization routing. No routing by catalogue name/ID without separately authorized organization mapping. |
| Public verification / Passport | institution.verify.$token.tsx, public_institution_verification.py, public_passport.py | Historical/display projections only. No picker on a response attestation merely to normalize a name. |

## Confirmed schema gap: report before implementation

educations has institution_name (String512), but no catalogue reference. Its
create/update/response DTOs also contain only the name. Resume import constructs
Education directly from that name. Thus stable-ID persistence through the complete
flow is not currently supported. Do not overload organization_id, institution
workspace UUIDs, student_id, source_claim_id, or verified-record identifiers.

Proposed minimal additive migration, pending approval:

1. Nullable educations.institution_catalogue_id (String80) and
   institution_catalogue_version (String32). Existing rows stay null; no backfill.
2. Add optional fields to Education create/update/read, Resume review Education
   payload/import/update, and Admin assisted Education contracts. Validate explicit
   new selections against the stated snapshot; manual names without IDs remain valid.
3. Preserve stored associations on unrelated legacy-client edits; clear association
   when a legacy client changes the institution name without a new selection. Explicit
   manual selection clears both fields. No network-dependent validation of old rows.
4. Propagate optional metadata through appropriate authorized read projections,
   retaining historical name snapshots. Do not change deduplication/verification
   identity semantics just because a catalogue ID is present.
5. Optional institution-organization association is a separate schema decision:
   nullable organizations catalogue fields, only for institution organizations,
   without uniqueness/ownership inference. Not needed for name-only suggestions.

No fake persistence in preferences, arbitrary metadata, or name-string encoding.
Versioned static catalogue need not become a DB master table for v1. If persistent
cross-snapshot entity IDs are required, design an alias/retirement registry first.

## Audit confidence and remaining gates

Backend and local Android build3 / iOS build10 source paths were inspected. Candidate,
Admin and Institution Desktop checkouts were searched read-only; some broader scans
stalled in cloud-managed paths and were cancelled. HR UI search returned no direct
institution-name entry matches; its backend reporting path is confirmed. These are
located surfaces, not a claim that every current deployed frontend was exhaustively
certified. Confirm canonical frontend worktrees before editing, rather than modifying
historical/release checkouts. Existing picker work was not located in these snapshots.

Required before rollout: approve additive schema scope; complete current frontend
surface audit/wiring; test manual/legacy/unknown-ID/unavailable-catalogue behavior and
permission boundaries; perform client build/UI checks. No client changes, tests or
deployments were performed in this audit. Four-tab IA remains untouched.

CATALOGUE_LICENSING_REVIEW_REQUIRED remains YES. Production deployment remains blocked
until founder review; source archive attribution alone is not redistribution clearance.
