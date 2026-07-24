/**
 * Admin Portal — Verification case DETAIL mock data.
 *
 * The queue (`verification-cases.ts`) holds lightweight summaries. This
 * module holds the deep record used by the Case Workspace and exposes
 * `getVerificationCaseDetail(caseId)` as the single retrieval function.
 *
 * BACKEND INTEGRATION NOTE
 * ------------------------
 * When the real case-detail API is ready, replace `getVerificationCaseDetail`
 * with a TanStack Query hook. Do NOT quietly fall back to mock data —
 * an unconfigured admin API should surface loading/empty/error states.
 *
 * Every timestamp here is derived from a frozen NOW, so nothing drifts
 * between renders within a single session.
 */

import type { Priority } from "./types";
import type { AttentionFlag, VerificationCase, VerificationType } from "./verification-cases";
import { mockVerificationCases } from "./verification-cases";

// ---- Frozen reference time (hour-aligned) ----
const NOW = new Date(Math.floor(Date.now() / 3_600_000) * 3_600_000);
function ago(days: number, hours = 0): string {
  const d = new Date(NOW);
  d.setUTCHours(d.getUTCHours() - hours);
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString();
}

// =====================================================================
// Types
// =====================================================================

export type ClaimFieldSource = "candidate" | "kairo_derived" | "verifier_confirmed";

export const CLAIM_SOURCE_LABEL: Record<ClaimFieldSource, string> = {
  candidate: "Provided by candidate",
  kairo_derived: "Matched by Kairo",
  verifier_confirmed: "Confirmed by verifier",
};

export interface ClaimField {
  key: string;
  label: string;
  value: string;
  source: ClaimFieldSource;
  note?: string;
}

export interface VerificationClaim {
  type: VerificationType;
  /** Short human summary shown at the top of the workspace. */
  headline: string;
  createdAt: string;
  claimSource: string;
  fields: ClaimField[];
}

// ---- Evidence ----
export type EvidenceDocType =
  | "offer_letter"
  | "appointment_letter"
  | "experience_letter"
  | "relieving_letter"
  | "payslip"
  | "employee_id"
  | "bank_statement"
  | "tax_document"
  | "degree_certificate"
  | "mark_sheet"
  | "certification_document"
  | "government_id"
  | "platform_screenshot"
  | "reference_letter"
  | "other";

export const EVIDENCE_DOC_LABEL: Record<EvidenceDocType, string> = {
  offer_letter: "Offer letter",
  appointment_letter: "Appointment letter",
  experience_letter: "Experience letter",
  relieving_letter: "Relieving letter",
  payslip: "Payslip",
  employee_id: "Employee ID",
  bank_statement: "Bank statement",
  tax_document: "Tax document",
  degree_certificate: "Degree certificate",
  mark_sheet: "Mark sheet",
  certification_document: "Certification document",
  government_id: "Government identity document",
  platform_screenshot: "Platform screenshot",
  reference_letter: "Reference letter",
  other: "Other supporting evidence",
};

export type EvidenceProcessingState = "uploaded" | "processing" | "processed" | "failed";
export type EvidenceReviewState =
  "not_reviewed" | "reviewed" | "needs_attention" | "unsupported" | "duplicate";

export type ComparisonResult =
  "match" | "partial_match" | "mismatch" | "not_found" | "not_applicable";

export interface EvidenceComparison {
  field: string;
  claimed: string;
  evidence: string;
  result: ComparisonResult;
}

export interface EvidenceExtraction {
  detectedCandidateName?: string;
  detectedOrganization?: string;
  detectedDates?: string[];
  extractedFields: { label: string; value: string; confidence: number }[];
  mismatchWarnings?: string[];
  reviewerNotes?: string;
  processingDetails?: string;
}

export interface EvidenceItem {
  id: string;
  title: string;
  docType: EvidenceDocType;
  filename: string;
  uploadedAt: string;
  source: "candidate_upload" | "verifier_upload" | "admin_upload";
  fileSizeBytes: number;
  pageCount?: number;
  processingStatus: EvidenceProcessingState;
  reviewStatus: EvidenceReviewState;
  extractionSummary?: string;
  attentionFlags: AttentionFlag[];
  candidateNote?: string;
  extraction?: EvidenceExtraction;
  comparisons?: EvidenceComparison[];
}

// ---- Organization resolution ----
export type OrgResolutionState = "resolved" | "suggested_match" | "unresolved" | "duplicate_review";

export interface OrganizationSuggestion {
  id: string;
  name: string;
  domain?: string;
  country?: string;
  confidence: number;
  reason: string;
}

export interface OrganizationResolution {
  candidateEntered: string;
  matched?: {
    id: string;
    canonicalName: string;
    domain?: string;
    website?: string;
    country?: string;
    orgType?: string;
    matchConfidence: number;
    matchReason: string;
    knownChannels: string[];
  };
  state: OrgResolutionState;
  duplicateWarning?: string;
  suggestions: OrganizationSuggestion[];
}

