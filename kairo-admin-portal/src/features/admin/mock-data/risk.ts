/**
 * Admin — Risk & Trust & Safety mock data.
 *
 * Deterministic seed for the Risk Center and Investigation workspace.
 * IDs cross-link to existing verification cases, users and organizations
 * so investigations can navigate into related modules.
 *
 * NEVER mutate this data at runtime; session-only overlays live in
 * `workflow/use-investigation-session.ts`.
 */

import { mockVerificationCases } from "./verification-cases";
import { mockUsers } from "./users";

// --- Frozen NOW (hour-aligned) ---
const NOW = new Date(Math.floor(Date.now() / 3_600_000) * 3_600_000);
function ago(days: number, hours = 0): string {
  const d = new Date(NOW);
  d.setUTCHours(d.getUTCHours() - hours);
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString();
}

// =====================================================================
// Enums & labels
// =====================================================================

export type RiskLevel = "critical" | "high" | "medium" | "low";
export const RISK_LEVEL_LABEL: Record<RiskLevel, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
};

export type InvestigationStatus =
  | "open"
  | "in_review"
  | "pending_evidence"
  | "pending_ts_review"
  | "escalated"
  | "resolved_action_taken"
  | "resolved_no_action"
  | "closed_duplicate";
export const INVESTIGATION_STATUS_LABEL: Record<InvestigationStatus, string> = {
  open: "Open",
  in_review: "In review",
  pending_evidence: "Pending evidence",
  pending_ts_review: "Pending Trust & Safety review",
  escalated: "Escalated",
  resolved_action_taken: "Resolved — action taken",
  resolved_no_action: "Resolved — no action",
  closed_duplicate: "Closed — duplicate",
};

export const RESOLVED_STATUSES: InvestigationStatus[] = [
  "resolved_action_taken",
  "resolved_no_action",
  "closed_duplicate",
];

export type RiskCategory =
  | "identity_mismatch"
  | "possible_duplicate_identity"
  | "suspicious_document"
  | "document_tampering"
  | "conflicting_employment_claims"
  | "conflicting_education_claims"
  | "multiple_accounts"
  | "rapid_account_creation"
  | "suspicious_login_activity"
  | "high_verification_failure_rate"
  | "manual_investigation"
  | "other";
export const RISK_CATEGORY_LABEL: Record<RiskCategory, string> = {
  identity_mismatch: "Identity mismatch",
  possible_duplicate_identity: "Possible duplicate identity",
  suspicious_document: "Suspicious document",
  document_tampering: "Document tampering",
  conflicting_employment_claims: "Conflicting employment claims",
  conflicting_education_claims: "Conflicting education claims",
  multiple_accounts: "Multiple accounts",
  rapid_account_creation: "Rapid account creation",
  suspicious_login_activity: "Suspicious login activity",
  high_verification_failure_rate: "High verification failure rate",
  manual_investigation: "Manual investigation",
  other: "Other",
};

export type SubjectKind = "user" | "organization" | "case";
export const SUBJECT_KIND_LABEL: Record<SubjectKind, string> = {
  user: "User",
  organization: "Organization",
  case: "Verification case",
};

export type SignalSeverity = "critical" | "high" | "medium" | "low" | "info";
export const SIGNAL_SEVERITY_LABEL: Record<SignalSeverity, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
  info: "Informational",
};

export type SignalConfidence = "high" | "medium" | "low";
export const SIGNAL_CONFIDENCE_LABEL: Record<SignalConfidence, string> = {
  high: "High confidence",
  medium: "Medium confidence",
  low: "Low confidence",
};

export type SignalSource =
  | "system_rule"
  | "pattern_match"
  | "reviewer_report"
  | "external_integration"
  | "candidate_reported"
  | "employer_reported";
export const SIGNAL_SOURCE_LABEL: Record<SignalSource, string> = {
  system_rule: "Deterministic rule",
  pattern_match: "Pattern match",
  reviewer_report: "Reviewer report",
  external_integration: "External integration",
  candidate_reported: "Candidate-reported",
  employer_reported: "Employer-reported",
};

export type SignalStatus = "active" | "investigating" | "mitigated" | "dismissed";
export const SIGNAL_STATUS_LABEL: Record<SignalStatus, string> = {
  active: "Active",
  investigating: "Investigating",
  mitigated: "Mitigated",
  dismissed: "Dismissed",
};

export type DocumentAnomalyKind =
  | "metadata_mismatch"
  | "expired_document"
  | "extraction_mismatch"
  | "low_ocr_confidence"
  | "manual_review_required"
  | "possible_manipulation"
  | "missing_pages"
  | "unreadable_upload";
