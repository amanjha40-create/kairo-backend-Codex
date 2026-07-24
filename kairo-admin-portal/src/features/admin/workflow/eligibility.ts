/**
 * Central workflow eligibility engine.
 *
 * All "can this operator perform action X on case Y right now?" logic
 * lives here so eligibility is testable and does not drift between the
 * button that opens a dialog and the confirm button inside it.
 */
import type { VerificationCaseDetail } from "../data/cases";
import type { VerificationStatus } from "../data/types";
import type {
  WorkflowAction,
  WorkflowActor,
  WorkflowEligibilityResult,
  WorkflowPermission,
  WorkflowTransitionRule,
} from "./types";
import { hasPermission } from "./permissions";

/**
 * Base transition rules. `getWorkflowEligibility` applies these first and
 * then layers case-specific evidence / flag / contact checks on top.
 */
export const TRANSITION_RULES: WorkflowTransitionRule[] = [
  {
    action: "request_correction",
    fromStatuses: [
      "pending_review",
      "resubmitted",
      "awaiting_organization",
      "awaiting_employer",
      "clarification_requested",
    ],
    toStatus: "corrections_requested",
    requiredPermission: "verification.request_correction",
  },
  {
    action: "approve_outreach",
    fromStatuses: ["pending_review", "resubmitted", "awaiting_organization", "failed_outreach"],
    toStatus: "awaiting_employer",
    requiredPermission: "verification.approve_outreach",
  },
  {
    action: "verify",
    fromStatuses: ["pending_review", "resubmitted", "awaiting_employer", "clarification_requested"],
    toStatus: "verified",
    requiredPermission: "verification.verify",
  },
  {
    action: "reject",
    fromStatuses: [
      "pending_review",
      "resubmitted",
      "awaiting_organization",
      "awaiting_employer",
      "clarification_requested",
      "failed_outreach",
    ],
    toStatus: "rejected",
    requiredPermission: "verification.reject",
  },
  {
    action: "unable_to_verify",
    fromStatuses: [
      "pending_review",
      "resubmitted",
      "awaiting_organization",
      "awaiting_employer",
      "clarification_requested",
      "failed_outreach",
    ],
    toStatus: "unable_to_verify",
    requiredPermission: "verification.mark_unable",
  },
  {
    action: "record_clarification_request",
    fromStatuses: ["awaiting_employer"],
    toStatus: "clarification_requested",
    requiredPermission: "verification.record_clarification",
  },
  {
    action: "record_clarification_response",
    fromStatuses: ["clarification_requested"],
    toStatus: "awaiting_employer",
    requiredPermission: "verification.record_clarification",
  },
];

/** Case state the engine consumes. Includes any session overrides. */
export interface WorkflowCaseState {
  currentStatus: VerificationStatus;
  hasEligibleContact: boolean;
  hasOpenCriticalFlag: boolean;
  hasOpenHighFlag: boolean;
  hasOpenDocumentMismatch: boolean;
  hasOpenPossibleDuplicate: boolean;
  organizationResolved: boolean;
  outstandingCorrection: boolean;
  evidenceCount: number;
  evidenceReviewedCount: number;
}

/** Build a workflow case state from a case detail + acknowledged flag ids. */
export function buildWorkflowCaseState(
  detail: VerificationCaseDetail,
  overrides: {
    currentStatus?: VerificationStatus;
    acknowledgedFlagIds?: Set<string>;
    hasOutstandingCorrectionOverride?: boolean;
  } = {},
): WorkflowCaseState {
  const ack = overrides.acknowledgedFlagIds ?? new Set<string>();
  const openFlags = detail.flags.filter((f) => f.state === "open" && !ack.has(f.id));
  const hasOpenCriticalFlag = openFlags.some(
    (f) =>
      f.severity === "high" &&
      (f.flag === "risk_review_required" || f.flag === "document_mismatch"),
  );
  const hasOpenHighFlag = openFlags.some((f) => f.severity === "high");
  const hasOpenDocumentMismatch = openFlags.some((f) => f.flag === "document_mismatch");
  const hasOpenPossibleDuplicate = openFlags.some((f) => f.flag === "possible_duplicate");
  const hasEligibleContact = detail.contacts.some(
    (c) => c.outreachEligible && c.internalApprovalStatus === "approved",
  );
  const outstandingCorrection =
    overrides.hasOutstandingCorrectionOverride ??
    detail.corrections.some((c) => c.state !== "resolved" && c.state !== "closed");

  return {
    currentStatus: overrides.currentStatus ?? detail.summary.status,
    hasEligibleContact,
    hasOpenCriticalFlag,
    hasOpenHighFlag,
    hasOpenDocumentMismatch,
    hasOpenPossibleDuplicate,
    organizationResolved: detail.organization.state === "resolved",
    outstandingCorrection,
    evidenceCount: detail.evidence.length,
    evidenceReviewedCount: detail.evidence.filter((e) => e.reviewStatus === "reviewed").length,
  };
}

const TERMINAL_STATUSES: VerificationStatus[] = ["verified", "rejected", "unable_to_verify"];

export function isTerminalStatus(status: VerificationStatus): boolean {
  return TERMINAL_STATUSES.includes(status);
}

function requiredPermissionFor(action: WorkflowAction): WorkflowPermission {
  const rule = TRANSITION_RULES.find((r) => r.action === action);
  if (!rule) throw new Error(`No transition rule for ${action}`);
  return rule.requiredPermission;
}