// ---- Verification contact ----
export type ContactState =
  | "unverified"
  | "approved"
  | "previously_successful"
  | "bounced"
  | "inactive"
  | "rejected"
  | "needs_review";

export type ContactSource =
  | "candidate_provided"
  | "organization_registry"
  | "previous_successful_verification"
  | "domain_discovery"
  | "manual_admin_entry";

export const CONTACT_SOURCE_LABEL: Record<ContactSource, string> = {
  candidate_provided: "Candidate provided",
  organization_registry: "Organization registry",
  previous_successful_verification: "Previous successful verification",
  domain_discovery: "Domain discovery",
  manual_admin_entry: "Manual admin entry",
};

export const CONTACT_STATE_LABEL: Record<ContactState, string> = {
  unverified: "Unverified",
  approved: "Approved",
  previously_successful: "Previously successful",
  bounced: "Bounced",
  inactive: "Inactive",
  rejected: "Rejected",
  needs_review: "Needs review",
};

export interface VerificationContact {
  id: string;
  name: string;
  role: string;
  organization: string;
  emailMasked: string;
  phoneMasked?: string;
  source: ContactSource;
  state: ContactState;
  confidence: number;
  lastSuccessfulUse?: string;
  bounceCount: number;
  outreachEligible: boolean;
  internalApprovalStatus: "not_started" | "pending" | "approved" | "rejected";
}

// ---- Communication events ----
export type CommunicationChannel = "email" | "sms" | "internal" | "webhook";
export type CommunicationState =
  | "prepared"
  | "queued"
  | "sent"
  | "delivered"
  | "opened"
  | "acted"
  | "bounced"
  | "failed"
  | "suppressed";

export const COMMUNICATION_STATE_LABEL: Record<CommunicationState, string> = {
  prepared: "Prepared",
  queued: "Queued",
  sent: "Sent",
  delivered: "Delivered",
  opened: "Opened",
  acted: "Acted",
  bounced: "Bounced",
  failed: "Failed",
  suppressed: "Suppressed",
};

export interface CommunicationEvent {
  id: string;
  channel: CommunicationChannel;
  recipientDisplay: string;
  template: string;
  state: CommunicationState;
  at: string;
  actor: string;
  failureReason?: string;
  relatedContactId?: string;
}

// ---- Corrections ----
export type CorrectionState =
  "requested" | "viewed" | "in_progress" | "resubmitted" | "resolved" | "closed";

export const CORRECTION_STATE_LABEL: Record<CorrectionState, string> = {
  requested: "Requested",
  viewed: "Viewed",
  in_progress: "In progress",
  resubmitted: "Resubmitted",
  resolved: "Resolved",
  closed: "Closed",
};

export interface CorrectionRequest {
  id: string;
  requestedBy: string;
  requestedAt: string;
  reason: string;
  fields: string[];
  state: CorrectionState;
  candidateResponse?: string;
  respondedAt?: string;
  attachmentsAdded: number;
  reviewOutcome?: string;
}

// ---- Internal notes ----
export type NoteCategory =
  "general" | "evidence" | "organization" | "contact" | "risk" | "decision_preparation";

export const NOTE_CATEGORY_LABEL: Record<NoteCategory, string> = {
  general: "General",
  evidence: "Evidence",
  organization: "Organization",
  contact: "Contact",
  risk: "Risk",
  decision_preparation: "Decision preparation",
};

export interface InternalNote {
  id: string;
  author: string;
  role: string;
  at: string;
  body: string;
  category: NoteCategory;
  /** Session-only notes are appended in the browser and not persisted. */
  sessionOnly?: boolean;
}

// ---- Attention flags ----
export type AttentionFlagState = "open" | "acknowledged" | "resolved";
export type AttentionSeverity = "low" | "medium" | "high";

export interface AttentionFlagRecord {
  id: string;
  flag: AttentionFlag;
  label: string;
  severity: AttentionSeverity;
  reason: string;
  createdAt: string;
  source: "system" | "admin" | "employer" | "candidate";
  state: AttentionFlagState;
}

// ---- Candidate summary ----
export interface CandidateCaseSummary {
  candidateId: string;
  name: string;
  email: string;
  phoneMasked: string;
  profileType: string;
  signupAt: string;
  onboardingState: string;
  profileCompletionPct: number;
  trustScore: number;
  trustPassportStatus: "not_issued" | "provisional" | "issued" | "revoked";
  employmentRecordCount: number;
  previousVerificationCount: number;
  lastActiveAt: string;
  accountStatus: "active" | "suspended" | "closed";
  riskFlags: string[];
}