export const DOCUMENT_ANOMALY_LABEL: Record<DocumentAnomalyKind, string> = {
  metadata_mismatch: "Metadata mismatch",
  expired_document: "Expired document",
  extraction_mismatch: "Extraction vs. claim mismatch",
  low_ocr_confidence: "Low OCR confidence",
  manual_review_required: "Manual review required",
  possible_manipulation: "Possible manipulation",
  missing_pages: "Missing pages",
  unreadable_upload: "Unreadable upload",
};

export type RecommendedActionKind =
  | "request_manual_review"
  | "escalate_investigation"
  | "mark_low_risk"
  | "prepare_account_restriction"
  | "prepare_account_restoration"
  | "prepare_trust_safety_review"
  | "prepare_law_enforcement_review";
export const RECOMMENDED_ACTION_LABEL: Record<RecommendedActionKind, string> = {
  request_manual_review: "Request manual review",
  escalate_investigation: "Escalate investigation",
  mark_low_risk: "Mark as low risk",
  prepare_account_restriction: "Prepare account restriction",
  prepare_account_restoration: "Prepare account restoration",
  prepare_trust_safety_review: "Prepare Trust & Safety review",
  prepare_law_enforcement_review: "Prepare law-enforcement review",
};

export type NoteCategory = "evidence" | "risk" | "decision" | "escalation" | "general";
export const NOTE_CATEGORY_LABEL: Record<NoteCategory, string> = {
  evidence: "Evidence",
  risk: "Risk",
  decision: "Decision",
  escalation: "Escalation",
  general: "General",
};

export type InvestigationEventKind =
  | "created"
  | "signal_detected"
  | "note_added"
  | "evidence_added"
  | "status_changed"
  | "assignment_changed"
  | "escalated"
  | "recommended_action"
  | "resolution";
export const EVENT_KIND_LABEL: Record<InvestigationEventKind, string> = {
  created: "Investigation created",
  signal_detected: "Risk signal detected",
  note_added: "Note added",
  evidence_added: "Evidence added",
  status_changed: "Status changed",
  assignment_changed: "Assignment changed",
  escalated: "Escalated",
  recommended_action: "Recommended action prepared",
  resolution: "Resolution recorded",
};

// =====================================================================
// Interfaces
// =====================================================================

export interface RiskSignal {
  id: string;
  title: string;
  explanation: string; // WHY this signal exists — never opaque
  severity: SignalSeverity;
  confidence: SignalConfidence;
  source: SignalSource;
  status: SignalStatus;
  createdAt: string;
  relatedEvidenceIds?: string[];
}

export interface DocumentAnomaly {
  id: string;
  kind: DocumentAnomalyKind;
  documentLabel: string;
  detail: string;
  relatedCaseId?: string;
  detectedAt: string;
  reviewedAt?: string;
}

export interface DuplicateReview {
  candidateA: {
    userId: string;
    displayName: string;
    email: string;
    joinedAt: string;
    location?: string;
  };
  candidateB: {
    userId: string;
    displayName: string;
    email: string;
    joinedAt: string;
    location?: string;
  };
  confidencePct: number;
  matchingFields: string[];
  differences: string[];
  sharedIdentifiers: string[];
  sharedPhone?: string;
  sharedEmailDomain?: string;
  sharedDocumentIds: string[];
  sharedOrganizationIds: string[];
}

export interface EvidenceRef {
  id: string;
  kind: "log" | "document" | "communication" | "case" | "system_report" | "screenshot";
  label: string;
  detail?: string;
  addedAt: string;
  relatedCaseId?: string;
}

export interface InvestigationNote {
  id: string;
  at: string;
  actor: string;
  actorRole: string;
  body: string;
  category: NoteCategory;
  sessionOnly?: true;
}

export interface InvestigationTimelineEvent {
  id: string;
  at: string;
  kind: InvestigationEventKind;
  actor: string;
  detail: string;
  sessionOnly?: true;
}

export interface RecommendedAction {
  kind: RecommendedActionKind;
  rationale: string;
}

export interface Investigation {
  id: string; // internal id (never exposed as identifier)
  reference: string; // RSK-24001
  category: RiskCategory;
  reason: string; // one-line
  summary: string; // paragraph
  riskLevel: RiskLevel;
  status: InvestigationStatus;
  priority: "critical" | "high" | "normal";
  owner: string; // "Aman Jha" | "Trust & Safety" | "Unassigned"
  subject: {
    kind: SubjectKind;
    id: string; // user id / org id / case id
    displayName: string;
    reference?: string; // KVR-... or ORG-...
  };
  country?: string;
  verificationType?: string;
  createdAt: string;
  updatedAt: string;
  escalated: boolean;
  signals: RiskSignal[];
  relatedUserIds: string[];
  relatedCaseIds: string[];
  relatedOrganizationIds: string[];
  documentAnomalies: DocumentAnomaly[];
  duplicateReview?: DuplicateReview;
  evidence: EvidenceRef[];
  notes: InvestigationNote[];
  timeline: InvestigationTimelineEvent[];
  recommendedActions: RecommendedAction[];
}