function nextStatusFor(
  action: WorkflowAction,
  currentStatus: VerificationStatus,
): VerificationStatus {
  const rule = TRANSITION_RULES.find(
    (r) => r.action === action && r.fromStatuses.includes(currentStatus),
  );
  return rule?.toStatus ?? currentStatus;
}

export function evaluateWorkflowEligibility(
  detail: VerificationCaseDetail,
  action: WorkflowAction,
  actor: WorkflowActor,
  state: WorkflowCaseState,
  opts: { rejectionIsHighRisk?: boolean } = {},
): WorkflowEligibilityResult {
  const requiredPermission = requiredPermissionFor(action);
  const blockingReasons: string[] = [];
  const warnings: string[] = [];
  const rule = TRANSITION_RULES.find((r) => r.action === action);
  const applicable = rule?.fromStatuses.includes(state.currentStatus) ?? false;
  const irrelevant = isTerminalStatus(state.currentStatus) || !applicable;

  if (isTerminalStatus(state.currentStatus)) {
    blockingReasons.push(
      "Case is in a terminal state; no further workflow transitions are permitted in this build.",
    );
  } else if (!applicable) {
    blockingReasons.push(
      `Action is not available from the current status "${state.currentStatus.replace(/_/g, " ")}".`,
    );
  }

  if (!hasPermission(actor.permissions, requiredPermission)) {
    blockingReasons.push(
      `Your role (${actor.role}) does not have the "${requiredPermission}" permission.`,
    );
  }

  // Action-specific rules
  switch (action) {
    case "request_correction":
      if (state.outstandingCorrection) {
        warnings.push("A correction request is already outstanding on this case.");
      }
      break;
    case "approve_outreach":
      if (!state.organizationResolved) {
        blockingReasons.push("Organization must be resolved before approving outreach.");
      }
      if (!state.hasEligibleContact) {
        blockingReasons.push("At least one approved, outreach-eligible contact is required.");
      }
      if (state.hasOpenCriticalFlag) {
        blockingReasons.push("Open critical risk flag blocks outreach. Resolve it first.");
      }
      if (state.outstandingCorrection) {
        blockingReasons.push(
          "Cannot approve outreach while a candidate correction is outstanding.",
        );
      }
      if (state.evidenceCount === 0) {
        blockingReasons.push("Required evidence has not been uploaded.");
      }
      if (state.hasOpenPossibleDuplicate) {
        warnings.push("Possible duplicate flag is open. Confirm this is not a duplicate case.");
      }
      break;
    case "verify":
      if (state.hasOpenCriticalFlag) {
        blockingReasons.push("Open critical risk flag blocks verification.");
      }
      if (state.hasOpenDocumentMismatch) {
        blockingReasons.push("Document mismatch flag must be reviewed before verifying.");
      }
      if (state.outstandingCorrection) {
        blockingReasons.push("Outstanding candidate correction must be resolved first.");
      }
      if (state.hasOpenPossibleDuplicate) {
        blockingReasons.push("Possible duplicate must be resolved before a terminal decision.");
      }
      if (state.evidenceCount === 0) {
        blockingReasons.push("No evidence attached to this case.");
      }
      if (state.evidenceReviewedCount === 0 && state.evidenceCount > 0) {
        warnings.push("No evidence has been marked as reviewed yet.");
      }
      if (state.currentStatus === "pending_review" || state.currentStatus === "resubmitted") {
        warnings.push(
          "Verifying directly without employer confirmation requires an approved evidence-only basis.",
        );
      }
      break;
    case "reject":
      if (state.hasOpenPossibleDuplicate) {
        blockingReasons.push("Possible duplicate must be resolved before a terminal decision.");
      }
      if (
        opts.rejectionIsHighRisk &&
        actor.roleKey !== "trust_safety" &&
        actor.roleKey !== "admin" &&
        actor.roleKey !== "operations_lead"
      ) {
        blockingReasons.push(
          "Fraud or identity-related rejection requires Trust & Safety or Admin permission.",
        );
      }
      break;
    case "unable_to_verify":
      // Distinct from rejection — no fraud-severity checks.
      break;
    case "record_clarification_request":
    case "record_clarification_response":
      // Lightweight session-only recording, no additional constraints.
      break;
  }

  const allowed = blockingReasons.length === 0;
  return {
    action,
    allowed,
    blockingReasons,
    warnings,
    requiredPermission,
    nextStatusOnSuccess: nextStatusFor(action, state.currentStatus),
    irrelevant,
  };
}

/** Convenience — evaluate every primary decision action for a case. */
export function getAvailableWorkflowActions(
  detail: VerificationCaseDetail,
  actor: WorkflowActor,
  state: WorkflowCaseState,
): Record<WorkflowAction, WorkflowEligibilityResult> {
  const actions: WorkflowAction[] = [
    "request_correction",
    "approve_outreach",
    "verify",
    "reject",
    "unable_to_verify",
    "record_clarification_request",
    "record_clarification_response",
  ];
  return actions.reduce(
    (acc, a) => {
      acc[a] = evaluateWorkflowEligibility(detail, a, actor, state);
      return acc;
    },
    {} as Record<WorkflowAction, WorkflowEligibilityResult>,
  );
}