// ---- Case timeline ----
export type TimelineEventKind =
  | "case_created"
  | "candidate_submitted"
  | "evidence_uploaded"
  | "processing_result"
  | "assignment_changed"
  | "priority_changed"
  | "organization_match"
  | "contact_approved"
  | "outreach_event"
  | "correction_requested"
  | "candidate_resubmitted"
  | "internal_note_added"
  | "attention_flag_created"
  | "attention_flag_acknowledged"
  | "employer_response"
  | "decision_prepared";

export type ActorSource = "candidate" | "admin" | "employer" | "system" | "integration";

export interface CaseTimelineEvent {
  id: string;
  kind: TimelineEventKind;
  actor: string;
  actorSource: ActorSource;
  at: string;
  description: string;
  relatedEntity?: string;
  metadata?: Record<string, string | number>;
  /** True when the event was appended by a session-only mock action. */
  sessionOnly?: boolean;
}

// ---- Case status meta ----
export interface CaseStatusMeta {
  description: string;
  stage: string;
  slaTargetHours: number;
  nextExpectedAction: string;
}

// ---- Complete detail record ----
export interface VerificationCaseDetail {
  summary: VerificationCase;
  claim: VerificationClaim;
  candidate: CandidateCaseSummary;
  evidence: EvidenceItem[];
  organization: OrganizationResolution;
  contacts: VerificationContact[];
  communications: CommunicationEvent[];
  corrections: CorrectionRequest[];
  notes: InternalNote[];
  flags: AttentionFlagRecord[];
  timeline: CaseTimelineEvent[];
  statusMeta: CaseStatusMeta;
}

// =====================================================================
// Deterministic detail records
// =====================================================================

/** Verified fields for a specific case. Any case not listed here falls back
 *  to a generic detail record derived from its summary. */
const CANDIDATE_BY_CASE: Record<string, CandidateCaseSummary> = {
  "vc-001": {
    candidateId: "cand-101",
    name: "Jonas Weiss",
    email: "jonas.weiss@example.com",
    phoneMasked: "+49 •••• ••34",
    profileType: "Full-time professional",
    signupAt: ago(84),
    onboardingState: "Complete",
    profileCompletionPct: 92,
    trustScore: 74,
    trustPassportStatus: "provisional",
    employmentRecordCount: 3,
    previousVerificationCount: 2,
    lastActiveAt: ago(0, 6),
    accountStatus: "active",
    riskFlags: ["Previous correction"],
  },
  "vc-002": {
    candidateId: "cand-102",
    name: "Priya Shah",
    email: "priya.shah@example.com",
    phoneMasked: "+91 •••• ••88",
    profileType: "Full-time professional",
    signupAt: ago(151),
    onboardingState: "Complete",
    profileCompletionPct: 87,
    trustScore: 68,
    trustPassportStatus: "not_issued",
    employmentRecordCount: 4,
    previousVerificationCount: 3,
    lastActiveAt: ago(0, 2),
    accountStatus: "active",
    riskFlags: [],
  },
  "vc-008": {
    candidateId: "cand-108",
    name: "Ines Duarte",
    email: "ines.duarte@example.com",
    phoneMasked: "+351 •••• ••22",
    profileType: "Full-time professional",
    signupAt: ago(220),
    onboardingState: "Complete",
    profileCompletionPct: 78,
    trustScore: 52,
    trustPassportStatus: "not_issued",
    employmentRecordCount: 5,
    previousVerificationCount: 1,
    lastActiveAt: ago(1, 4),
    accountStatus: "active",
    riskFlags: ["Contact bounced", "Risk review pending"],
  },
};

function defaultCandidate(c: VerificationCase): CandidateCaseSummary {
  return {
    candidateId: c.candidateId,
    name: c.candidateName,
    email: c.candidateEmail,
    phoneMasked: "+•• •••• •• ••",
    profileType: c.verificationType === "identity" ? "Individual" : "Professional",
    signupAt: ago(120),
    onboardingState: "Complete",
    profileCompletionPct: 80,
    trustScore: 60,
    trustPassportStatus: "not_issued",
    employmentRecordCount: 2,
    previousVerificationCount: 1,
    lastActiveAt: ago(1, 0),
    accountStatus: "active",
    riskFlags: [],
  };
}