// =====================================================================
// Seed
// =====================================================================

// Small helper for pulling deterministic subject displays from users.
function userById(id: string) {
  return mockUsers.find((u) => u.id === id);
}
function caseById(id: string) {
  return mockVerificationCases.find((c) => c.id === id);
}

function refFor(n: number): string {
  return `RSK-${(24000 + n).toString()}`;
}

const AMAN = "Aman Jha";
const TS = "Trust & Safety";
const OPS = "Operations Reviewer";

// ---- Investigations ----
const RAW: Investigation[] = [
  {
    id: "inv-001",
    reference: refFor(1),
    category: "identity_mismatch",
    reason: "Selfie liveness failed twice; ID doc name differs from account name",
    summary:
      "Candidate submitted an ID whose printed name does not match the account name. Two liveness checks failed within 20 minutes. Onboarding is blocked at identity verification.",
    riskLevel: "high",
    status: "in_review",
    priority: "high",
    owner: AMAN,
    subject: {
      kind: "user",
      id: "cand-104",
      displayName: userById("cand-104")?.fullName ?? "Lena Fischer",
      reference: userById("cand-104")?.displayId,
    },
    country: "AT",
    verificationType: "identity",
    createdAt: ago(2, 4),
    updatedAt: ago(0, 3),
    escalated: false,
    signals: [
      {
        id: "sig-001a",
        title: "Selfie liveness failed twice within 20 minutes",
        explanation:
          "The onboarding liveness check returned 'failed' for two attempts submitted 12 minutes apart. This meets the deterministic threshold of ≥2 failed attempts within one hour.",
        severity: "high",
        confidence: "high",
        source: "system_rule",
        status: "active",
        createdAt: ago(2, 4),
      },
      {
        id: "sig-001b",
        title: "ID document name does not match account name",
        explanation:
          "OCR extracted 'Lena FISCHERBAUER' from the government ID while the account name is 'Lena Fischer'. Rule requires either an exact match or a documented alias.",
        severity: "medium",
        confidence: "medium",
        source: "system_rule",
        status: "active",
        createdAt: ago(2, 4),
      },
    ],
    relatedUserIds: ["cand-104"],
    relatedCaseIds: ["vc-004"],
    relatedOrganizationIds: ["org-14"],
    documentAnomalies: [
      {
        id: "doc-anom-001",
        kind: "metadata_mismatch",
        documentLabel: "Government ID (front)",
        detail: "Extracted family name differs from account family name. No alias declared.",
        relatedCaseId: "vc-004",
        detectedAt: ago(2, 4),
      },
    ],
    evidence: [
      { id: "ev-001a", kind: "log", label: "Onboarding liveness log", addedAt: ago(2, 4) },
      {
        id: "ev-001b",
        kind: "document",
        label: "Government ID upload",
        addedAt: ago(2, 4),
        relatedCaseId: "vc-004",
      },
    ],
    notes: [
      {
        id: "note-001a",
        at: ago(1, 6),
        actor: AMAN,
        actorRole: "Operations Lead",
        body: "Requested candidate to submit a passport rather than the national ID to resolve the family-name discrepancy.",
        category: "evidence",
      },
    ],
    timeline: [
      {
        id: "tl-001a",
        at: ago(2, 4),
        kind: "created",
        actor: "System",
        detail: "Investigation opened from onboarding rule",
      },
      {
        id: "tl-001b",
        at: ago(2, 4),
        kind: "signal_detected",
        actor: "System",
        detail: "Liveness failure ×2",
      },
      {
        id: "tl-001c",
        at: ago(1, 6),
        kind: "note_added",
        actor: AMAN,
        detail: "Evidence note added",
      },
      {
        id: "tl-001d",
        at: ago(0, 3),
        kind: "status_changed",
        actor: AMAN,
        detail: "Moved to In review",
      },
    ],
    recommendedActions: [
      {
        kind: "request_manual_review",
        rationale: "Await candidate re-submission with passport before further action.",
      },
    ],
  },
  {
    id: "inv-002",
    reference: refFor(2),
    category: "possible_duplicate_identity",
    reason: "Two accounts share phone number and matching identity fields",
    summary:
      "Accounts cand-107 (Daniel Kim) and cand-121 (Tomás Silva) share the same phone number and use the same document reference. Confidence is high but locations and names differ.",
    riskLevel: "critical",
    status: "pending_ts_review",
    priority: "critical",
    owner: TS,
    subject: {
      kind: "user",
      id: "cand-107",
      displayName: userById("cand-107")?.fullName ?? "Daniel Kim",
      reference: userById("cand-107")?.displayId,
    },
    verificationType: "identity",
    createdAt: ago(5, 0),
    updatedAt: ago(0, 8),
    escalated: true,
    signals: [
      {
        id: "sig-002a",
        title: "Same phone number on two active-history accounts",
        explanation:
          "Phone '+82 2 5550 7788' is registered on both cand-107 and cand-121. Deterministic duplicate-phone rule flags identity review.",
        severity: "critical",
        confidence: "high",
        source: "system_rule",
        status: "active",
        createdAt: ago(5, 0),
      },
      {
        id: "sig-002b",
        title: "Shared document reference across accounts",
        explanation:
          "The government ID reference number is identical across the two accounts within a 45-day window.",
        severity: "high",
        confidence: "high",
        source: "pattern_match",
        status: "investigating",
        createdAt: ago(5, 0),
      },
      {
        id: "sig-002c",
        title: "Divergent employment history",
        explanation:
          "The two accounts declare different employers and countries — this weakens (but does not eliminate) the duplicate hypothesis.",
        severity: "low",
        confidence: "medium",
        source: "pattern_match",
        status: "active",
        createdAt: ago(5, 0),
      },
    ],
    relatedUserIds: ["cand-107", "cand-121"],
    relatedCaseIds: [],
    relatedOrganizationIds: [],
    documentAnomalies: [],
    duplicateReview: {
      candidateA: {
        userId: "cand-107",
        displayName: userById("cand-107")?.fullName ?? "Daniel Kim",
        email: userById("cand-107")?.email ?? "daniel.kim@example.com",
        joinedAt: userById("cand-107")?.joinedAt ?? ago(60),
        location: userById("cand-107")?.location,
      },
      candidateB: {
        userId: "cand-121",
        displayName: userById("cand-121")?.fullName ?? "Tomás Silva",
        email: userById("cand-121")?.email ?? "tomas.silva@example.com",
        joinedAt: userById("cand-121")?.joinedAt ?? ago(100),
        location: userById("cand-121")?.location,
      },
      confidencePct: 82,
      matchingFields: ["Phone number", "Government ID reference", "Device fingerprint (partial)"],
      differences: ["Full name", "Country", "Employer", "Preferred language"],
      sharedIdentifiers: ["+82 2 5550 7788", "ID ref ends ★★★1042"],
      sharedPhone: "+82 2 5550 7788",
      sharedEmailDomain: "example.com",
      sharedDocumentIds: ["gov-id-ref-1042"],
      sharedOrganizationIds: [],
    },
    evidence: [
      {
        id: "ev-002a",
        kind: "system_report",
        label: "Duplicate-phone rule output",
        addedAt: ago(5, 0),
      },
      {
        id: "ev-002b",
        kind: "log",
        label: "Session fingerprints (24h window)",
        addedAt: ago(5, 0),
      },
    ],
    notes: [
      {
        id: "note-002a",
        at: ago(3, 0),
        actor: TS,
        actorRole: "Trust & Safety",
        body: "Both accounts are currently inactive/disabled. Waiting on candidate response to reconciliation email.",
        category: "risk",
      },
    ],
    timeline: [
      {
        id: "tl-002a",
        at: ago(5, 0),
        kind: "created",
        actor: "System",
        detail: "Duplicate-phone rule opened investigation",
      },
      {
        id: "tl-002b",
        at: ago(5, 0),
        kind: "signal_detected",
        actor: "System",
        detail: "Shared identifiers",
      },
      {
        id: "tl-002c",
        at: ago(4, 0),
        kind: "assignment_changed",
        actor: AMAN,
        detail: "Assigned to Trust & Safety",
      },
      {
        id: "tl-002d",
        at: ago(2, 0),
        kind: "escalated",
        actor: TS,
        detail: "Escalated for review",
      },
    ],
    recommendedActions: [
      {
        kind: "prepare_trust_safety_review",
        rationale:
          "Deterministic duplicate rule met; requires human confirmation before restriction.",
      },
      {
        kind: "escalate_investigation",
        rationale: "Critical severity signals across two accounts.",
      },
    ],
  },
  {
    id: "inv-003",
    reference: refFor(3),
    category: "suspicious_document",
    reason: "Extracted employment dates differ from declared claim",
    summary:
      "The offer letter uploaded for the Northwind Analytics claim extracts start-date '2019-03-01', but the candidate declared '2018-01-15'. OCR confidence on the date field is medium.",
    riskLevel: "medium",
    status: "in_review",
    priority: "high",
    owner: AMAN,
    subject: {
      kind: "case",
      id: "vc-001",
      displayName: caseById("vc-001")?.candidateName ?? "Jonas Weiss",
      reference: caseById("vc-001")?.reference,
    },
    country: "DE",
    verificationType: "employment",
    createdAt: ago(1, 8),
    updatedAt: ago(0, 5),
    escalated: false,
    signals: [
      {
        id: "sig-003a",
        title: "Extraction date does not match declared start date",
        explanation:
          "OCR read '2019-03-01' as start date from the offer letter; candidate declared '2018-01-15'. The delta of 13 months exceeds the ±3-month tolerance rule.",
        severity: "medium",
        confidence: "medium",
        source: "system_rule",
        status: "active",
        createdAt: ago(1, 8),
      },
    ],
    relatedUserIds: ["cand-101"],
    relatedCaseIds: ["vc-001"],
    relatedOrganizationIds: ["org-11"],
    documentAnomalies: [
      {
        id: "doc-anom-003",
        kind: "extraction_mismatch",
        documentLabel: "Offer letter (Northwind Analytics)",
        detail: "Extracted start date '2019-03-01' vs. declared '2018-01-15'.",
        relatedCaseId: "vc-001",
        detectedAt: ago(1, 8),
      },
      {
        id: "doc-anom-003b",
        kind: "low_ocr_confidence",
        documentLabel: "Offer letter (Northwind Analytics)",
        detail: "Date field OCR confidence 0.62 (below 0.8 threshold).",
        relatedCaseId: "vc-001",
        detectedAt: ago(1, 8),
      },
    ],
    evidence: [
      {
        id: "ev-003a",
        kind: "document",
        label: "Offer letter PDF",
        addedAt: ago(1, 8),
        relatedCaseId: "vc-001",
      },
      { id: "ev-003b", kind: "system_report", label: "OCR extraction JSON", addedAt: ago(1, 8) },
    ],
    notes: [],
    timeline: [
      {
        id: "tl-003a",
        at: ago(1, 8),
        kind: "created",
        actor: "System",
        detail: "Extraction mismatch rule opened investigation",
      },
      {
        id: "tl-003b",
        at: ago(0, 5),
        kind: "status_changed",
        actor: AMAN,
        detail: "Moved to In review",
      },
    ],
    recommendedActions: [
      {
        kind: "request_manual_review",
        rationale: "Ask candidate to reconcile declared vs. extracted start date before decision.",
      },
    ],
  },
  {
    id: "inv-004",
    reference: refFor(4),
    category: "document_tampering",
    reason: "Possible manipulation on degree certificate PDF metadata",
    summary:
      "The uploaded degree certificate PDF was modified 4 minutes before upload, and 'Modified By' differs from the issuing institution. This pattern matches a deterministic tampering rule.",
    riskLevel: "critical",
    status: "escalated",
    priority: "critical",
    owner: TS,
    subject: {
      kind: "case",
      id: "vc-006",
      displayName: caseById("vc-006")?.candidateName ?? "Sofia Martins",
      reference: caseById("vc-006")?.reference,
    },
    country: "PT",
    verificationType: "education",
    createdAt: ago(3, 0),
    updatedAt: ago(0, 2),
    escalated: true,
    signals: [
      {
        id: "sig-004a",
        title: "PDF 'Modified' timestamp is 4 minutes before upload",
        explanation:
          "Metadata shows the file was last modified 4 minutes before upload — a rule threshold of <10 minutes with a 'Modified By' change is treated as suspicious.",
        severity: "critical",
        confidence: "high",
        source: "system_rule",
        status: "active",
        createdAt: ago(3, 0),
      },
      {
        id: "sig-004b",
        title: "'Modified By' differs from issuing institution",
        explanation:
          "Metadata Modified-By reads 'Adobe Acrobat Pro 2023 (user: office)'; the institution's official issuance uses 'Instituto Superior de Lisboa – Registrar'.",
        severity: "high",
        confidence: "medium",
        source: "system_rule",
        status: "active",
        createdAt: ago(3, 0),
      },
    ],
    relatedUserIds: ["cand-106"],
    relatedCaseIds: ["vc-006"],
    relatedOrganizationIds: [],
    documentAnomalies: [
      {
        id: "doc-anom-004",
        kind: "possible_manipulation",
        documentLabel: "Degree certificate PDF",
        detail: "Metadata mismatch and short modify→upload window.",
        relatedCaseId: "vc-006",
        detectedAt: ago(3, 0),
      },
    ],
    evidence: [
      {
        id: "ev-004a",
        kind: "document",
        label: "Degree certificate PDF",
        addedAt: ago(3, 0),
        relatedCaseId: "vc-006",
      },
      { id: "ev-004b", kind: "system_report", label: "PDF metadata dump", addedAt: ago(3, 0) },
    ],
    notes: [
      {
        id: "note-004a",
        at: ago(2, 0),
        actor: TS,
        actorRole: "Trust & Safety",
        body: "Requested institution verification via registrar channel.",
        category: "escalation",
      },
    ],
    timeline: [
      {
        id: "tl-004a",
        at: ago(3, 0),
        kind: "created",
        actor: "System",
        detail: "Document-tampering rule opened investigation",
      },
      {
        id: "tl-004b",
        at: ago(2, 0),
        kind: "escalated",
        actor: TS,
        detail: "Escalated to Trust & Safety",
      },
    ],
    recommendedActions: [
      {
        kind: "prepare_trust_safety_review",
        rationale:
          "Critical tampering signal requires human confirmation before verification decision.",
      },
      {
        kind: "escalate_investigation",
        rationale: "Multiple high/critical signals on issuance authenticity.",
      },
    ],
  },
  {
    id: "inv-005",
    reference: refFor(5),
    category: "conflicting_employment_claims",
    reason: "Two candidates claim the same senior role at the same employer, overlapping dates",
    summary:
      "cand-103 and cand-118 both declare the 'Engineering Manager' role at Acme Corp with overlapping periods. Only one role of that seniority is typically filled.",
    riskLevel: "medium",
    status: "open",
    priority: "high",
    owner: OPS,
    subject: {
      kind: "organization",
      id: "org-13",
      displayName: "Acme Corp",
      reference: "ORG-13",
    },
    verificationType: "employment",
    createdAt: ago(1, 2),
    updatedAt: ago(1, 0),
    escalated: false,
    signals: [
      {
        id: "sig-005a",
        title: "Overlapping tenure for same senior role",
        explanation:
          "Both accounts claim 'Engineering Manager' at Acme Corp with overlapping declared periods (Jan 2022–present).",
        severity: "high",
        confidence: "medium",
        source: "pattern_match",
        status: "active",
        createdAt: ago(1, 2),
      },
    ],
    relatedUserIds: ["cand-103", "cand-118"],
    relatedCaseIds: ["vc-003"],
    relatedOrganizationIds: ["org-13"],
    documentAnomalies: [],
    evidence: [
      {
        id: "ev-005a",
        kind: "system_report",
        label: "Claim overlap report — Acme Corp",
        addedAt: ago(1, 2),
      },
    ],
    notes: [],
    timeline: [
      {
        id: "tl-005a",
        at: ago(1, 2),
        kind: "created",
        actor: "System",
        detail: "Claim-overlap rule opened investigation",
      },
    ],
    recommendedActions: [
      {
        kind: "request_manual_review",
        rationale: "Contact employer to disambiguate which candidate holds the role.",
      },
    ],
  },
  {
    id: "inv-006",
    reference: refFor(6),
    category: "multiple_accounts",
    reason: "Three accounts on the same device fingerprint",
    summary:
      "Three accounts registered within 48 hours share the same browser fingerprint and IP range. Two are already inactive.",
    riskLevel: "high",
    status: "pending_evidence",
    priority: "high",
    owner: TS,
    subject: {
      kind: "user",
      id: "cand-110",
      displayName: userById("cand-110")?.fullName ?? "Emily Carter",
      reference: userById("cand-110")?.displayId,
    },
    country: "US",
    createdAt: ago(4, 3),
    updatedAt: ago(0, 12),
    escalated: false,
    signals: [
      {
        id: "sig-006a",
        title: "Shared browser fingerprint across 3 accounts",
        explanation:
          "Fingerprint hash matched on 3 accounts opened within 48 hours from the same /24 IP range.",
        severity: "high",
        confidence: "high",
        source: "system_rule",
        status: "active",
        createdAt: ago(4, 3),
      },
    ],
    relatedUserIds: ["cand-110"],
    relatedCaseIds: [],
    relatedOrganizationIds: [],
    documentAnomalies: [],
    evidence: [
      { id: "ev-006a", kind: "log", label: "Session fingerprint export", addedAt: ago(4, 3) },
    ],
    notes: [],
    timeline: [
      {
        id: "tl-006a",
        at: ago(4, 3),
        kind: "created",
        actor: "System",
        detail: "Multi-account rule opened investigation",
      },
    ],
    recommendedActions: [
      {
        kind: "request_manual_review",
        rationale:
          "Confirm whether these are shared-device users or account takeover before restricting.",
      },
    ],
  },
  {
    id: "inv-007",
    reference: refFor(7),
    category: "rapid_account_creation",
    reason: "Burst of 14 accounts from same ASN in under 30 minutes",
    summary:
      "Automated rate rule triggered when 14 accounts registered from the same ASN in 27 minutes. No verifications submitted yet on any of them.",
    riskLevel: "medium",
    status: "in_review",
    priority: "normal",
    owner: OPS,
    createdAt: ago(0, 10),
    updatedAt: ago(0, 4),
    escalated: false,
    subject: {
      kind: "organization",
      id: "asn-cluster-1",
      displayName: "ASN cluster (AS-EXAMPLE-77)",
    },
    signals: [
      {
        id: "sig-007a",
        title: "14 accounts opened from one ASN in 27 minutes",
        explanation:
          "Deterministic rate rule: ≥10 registrations per ASN within 30 minutes. Threshold exceeded.",
        severity: "medium",
        confidence: "high",
        source: "system_rule",
        status: "active",
        createdAt: ago(0, 10),
      },
    ],
    relatedUserIds: [],
    relatedCaseIds: [],
    relatedOrganizationIds: [],
    documentAnomalies: [],
    evidence: [
      { id: "ev-007a", kind: "system_report", label: "ASN burst report", addedAt: ago(0, 10) },
    ],
    notes: [],
    timeline: [
      {
        id: "tl-007a",
        at: ago(0, 10),
        kind: "created",
        actor: "System",
        detail: "Rate rule opened investigation",
      },
    ],
    recommendedActions: [
      {
        kind: "mark_low_risk",
        rationale: "If no verification submitted in 48h, close as low risk.",
      },
    ],
  },
  {
    id: "inv-008",
    reference: refFor(8),
    category: "suspicious_login_activity",
    reason: "Multiple failed logins from three countries in 20 minutes",
    summary:
      "Account cand-107 saw failed login attempts from KR, US and NG within 20 minutes, followed by a password reset request.",
    riskLevel: "high",
    status: "in_review",
    priority: "high",
    owner: AMAN,
    subject: {
      kind: "user",
      id: "cand-107",
      displayName: userById("cand-107")?.fullName ?? "Daniel Kim",
      reference: userById("cand-107")?.displayId,
    },
    country: "KR",
    createdAt: ago(2, 12),
    updatedAt: ago(0, 4),
    escalated: false,
    signals: [
      {
        id: "sig-008a",
        title: "Impossible-travel login attempts",
        explanation:
          "Failed sign-in attempts from KR, US and NG within 20 minutes. Physical travel time between any two locations exceeds elapsed time.",
        severity: "high",
        confidence: "high",
        source: "system_rule",
        status: "active",
        createdAt: ago(2, 12),
      },
      {
        id: "sig-008b",
        title: "Password reset requested immediately after failures",
        explanation:
          "A password reset was requested within 3 minutes of the last failed attempt. Rule flags this as potential takeover attempt.",
        severity: "medium",
        confidence: "high",
        source: "system_rule",
        status: "active",
        createdAt: ago(2, 12),
      },
    ],
    relatedUserIds: ["cand-107"],
    relatedCaseIds: [],
    relatedOrganizationIds: [],
    documentAnomalies: [],
    evidence: [
      { id: "ev-008a", kind: "log", label: "Login attempt log (72h)", addedAt: ago(2, 12) },
    ],
    notes: [],
    timeline: [
      {
        id: "tl-008a",
        at: ago(2, 12),
        kind: "created",
        actor: "System",
        detail: "Impossible-travel rule opened investigation",
      },
    ],
    recommendedActions: [
      {
        kind: "prepare_account_restriction",
        rationale: "Temporary sign-in restriction until candidate confirms recent activity.",
      },
    ],
  },
  {
    id: "inv-009",
    reference: refFor(9),
    category: "high_verification_failure_rate",
    reason: "Employer domain shows 68% verification failure rate over 30 days",
    summary:
      "Outreach to hr@umbrella.example has failed to yield a response on 68% of verification requests over 30 days, well above the 25% threshold.",
    riskLevel: "medium",
    status: "in_review",
    priority: "normal",
    owner: OPS,
    subject: {
      kind: "organization",
      id: "org-14",
      displayName: "Umbrella GmbH",
      reference: "ORG-14",
    },
    verificationType: "employment",
    createdAt: ago(6, 0),
    updatedAt: ago(1, 0),
    escalated: false,
    signals: [
      {
        id: "sig-009a",
        title: "Employer response rate below floor",
        explanation:
          "Response rate on outreach to umbrella.example is 32% (17/53), below the 75% floor. Rule flags for organization review, not for candidate-level restriction.",
        severity: "medium",
        confidence: "high",
        source: "pattern_match",
        status: "active",
        createdAt: ago(6, 0),
      },
    ],
    relatedUserIds: [],
    relatedCaseIds: ["vc-004"],
    relatedOrganizationIds: ["org-14"],
    documentAnomalies: [],
    evidence: [
      {
        id: "ev-009a",
        kind: "system_report",
        label: "30-day outreach report — umbrella.example",
        addedAt: ago(6, 0),
      },
    ],
    notes: [
      {
        id: "note-009a",
        at: ago(2, 0),
        actor: OPS,
        actorRole: "Reviewer",
        body: "Suggest opening a Registry review for alternate verification channels.",
        category: "general",
      },
    ],
    timeline: [
      {
        id: "tl-009a",
        at: ago(6, 0),
        kind: "created",
        actor: "System",
        detail: "Response-rate rule opened investigation",
      },
    ],
    recommendedActions: [
      {
        kind: "request_manual_review",
        rationale: "Add verified backup contact for this employer via Registry.",
      },
    ],
  },
  {
    id: "inv-010",
    reference: refFor(10),
    category: "manual_investigation",
    reason: "Reviewer-reported inconsistency between resume and evidence",
    summary:
      "Reviewer flagged that Marco Bianchi's resume lists a role at 'Acme Corp' that does not appear in any submitted evidence or claim.",
    riskLevel: "low",
    status: "open",
    priority: "normal",
    owner: AMAN,
    subject: {
      kind: "user",
      id: "cand-103",
      displayName: userById("cand-103")?.fullName ?? "Marco Bianchi",
      reference: userById("cand-103")?.displayId,
    },
    country: "IT",
    createdAt: ago(0, 6),
    updatedAt: ago(0, 6),
    escalated: false,
    signals: [
      {
        id: "sig-010a",
        title: "Reviewer-reported resume/evidence mismatch",
        explanation:
          "Filed manually by reviewer during outreach preparation. Marked as low severity pending candidate response.",
        severity: "low",
        confidence: "medium",
        source: "reviewer_report",
        status: "active",
        createdAt: ago(0, 6),
      },
    ],
    relatedUserIds: ["cand-103"],
    relatedCaseIds: ["vc-003"],
    relatedOrganizationIds: ["org-13"],
    documentAnomalies: [],
    evidence: [
      {
        id: "ev-010a",
        kind: "screenshot",
        label: "Resume screenshot — page 2",
        addedAt: ago(0, 6),
      },
    ],
    notes: [],
    timeline: [
      {
        id: "tl-010a",
        at: ago(0, 6),
        kind: "created",
        actor: AMAN,
        detail: "Reviewer opened manual investigation",
      },
    ],
    recommendedActions: [
      { kind: "mark_low_risk", rationale: "Close if candidate clarifies within 7 days." },
    ],
  },
];

