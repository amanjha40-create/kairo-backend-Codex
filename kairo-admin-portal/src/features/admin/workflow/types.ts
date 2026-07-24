/**
 * Kairo Admin — Verification workflow type layer.
 *
 * Central definitions for controlled workflow actions. No business logic
 * lives here — rules go in `eligibility.ts`, permissions in
 * `permissions.ts`, validation in `schemas.ts`.
 */

import type { VerificationStatus } from "../data/types";

/** Every controlled action available on the case workspace. */
export type WorkflowAction =
  | "request_correction"
  | "approve_outreach"
  | "verify"
  | "reject"
  | "unable_to_verify"
  | "record_clarification_request"
  | "record_clarification_response";

export const WORKFLOW_ACTION_LABEL: Record<WorkflowAction, string> = {
  request_correction: "Request Correction",
  approve_outreach: "Approve for Outreach",
  verify: "Verify",
  reject: "Reject",
  unable_to_verify: "Unable to Verify",
  record_clarification_request: "Record employer clarification",
  record_clarification_response: "Record candidate response",
};

/**
 * Whether the action is a terminal decision. Terminal decisions are
 * presented with stronger confirmation styling.
 */
export const WORKFLOW_ACTION_TERMINAL: Record<WorkflowAction, boolean> = {
  request_correction: false,
  approve_outreach: false,
  verify: true,
  reject: true,
  unable_to_verify: true,
  record_clarification_request: false,
  record_clarification_response: false,
};

// ---------------------------------------------------------------------
// Permissions & roles
// ---------------------------------------------------------------------

export type WorkflowPermission =
  | "verification.request_correction"
  | "verification.approve_outreach"
  | "verification.verify"
  | "verification.reject"
  | "verification.mark_unable"
  | "verification.assign"
  | "verification.change_priority"
  | "verification.acknowledge_flag"
  | "verification.record_clarification"
  | "users.view"
  | "users.notes.create"
  | "users.account.disable"
  | "users.account.enable"
  | "users.sessions.revoke"
  | "users.verification.resend"
  | "users.password_reset.prepare"
  | "users.risk.flag"
  | "users.data_export.prepare"
  | "users.deletion.prepare"
  | "communications.view"
  | "communications.view_failures"
  | "communications.notes.create"
  | "communications.followup.schedule"
  | "communications.followup.cancel"
  | "communications.manual_contact.log"
  | "communications.failure.review"
  | "risk.view"
  | "risk.note"
  | "risk.review"
  | "risk.escalate"
  | "risk.resolve"
  | "risk.prepare_actions"
  | "system.view"
  | "system.jobs.view"
  | "system.jobs.prepare_actions"
  | "system.flags.view"
  | "system.flags.prepare_changes"
  | "system.messaging.view"
  | "system.audit.view"
  | "system.alerts.manage"
  | "system.configuration.view";

export type AdminRoleKey = "admin" | "operations_lead" | "trust_safety" | "reviewer" | "read_only";

// ---------------------------------------------------------------------
// Eligibility & transitions
// ---------------------------------------------------------------------

export interface WorkflowActor {
  name: string;
  role: string;
  roleKey: AdminRoleKey;
  permissions: WorkflowPermission[];
}

export interface WorkflowEligibilityResult {
  action: WorkflowAction;
  allowed: boolean;
  /** Reasons the action is blocked. Empty when `allowed` is true. */
  blockingReasons: string[];
  /** Non-blocking cautions the operator should see before confirming. */
  warnings: string[];
  requiredPermission: WorkflowPermission;
  /** Machine hint for the next status if the action succeeds. */
  nextStatusOnSuccess: VerificationStatus;
  /** True when the action is not applicable to the case's current state at all. */
  irrelevant: boolean;
}

export interface WorkflowTransitionRule {
  action: WorkflowAction;
  fromStatuses: VerificationStatus[];
  toStatus: VerificationStatus;
  requiredPermission: WorkflowPermission;
}

// ---------------------------------------------------------------------
// Decision reason enums (used by dialogs & schemas)
// ---------------------------------------------------------------------

export const CORRECTION_REASONS = [
  "missing_information",
  "document_unclear",
  "document_mismatch",
  "incorrect_employment_details",
  "incorrect_education_details",
  "organization_information_incomplete",
  "identity_information_mismatch",
  "additional_evidence_required",
  "other",
] as const;
export type CorrectionReason = (typeof CORRECTION_REASONS)[number];
export const CORRECTION_REASON_LABEL: Record<CorrectionReason, string> = {
  missing_information: "Missing information",
  document_unclear: "Document unclear",
  document_mismatch: "Document mismatch",
  incorrect_employment_details: "Incorrect employment details",
  incorrect_education_details: "Incorrect education details",
  organization_information_incomplete: "Organization information incomplete",
  identity_information_mismatch: "Identity information mismatch",
  additional_evidence_required: "Additional evidence required",
  other: "Other",
};

export const VERIFICATION_BASES = [
  "employer_confirmed",
  "institution_confirmed",
  "issuing_body_confirmed",
  "platform_confirmed",
  "approved_primary_evidence",
  "approved_multi_document_evidence",
  "authoritative_registry",
  "previous_verified_organization_channel",
  "other_approved_basis",
] as const;
export type VerificationBasis = (typeof VERIFICATION_BASES)[number];
export const VERIFICATION_BASIS_LABEL: Record<VerificationBasis, string> = {
  employer_confirmed: "Employer confirmed",
  institution_confirmed: "Institution confirmed",
  issuing_body_confirmed: "Issuing body confirmed",
  platform_confirmed: "Platform confirmed",
  approved_primary_evidence: "Approved primary evidence",
  approved_multi_document_evidence: "Approved multi-document evidence",
  authoritative_registry: "Authoritative registry",
  previous_verified_organization_channel: "Previous verified organization channel",
  other_approved_basis: "Other approved basis",
};