function buildClaim(c: VerificationCase): VerificationClaim {
  switch (c.verificationType) {
    case "employment":
      return {
        type: "employment",
        headline: `${c.roleOrProgram} at ${c.organizationName}`,
        createdAt: c.submittedAt,
        claimSource: "Candidate onboarding",
        fields: [
          {
            key: "candidate",
            label: "Candidate name",
            value: c.candidateName,
            source: "candidate",
          },
          { key: "org", label: "Organization", value: c.organizationName, source: "kairo_derived" },
          { key: "role", label: "Role / title", value: c.roleOrProgram, source: "candidate" },
          {
            key: "employmentType",
            label: "Employment type",
            value: "Full-time",
            source: "candidate",
          },
          { key: "startDate", label: "Start date", value: "March 3, 2021", source: "candidate" },
          { key: "endDate", label: "End date", value: "Currently employed", source: "candidate" },
          { key: "employeeId", label: "Employee ID", value: "EMP-40912", source: "candidate" },
          { key: "location", label: "Work location", value: "Berlin, DE", source: "candidate" },
          { key: "department", label: "Department", value: "Data Platform", source: "candidate" },
          {
            key: "manager",
            label: "Reporting manager",
            value: "Sabine Keller",
            source: "candidate",
          },
          {
            key: "hrContact",
            label: "HR contact (candidate)",
            value: "hr@northwind.example",
            source: "candidate",
          },
        ],
      };
    case "education":
      return {
        type: "education",
        headline: c.roleOrProgram,
        createdAt: c.submittedAt,
        claimSource: "Candidate onboarding",
        fields: [
          {
            key: "candidate",
            label: "Candidate name",
            value: c.candidateName,
            source: "candidate",
          },
          {
            key: "institution",
            label: "Institution",
            value: c.organizationName,
            source: "kairo_derived",
          },
          { key: "degree", label: "Degree", value: c.roleOrProgram, source: "candidate" },
          {
            key: "field",
            label: "Field of study",
            value: "Business Administration",
            source: "candidate",
          },
          {
            key: "enrolled",
            label: "Enrolment date",
            value: "September 2017",
            source: "candidate",
          },
          { key: "graduated", label: "Graduation date", value: "June 2019", source: "candidate" },
          { key: "studentId", label: "Student ID", value: "WI-2017-2214", source: "candidate" },
        ],
      };
    case "certification":
      return {
        type: "certification",
        headline: c.roleOrProgram,
        createdAt: c.submittedAt,
        claimSource: "Candidate onboarding",
        fields: [
          {
            key: "candidate",
            label: "Candidate name",
            value: c.candidateName,
            source: "candidate",
          },
          { key: "issuer", label: "Issuer", value: c.organizationName, source: "kairo_derived" },
          {
            key: "certification",
            label: "Certification",
            value: c.roleOrProgram,
            source: "candidate",
          },
          {
            key: "credentialId",
            label: "Credential ID",
            value: "AWS-PSA-77291",
            source: "candidate",
          },
          {
            key: "issued",
            label: "Issue date",
            value: "November 2023",
            source: "verifier_confirmed",
          },
          {
            key: "expires",
            label: "Expiry date",
            value: "November 2026",
            source: "verifier_confirmed",
          },
        ],
      };
    case "identity":
      return {
        type: "identity",
        headline: c.roleOrProgram,
        createdAt: c.submittedAt,
        claimSource: "Candidate onboarding",
        fields: [
          { key: "docType", label: "Document type", value: "National ID", source: "candidate" },
          { key: "name", label: "Name on document", value: c.candidateName, source: "candidate" },
          { key: "dob", label: "Date of birth", value: "•• ••• 19••", source: "candidate" },
          { key: "docRef", label: "Document reference", value: "•••••••1284", source: "candidate" },
          { key: "country", label: "Country", value: "China", source: "candidate" },
        ],
      };
    case "platform":
      return {
        type: "platform",
        headline: `${c.roleOrProgram} · ${c.organizationName}`,
        createdAt: c.submittedAt,
        claimSource: "Candidate onboarding",
        fields: [
          {
            key: "platform",
            label: "Platform",
            value: c.organizationName,
            source: "kairo_derived",
          },
          { key: "workerId", label: "Worker ID", value: "PL-778812", source: "candidate" },
          { key: "period", label: "Active period", value: "2021 — Present", source: "candidate" },
          { key: "rating", label: "Rating / status", value: "4.8 / Active", source: "candidate" },
        ],
      };
    case "reference":
      return {
        type: "reference",
        headline: `Reference · ${c.roleOrProgram}`,
        createdAt: c.submittedAt,
        claimSource: "Candidate onboarding",
        fields: [
          { key: "referee", label: "Referee", value: "Alex Nordgren", source: "candidate" },
          {
            key: "relationship",
            label: "Relationship",
            value: "Former manager",
            source: "candidate",
          },
          { key: "org", label: "Organization", value: c.organizationName, source: "kairo_derived" },
          { key: "channel", label: "Contact channel", value: "Email", source: "candidate" },
          {
            key: "period",
            label: "Period worked together",
            value: "2019 — 2022",
            source: "candidate",
          },
        ],
      };
  }
}