export const mockInvestigations: Investigation[] = RAW;

// =====================================================================
// Accessors & metrics
// =====================================================================

export function getInvestigation(id: string): Investigation | undefined {
  return mockInvestigations.find((i) => i.id === id || i.reference === id);
}

export interface RiskMetrics {
  open: number;
  highRiskUsers: number;
  duplicateCandidates: number;
  documentAnomalies: number;
  suspiciousLogins: number;
  pendingTsReview: number;
  recentlyResolved: number;
  escalated: number;
}

export function getRiskMetrics(): RiskMetrics {
  const investigations = mockInvestigations;
  const highRiskUserSet = new Set<string>();
  for (const inv of investigations) {
    if (
      (inv.riskLevel === "high" || inv.riskLevel === "critical") &&
      !RESOLVED_STATUSES.includes(inv.status)
    ) {
      for (const uid of inv.relatedUserIds) highRiskUserSet.add(uid);
      if (inv.subject.kind === "user") highRiskUserSet.add(inv.subject.id);
    }
  }
  const cutoff = Date.now() - 7 * 86_400_000;
  return {
    open: investigations.filter((i) => !RESOLVED_STATUSES.includes(i.status)).length,
    highRiskUsers: highRiskUserSet.size,
    duplicateCandidates: investigations.filter(
      (i) => i.category === "possible_duplicate_identity" && !RESOLVED_STATUSES.includes(i.status),
    ).length,
    documentAnomalies: investigations.reduce((n, i) => n + i.documentAnomalies.length, 0),
    suspiciousLogins: investigations.filter(
      (i) => i.category === "suspicious_login_activity" && !RESOLVED_STATUSES.includes(i.status),
    ).length,
    pendingTsReview: investigations.filter((i) => i.status === "pending_ts_review").length,
    recentlyResolved: investigations.filter(
      (i) => RESOLVED_STATUSES.includes(i.status) && new Date(i.updatedAt).getTime() >= cutoff,
    ).length,
    escalated: investigations.filter((i) => i.escalated && !RESOLVED_STATUSES.includes(i.status))
      .length,
  };
}

export const ALL_INVESTIGATORS: string[] = Array.from(
  new Set(mockInvestigations.map((i) => i.owner)),
).sort();