export const REJECTION_REASONS = [
  "material_document_inconsistency",
  "organization_denied",
  "institution_denied",
  "issuer_denied_credential",
  "identity_not_matched",
  "fraudulent_evidence_suspected",
  "candidate_failed_to_resolve",
  "duplicate_or_invalid_request",
  "other_substantiated",
] as const;
export type RejectionReason = (typeof REJECTION_REASONS)[number];
export const REJECTION_REASON_LABEL: Record<RejectionReason, string> = {
  material_document_inconsistency: "Material document inconsistency",
  organization_denied: "Organization denied the claim",
  institution_denied: "Institution denied the claim",
  issuer_denied_credential: "Issuer denied the credential",
  identity_not_matched: "Identity could not be matched",
  fraudulent_evidence_suspected: "Fraudulent or altered evidence suspected",
  candidate_failed_to_resolve: "Candidate failed to resolve material discrepancies",
  duplicate_or_invalid_request: "Duplicate or invalid verification request",
  other_substantiated: "Other substantiated reason",
};
/** Rejection reasons that require Trust & Safety or Admin permission. */
export const HIGH_RISK_REJECTION_REASONS: RejectionReason[] = [
  "fraudulent_evidence_suspected",
  "identity_not_matched",
];

export const UNABLE_REASONS = [
  "organization_unreachable",
  "institution_unreachable",
  "no_valid_contact",
  "insufficient_evidence",
  "organization_no_longer_operating",
  "records_unavailable",
  "channel_unavailable",
  "candidate_did_not_provide",
  "conflicting_information",
  "other",
] as const;
export type UnableReason = (typeof UNABLE_REASONS)[number];
export const UNABLE_REASON_LABEL: Record<UnableReason, string> = {
  organization_unreachable: "Organization unreachable",
  institution_unreachable: "Institution unreachable",
  no_valid_contact: "No valid verification contact",
  insufficient_evidence: "Insufficient evidence",
  organization_no_longer_operating: "Organization no longer operating",
  records_unavailable: "Records unavailable",
  channel_unavailable: "Verification channel unavailable",
  candidate_did_not_provide: "Candidate did not provide required information",
  conflicting_information: "Conflicting information without conclusive evidence",
  other: "Other",
};

// ---------------------------------------------------------------------
// Session records
// ---------------------------------------------------------------------

export type FieldConfirmation =
  "confirmed" | "partially_confirmed" | "not_confirmed" | "not_applicable";
export const FIELD_CONFIRMATION_LABEL: Record<FieldConfirmation, string> = {
  confirmed: "Confirmed",
  partially_confirmed: "Partially confirmed",
  not_confirmed: "Not confirmed",
  not_applicable: "Not applicable",
};

export interface WorkflowActor_Attribution {
  actorName: string;
  actorRole: string;
  at: string;
}

export interface CorrectionActionPayload {
  reasons: CorrectionReason[];
  affectedFieldKeys: string[];
  requestedItems: string[];
  candidateMessage: string;
  internalNote?: string;
}

export interface OutreachActionPayload {
  contactId: string;
  channel: "email";
  internalNote?: string;
}

export interface VerifyActionPayload {
  basis: VerificationBasis;
  fieldConfirmations: Record<string, FieldConfirmation>;
  decisionSummary: string;
  effectiveDate: string; // yyyy-mm-dd
  expiryDate?: string;
  internalNote?: string;
}

export interface RejectActionPayload {
  reason: RejectionReason;
  decisionSummary: string;
  supportingEvidenceIds: string[];
  candidateMessage: string;
  internalNote?: string;
  acknowledgement: true;
}

export interface UnableActionPayload {
  reason: UnableReason;
  attemptsSummary: string;
  outstandingUncertainty: string;
  candidateMessage: string;
  internalNote?: string;
}

export interface ClarificationRequestPayload {
  question: string;
  affectedFieldKeys: string[];
  internalNote?: string;
}

export interface ClarificationResponsePayload {
  response: string;
  updatedFieldKeys: string[];
  evidenceAdded: boolean;
  internalNote?: string;
}

// Session decision record shown in the Decision Summary panel.
export interface SessionDecisionRecord {
  id: string;
  kind: "verify" | "reject" | "unable_to_verify";
  reasonLabel: string;
  basisLabel?: string;
  decisionSummary: string;
  candidateMessage?: string;
  fieldConfirmations?: Record<string, FieldConfirmation>;
  actorName: string;
  actorRole: string;
  at: string;
}

export interface SessionCorrectionRecord {
  id: string;
  reasonLabels: string[];
  affectedFieldKeys: string[];
  requestedItems: string[];
  candidateMessage: string;
  actorName: string;
  actorRole: string;
  at: string;
}

export interface SessionCommunicationRecord {
  id: string;
  channel: "email";
  template: string;
  recipientDisplay: string;
  state: "prepared";
  at: string;
  actorName: string;
}

export interface SessionClarificationRecord {
  id: string;
  kind: "employer_request" | "candidate_response";
  question?: string;
  response?: string;
  affectedFieldKeys: string[];
  updatedFieldKeys?: string[];
  evidenceAdded?: boolean;
  at: string;
  actorName: string;
}