function buildEvidence(c: VerificationCase): EvidenceItem[] {
  if (c.evidenceCount === 0) return [];
  const base: EvidenceItem[] = [
    {
      id: `${c.id}-ev-1`,
      title: "Employment offer letter",
      docType: "offer_letter",
      filename: "offer_letter.pdf",
      uploadedAt: c.submittedAt,
      source: "candidate_upload",
      fileSizeBytes: 184_320,
      pageCount: 2,
      processingStatus: "processed",
      reviewStatus: "reviewed",
      extractionSummary: "Offer for Senior Data Engineer, starting Mar 3, 2021.",
      attentionFlags: [],
      candidateNote: "Original PDF as issued.",
      extraction: {
        detectedCandidateName: c.candidateName,
        detectedOrganization: c.organizationName,
        detectedDates: ["2021-02-15", "2021-03-03"],
        extractedFields: [
          { label: "Candidate name", value: c.candidateName, confidence: 0.97 },
          { label: "Organization", value: c.organizationName, confidence: 0.94 },
          { label: "Role", value: c.roleOrProgram, confidence: 0.91 },
          { label: "Start date", value: "2021-03-03", confidence: 0.88 },
        ],
        processingDetails: "Mock extraction — real OCR runs in a later phase.",
      },
      comparisons: [
        {
          field: "Candidate name",
          claimed: c.candidateName,
          evidence: c.candidateName,
          result: "match",
        },
        {
          field: "Organization",
          claimed: c.organizationName,
          evidence: c.organizationName,
          result: "match",
        },
        { field: "Role", claimed: c.roleOrProgram, evidence: c.roleOrProgram, result: "match" },
        { field: "Start date", claimed: "March 3, 2021", evidence: "2021-03-03", result: "match" },
      ],
    },
    {
      id: `${c.id}-ev-2`,
      title: "Recent payslip",
      docType: "payslip",
      filename: "payslip_2024_03.pdf",
      uploadedAt: ago(1, 3),
      source: "candidate_upload",
      fileSizeBytes: 96_212,
      pageCount: 1,
      processingStatus: "processed",
      reviewStatus: c.attentionFlags.includes("document_mismatch")
        ? "needs_attention"
        : "not_reviewed",
      extractionSummary: "Monthly payslip, March 2024.",
      attentionFlags: c.attentionFlags.includes("document_mismatch") ? ["document_mismatch"] : [],
      extraction: {
        detectedCandidateName: c.candidateName,
        detectedOrganization: c.organizationName,
        detectedDates: ["2024-03-31"],
        extractedFields: [
          { label: "Candidate name", value: c.candidateName, confidence: 0.95 },
          { label: "Organization", value: c.organizationName, confidence: 0.9 },
          { label: "Pay period", value: "March 2024", confidence: 0.86 },
        ],
        mismatchWarnings: c.attentionFlags.includes("document_mismatch")
          ? [
              "Role on payslip ('Data Engineer') does not match claimed role ('Senior Data Engineer').",
            ]
          : undefined,
      },
      comparisons: [
        {
          field: "Candidate name",
          claimed: c.candidateName,
          evidence: c.candidateName,
          result: "match",
        },
        {
          field: "Organization",
          claimed: c.organizationName,
          evidence: c.organizationName,
          result: "match",
        },
        {
          field: "Role",
          claimed: c.roleOrProgram,
          evidence: "Data Engineer",
          result: c.attentionFlags.includes("document_mismatch") ? "mismatch" : "partial_match",
        },
      ],
    },
    {
      id: `${c.id}-ev-3`,
      title: "Employee ID card (scan)",
      docType: "employee_id",
      filename: "employee_id.jpg",
      uploadedAt: ago(1, 3),
      source: "candidate_upload",
      fileSizeBytes: 512_988,
      processingStatus: "processed",
      reviewStatus: "not_reviewed",
      extractionSummary: "Employee ID EMP-40912 detected.",
      attentionFlags: [],
      extraction: {
        detectedCandidateName: c.candidateName,
        detectedOrganization: c.organizationName,
        extractedFields: [
          { label: "Employee ID", value: "EMP-40912", confidence: 0.92 },
          { label: "Organization", value: c.organizationName, confidence: 0.9 },
        ],
      },
      comparisons: [
        { field: "Employee ID", claimed: "EMP-40912", evidence: "EMP-40912", result: "match" },
      ],
    },
    {
      id: `${c.id}-ev-4`,
      title: "Bank statement (redacted)",
      docType: "bank_statement",
      filename: "bank_statement.pdf",
      uploadedAt: ago(0, 5),
      source: "candidate_upload",
      fileSizeBytes: 244_112,
      pageCount: 3,
      processingStatus: "processing",
      reviewStatus: "not_reviewed",
      extractionSummary: "Awaiting processing.",
      attentionFlags: [],
    },
  ];
  return base.slice(0, Math.max(1, Math.min(c.evidenceCount, base.length)));
}

function buildOrganization(c: VerificationCase): OrganizationResolution {
  const state: OrgResolutionState =
    c.organizationStatus === "resolved"
      ? "resolved"
      : c.organizationStatus === "suggested_match"
        ? "suggested_match"
        : c.organizationStatus === "duplicate_review"
          ? "duplicate_review"
          : "unresolved";
  return {
    candidateEntered: c.organizationName,
    matched:
      state === "resolved" || state === "suggested_match"
        ? {
            id: c.organizationId,
            canonicalName: c.organizationName,
            domain: `${c.organizationName.toLowerCase().replace(/[^a-z0-9]+/g, "")}.example`,
            website: `https://${c.organizationName.toLowerCase().replace(/[^a-z0-9]+/g, "")}.example`,
            country: "Germany",
            orgType: "Private company",
            matchConfidence: state === "resolved" ? 0.96 : 0.72,
            matchReason:
              state === "resolved"
                ? "Exact domain and canonical name match."
                : "Fuzzy match on name; domain not confirmed.",
            knownChannels:
              state === "resolved"
                ? ["Registry contact", "Previous successful verification"]
                : ["Registry contact"],
          }
        : undefined,
    state,
    duplicateWarning:
      state === "duplicate_review"
        ? "Two organization records exist with similar names in the registry."
        : undefined,
    suggestions:
      state === "resolved"
        ? []
        : [
            {
              id: "org-sugg-1",
              name: `${c.organizationName} GmbH`,
              domain: `${c.organizationName.toLowerCase().replace(/[^a-z0-9]+/g, "")}.de`,
              country: "Germany",
              confidence: 0.71,
              reason: "Domain WHOIS matches candidate email domain.",
            },
            {
              id: "org-sugg-2",
              name: `${c.organizationName} International`,
              domain: `${c.organizationName.toLowerCase().replace(/[^a-z0-9]+/g, "")}-intl.example`,
              country: "United Kingdom",
              confidence: 0.44,
              reason: "Name similarity only.",
            },
          ],
  };
}

function buildContacts(c: VerificationCase): VerificationContact[] {
  const list: VerificationContact[] = [
    {
      id: `${c.id}-contact-1`,
      name: "Sabine Keller",
      role: "HR Manager",
      organization: c.organizationName,
      emailMasked:
        "s.k••••@" + c.organizationName.toLowerCase().replace(/[^a-z0-9]+/g, "") + ".example",
      phoneMasked: "+49 •••• ••12",
      source: "candidate_provided",
      state: c.attentionFlags.includes("contact_unverified") ? "unverified" : "approved",
      confidence: c.attentionFlags.includes("contact_unverified") ? 0.42 : 0.88,
      lastSuccessfulUse: c.outreachStatus === "responded" ? ago(30) : undefined,
      bounceCount: c.attentionFlags.includes("email_bounced") ? 1 : 0,
      outreachEligible: !c.attentionFlags.includes("email_bounced"),
      internalApprovalStatus: c.attentionFlags.includes("contact_unverified")
        ? "pending"
        : "approved",
    },
    {
      id: `${c.id}-contact-2`,
      name: "People Operations",
      role: "Shared inbox",
      organization: c.organizationName,
      emailMasked:
        "people@" + c.organizationName.toLowerCase().replace(/[^a-z0-9]+/g, "") + ".example",
      source: "domain_discovery",
      state: "needs_review",
      confidence: 0.61,
      bounceCount: 0,
      outreachEligible: false,
      internalApprovalStatus: "not_started",
    },
  ];
  if (c.attentionFlags.includes("email_bounced")) {
    list.push({
      id: `${c.id}-contact-3`,
      name: "Legacy HR alias",
      role: "Alias",
      organization: c.organizationName,
      emailMasked: "hr@" + c.organizationName.toLowerCase().replace(/[^a-z0-9]+/g, "") + ".example",
      source: "previous_successful_verification",
      state: "bounced",
      confidence: 0.2,
      bounceCount: 3,
      outreachEligible: false,
      internalApprovalStatus: "rejected",
    });
  }
  return list;
}

function buildCommunications(c: VerificationCase): CommunicationEvent[] {
  const list: CommunicationEvent[] = [];
  if (c.outreachStatus !== "not_started") {
    list.push({
      id: `${c.id}-comm-1`,
      channel: "email",
      recipientDisplay: "Sabine Keller",
      template: "employer_verification_request_v3",
      state: "prepared",
      at: ago(2, 6),
      actor: "System",
    });
    list.push({
      id: `${c.id}-comm-2`,
      channel: "email",
      recipientDisplay: "Sabine Keller",
      template: "employer_verification_request_v3",
      state: "sent",
      at: ago(2, 5),
      actor: "System",
    });
    if (c.outreachStatus === "sent" || c.outreachStatus === "responded") {
      list.push({
        id: `${c.id}-comm-3`,
        channel: "email",
        recipientDisplay: "Sabine Keller",
        template: "employer_verification_request_v3",
        state: "delivered",
        at: ago(2, 4),
        actor: "Delivery provider",
      });
      list.push({
        id: `${c.id}-comm-4`,
        channel: "email",
        recipientDisplay: "Sabine Keller",
        template: "employer_verification_request_v3",
        state: "opened",
        at: ago(1, 20),
        actor: "Recipient",
      });
    }
    if (c.outreachStatus === "responded") {
      list.push({
        id: `${c.id}-comm-5`,
        channel: "email",
        recipientDisplay: "Sabine Keller",
        template: "employer_verification_response",
        state: "acted",
        at: ago(0, 18),
        actor: "Recipient",
      });
    }
    if (c.outreachStatus === "bounced") {
      list.push({
        id: `${c.id}-comm-bounce`,
        channel: "email",
        recipientDisplay: "Legacy HR alias",
        template: "employer_verification_request_v3",
        state: "bounced",
        at: ago(1, 12),
        actor: "Delivery provider",
        failureReason: "550 5.1.1 mailbox does not exist",
      });
    }
  }
  return list;
}

function buildCorrections(c: VerificationCase): CorrectionRequest[] {
  if (c.correctionCount === 0) return [];
  return [
    {
      id: `${c.id}-corr-1`,
      requestedBy: "Aman Jha",
      requestedAt: ago(3, 0),
      reason: "Employment dates on payslip do not match claim.",
      fields: ["Start date", "End date"],
      state: c.status === "resubmitted" ? "resubmitted" : "in_progress",
      candidateResponse:
        c.status === "resubmitted"
          ? "Uploaded a new payslip and clarified the promotion date."
          : undefined,
      respondedAt: c.status === "resubmitted" ? ago(0, 6) : undefined,
      attachmentsAdded: c.status === "resubmitted" ? 1 : 0,
    },
  ];
}

function buildNotes(c: VerificationCase): InternalNote[] {
  return [
    {
      id: `${c.id}-note-1`,
      author: "Aman Jha",
      role: "Operations reviewer",
      at: ago(1, 6),
      body: c.attentionFlags.includes("document_mismatch")
        ? "Role on payslip differs from claim; requesting clarification before outreach."
        : "Initial review looks clean. Prepping outreach.",
      category: c.attentionFlags.includes("document_mismatch") ? "evidence" : "general",
    },
  ];
}

function buildFlags(c: VerificationCase): AttentionFlagRecord[] {
  return c.attentionFlags.map((flag, i) => ({
    id: `${c.id}-flag-${i}`,
    flag,
    label: flag
      .split("_")
      .map((s) => s[0].toUpperCase() + s.slice(1))
      .join(" "),
    severity: flag === "risk_review_required" || flag === "document_mismatch" ? "high" : "medium",
    reason:
      flag === "document_mismatch"
        ? "Role on payslip does not match claimed role."
        : flag === "email_bounced"
          ? "Employer inbox rejected the verification email."
          : flag === "contact_unverified"
            ? "Contact has not been approved for outreach."
            : "Requires reviewer attention.",
    createdAt: ago(1, 8),
    source: "system",
    state: "open",
  }));
}

function buildTimeline(c: VerificationCase): CaseTimelineEvent[] {
  const t: CaseTimelineEvent[] = [
    {
      id: `${c.id}-tl-1`,
      kind: "case_created",
      actor: c.candidateName,
      actorSource: "candidate",
      at: c.submittedAt,
      description: "Case created from candidate submission.",
    },
    {
      id: `${c.id}-tl-2`,
      kind: "evidence_uploaded",
      actor: c.candidateName,
      actorSource: "candidate",
      at: c.submittedAt,
      description: `${c.evidenceCount} document(s) uploaded.`,
    },
    {
      id: `${c.id}-tl-3`,
      kind: "processing_result",
      actor: "Kairo Extraction",
      actorSource: "system",
      at: c.submittedAt,
      description: "Automatic document processing completed.",
    },
    {
      id: `${c.id}-tl-4`,
      kind: "organization_match",
      actor: "Kairo Registry",
      actorSource: "integration",
      at: c.submittedAt,
      description:
        c.organizationStatus === "resolved"
          ? `Matched to ${c.organizationName}.`
          : "Organization requires review.",
    },
  ];
  if (c.assignedReviewer !== "Unassigned") {
    t.push({
      id: `${c.id}-tl-assign`,
      kind: "assignment_changed",
      actor: "Operations lead",
      actorSource: "admin",
      at: ago(2, 2),
      description: `Assigned to ${c.assignedReviewer}.`,
    });
  }
  if (c.outreachStatus !== "not_started") {
    t.push({
      id: `${c.id}-tl-out`,
      kind: "outreach_event",
      actor: "System",
      actorSource: "system",
      at: ago(2, 5),
      description: "Outreach email sent to employer contact.",
    });
  }
  if (c.correctionCount > 0) {
    t.push({
      id: `${c.id}-tl-corr`,
      kind: "correction_requested",
      actor: "Aman Jha",
      actorSource: "admin",
      at: ago(3, 0),
      description: "Correction requested: employment dates.",
    });
  }
  if (c.status === "resubmitted") {
    t.push({
      id: `${c.id}-tl-resub`,
      kind: "candidate_resubmitted",
      actor: c.candidateName,
      actorSource: "candidate",
      at: ago(0, 6),
      description: "Candidate resubmitted with updated evidence.",
    });
  }
  for (const flag of c.attentionFlags) {
    t.push({
      id: `${c.id}-tl-flag-${flag}`,
      kind: "attention_flag_created",
      actor: "System",
      actorSource: "system",
      at: ago(1, 8),
      description: `Attention flag: ${flag.replace(/_/g, " ")}.`,
    });
  }
  return t.sort((a, b) => new Date(a.at).getTime() - new Date(b.at).getTime());
}

function buildStatusMeta(c: VerificationCase): CaseStatusMeta {
  const map: Record<string, CaseStatusMeta> = {
    pending_review: {
      description: "Awaiting reviewer to inspect evidence and prepare outreach.",
      stage: "Review",
      slaTargetHours: 48,
      nextExpectedAction: "Admin must review evidence.",
    },
    corrections_requested: {
      description: "Waiting for the candidate to correct claim details or evidence.",
      stage: "Corrections",
      slaTargetHours: 72,
      nextExpectedAction: "Candidate must resubmit information.",
    },
    resubmitted: {
      description: "Candidate has resubmitted; reviewer should re-inspect.",
      stage: "Review",
      slaTargetHours: 48,
      nextExpectedAction: "Admin must review the resubmission.",
    },
    awaiting_organization: {
      description: "Organization identity must be resolved before outreach.",
      stage: "Organization",
      slaTargetHours: 48,
      nextExpectedAction: "Organization match must be resolved.",
    },
    awaiting_employer: {
      description: "Outreach sent; waiting for employer response.",
      stage: "Outreach",
      slaTargetHours: 120,
      nextExpectedAction: "Employer response is pending.",
    },
    clarification_requested: {
      description: "Clarification requested from the candidate or verifier.",
      stage: "Clarification",
      slaTargetHours: 72,
      nextExpectedAction: "Clarification response is pending.",
    },
    verified: {
      description: "Verification is complete.",
      stage: "Complete",
      slaTargetHours: 0,
      nextExpectedAction: "Case is complete.",
    },
    rejected: {
      description: "Case rejected after review.",
      stage: "Complete",
      slaTargetHours: 0,
      nextExpectedAction: "Case is complete.",
    },
    failed_outreach: {
      description: "Employer outreach failed and requires an alternative channel.",
      stage: "Outreach",
      slaTargetHours: 48,
      nextExpectedAction: "Contact requires review.",
    },
    unable_to_verify: {
      description: "Unable to verify — case is closed.",
      stage: "Complete",
      slaTargetHours: 0,
      nextExpectedAction: "Case is complete.",
    },
  };
  return map[c.status];
}

/**
 * Public retrieval function.
 *
 * DATA INTEGRITY: Returns a detail record ONLY for case IDs present in
 * the deterministic queue dataset (`mockVerificationCases`). Unknown
 * IDs return `undefined` so the route renders its clean not-found state
 * rather than silently fabricating a plausible verification record.
 *
 * `defaultCandidate()` fills candidate metadata only for cases that
 * already exist in the queue but lack a hand-tuned entry in
 * `CANDIDATE_BY_CASE`. It is NOT a fallback for unknown case IDs.
 */
export function getVerificationCaseDetail(caseId: string): VerificationCaseDetail | undefined {
  const summary = mockVerificationCases.find((c) => c.id === caseId);
  if (!summary) return undefined;
  const candidate = CANDIDATE_BY_CASE[caseId] ?? defaultCandidate(summary);
  return {
    summary,
    claim: buildClaim(summary),
    candidate,
    evidence: buildEvidence(summary),
    organization: buildOrganization(summary),
    contacts: buildContacts(summary),
    communications: buildCommunications(summary),
    corrections: buildCorrections(summary),
    notes: buildNotes(summary),
    flags: buildFlags(summary),
    timeline: buildTimeline(summary),
    statusMeta: buildStatusMeta(summary),
  };
}

/** Small helper used by mock preview components. */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export const PRIORITY_LABEL: Record<Priority, string> = {
  urgent: "Urgent",
  high: "High",
  normal: "Normal",
  low: "Low",
};
