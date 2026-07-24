/**
 * Session-only outreach engine.
 *
 * Two exports:
 *   1. `evaluateOutreachReadiness` — a pure function that inspects a case
 *      workspace's current state and returns a structured readiness
 *      report (blockers + warnings). Used by the case workspace to
 *      enable/disable the outreach preparation flow and to justify
 *      disabled states with human-readable copy.
 *   2. `nextDeliveryStates` / `OUTREACH_TEMPLATES` / `simulateEvent`
 *      helpers — deterministic rules used by the outreach simulator so
 *      delivery transitions are always logical (e.g. can't `Bounce` after
 *      `Delivered`, can't `Open` before `Delivered`).
 *
 * Nothing here performs I/O. No emails are sent. Templates are mock copy.
 */

import type { VerificationContact, VerificationCaseDetail } from "../data/cases";
import type { WorkflowActor, WorkflowPermission } from "./types";
import { hasPermission } from "./permissions";

// =====================================================================
// Readiness engine
// =====================================================================

export interface OutreachReadinessReport {
  ready: boolean;
  approvedContact?: VerificationContact;
  blockers: string[];
  warnings: string[];
  requiredPermission: WorkflowPermission;
}

export function evaluateOutreachReadiness(
  detail: VerificationCaseDetail,
  ctx: {
    actor: WorkflowActor;
    sessionApprovedContactIds: Set<string>;
    sessionRejectedContactIds: Set<string>;
    acknowledgedFlagIds: Set<string>;
    orgResolvedInSession: boolean;
  },
): OutreachReadinessReport {
  const blockers: string[] = [];
  const warnings: string[] = [];

  if (!hasPermission(ctx.actor.permissions, "verification.approve_outreach")) {
    blockers.push(`${ctx.actor.role} role does not include permission to approve outreach.`);
  }

  // Organization must be resolved (either originally or in-session).
  const orgResolved = detail.organization.state === "resolved" || ctx.orgResolvedInSession;
  if (!orgResolved) {
    blockers.push(
      "Organization is not resolved. Accept a suggested match, or propose a registry record.",
    );
  }
  if (detail.organization.state === "duplicate_review") {
    warnings.push(
      "Organization has a possible duplicate in the registry. Confirm the canonical record before sending outreach.",
    );
  }

  // At least one approved contact.
  const contacts = detail.contacts;
  const approvedContact = contacts.find((c) => {
    if (ctx.sessionRejectedContactIds.has(c.id)) return false;
    if (ctx.sessionApprovedContactIds.has(c.id))
      return c.outreachEligible !== false && c.state !== "bounced";
    return (
      c.internalApprovalStatus === "approved" &&
      c.outreachEligible &&
      c.state !== "bounced" &&
      c.state !== "rejected" &&
      c.state !== "inactive"
    );
  });
  if (!approvedContact) {
    blockers.push("No approved verification contact. Review a contact and mark it approved.");
  }

  // Risk / attention flags block outreach until acknowledged.
  const openHighRiskFlags = detail.flags.filter(
    (f) =>
      f.state === "open" &&
      !ctx.acknowledgedFlagIds.has(f.id) &&
      (f.severity === "high" ||
        f.flag === "document_mismatch" ||
        f.flag === "risk_review_required"),
  );
  if (openHighRiskFlags.length > 0) {
    blockers.push(
      `Acknowledge ${openHighRiskFlags.length} high-severity flag${openHighRiskFlags.length === 1 ? "" : "s"} before outreach: ${openHighRiskFlags.map((f) => f.label).join(", ")}.`,
    );
  }

  // Bounced primary contact is a warning even if a fallback is available.
  if (contacts.some((c) => c.state === "bounced") && approvedContact) {
    warnings.push(
      "This case has a previously bounced contact on file. Confirm the alternative address is current.",
    );
  }

  return {
    ready: blockers.length === 0 && Boolean(approvedContact),
    approvedContact,
    blockers,
    warnings,
    requiredPermission: "verification.approve_outreach",
  };
}

// =====================================================================
// Outreach templates (mock copy)
// =====================================================================

export type OutreachTemplateId =
  | "employer_verification_request_v3"
  | "employer_verification_follow_up_v1"
  | "reference_check_request_v1"
  | "credential_issuer_confirmation_v1";

export interface OutreachTemplate {
  id: OutreachTemplateId;
  name: string;
  channel: "email";
  subject: string;
  bodyPreview: string;
}

export const OUTREACH_TEMPLATES: OutreachTemplate[] = [
  {
    id: "employer_verification_request_v3",
    name: "Employer verification request",
    channel: "email",
    subject: "Verification request — {{candidateName}}",
    bodyPreview:
      "Hello {{contactName}},\n\nKairo is verifying the employment history of {{candidateName}}, who has provided your organisation ({{organizationName}}) as a reference. Could you confirm the role and dates below via the secure link?\n\n— The Kairo Verification Team",
  },
  {
    id: "employer_verification_follow_up_v1",
    name: "Employer follow-up",
    channel: "email",
    subject: "Reminder — verification request for {{candidateName}}",
    bodyPreview:
      "Hello {{contactName}},\n\nJust a reminder about the verification request for {{candidateName}}. It should take under 2 minutes.\n\n— The Kairo Verification Team",
  },
  {
    id: "reference_check_request_v1",
    name: "Professional reference check",
    channel: "email",
    subject: "Reference request — {{candidateName}}",
    bodyPreview:
      "Hello {{contactName}},\n\nKairo is contacting you as a professional reference for {{candidateName}}. If you're available, please confirm the details below.\n\n— The Kairo Verification Team",
  },
  {
    id: "credential_issuer_confirmation_v1",
    name: "Credential issuer confirmation",
    channel: "email",
    subject: "Credential confirmation — {{credentialName}}",
    bodyPreview:
      "Hello,\n\nKairo is confirming a credential ({{credentialName}}) presented by {{candidateName}}. Please confirm issuance details via the secure link.\n\n— The Kairo Verification Team",
  },
];

export function renderTemplatePreview(tpl: OutreachTemplate, vars: Record<string, string>) {
  const substitute = (s: string) => s.replace(/\{\{(\w+)\}\}/g, (_, k) => vars[k] ?? `{{${k}}}`);
  return {
    subject: substitute(tpl.subject),
    body: substitute(tpl.bodyPreview),
  };
}

// =====================================================================
// Delivery simulation
// =====================================================================

export type DeliveryState =
  "prepared" | "sent" | "delivered" | "opened" | "link_opened" | "responded" | "bounced" | "failed";

export const DELIVERY_STATE_LABEL: Record<DeliveryState, string> = {
  prepared: "Prepared",
  sent: "Simulated sent",
  delivered: "Delivered",
  opened: "Opened",
  link_opened: "Link opened",
  responded: "Responded",
  bounced: "Bounced",
  failed: "Failed",
};

/**
 * Which follow-up delivery events can be simulated from a given state.
 * Terminal states (`responded`, `bounced`, `failed`) return an empty list.
 */
export function nextDeliveryStates(current: DeliveryState): DeliveryState[] {
  switch (current) {
    case "prepared":
      return ["sent"];
    case "sent":
      return ["delivered", "bounced", "failed"];
    case "delivered":
      return ["opened", "bounced"];
    case "opened":
      return ["link_opened", "responded"];
    case "link_opened":
      return ["responded"];
    default:
      return [];
  }
}

export const TERMINAL_DELIVERY_STATES: DeliveryState[] = ["responded", "bounced", "failed"];

export function isTerminalDelivery(s: DeliveryState) {
  return TERMINAL_DELIVERY_STATES.includes(s);
}

// =====================================================================
// Employer response classification
// =====================================================================

export type EmployerResponseOutcome =
  "confirmed" | "partially_confirmed" | "denied" | "unable_to_confirm" | "requested_more_info";

export const EMPLOYER_RESPONSE_LABEL: Record<EmployerResponseOutcome, string> = {
  confirmed: "Confirmed the claim",
  partially_confirmed: "Partially confirmed",
  denied: "Denied the claim",
  unable_to_confirm: "Unable to confirm",
  requested_more_info: "Requested more information",
};

// =====================================================================
// Failed outreach reasons
// =====================================================================

export type FailedOutreachReason =
  | "hard_bounce"
  | "soft_bounce_repeated"
  | "no_response"
  | "invalid_contact"
  | "contact_moved_org"
  | "auto_reply_only"
  | "spam_blocked";

export const FAILED_OUTREACH_REASON_LABEL: Record<FailedOutreachReason, string> = {
  hard_bounce: "Hard bounce (invalid mailbox)",
  soft_bounce_repeated: "Soft bounce, repeated",
  no_response: "No response after follow-ups",
  invalid_contact: "Contact details invalid",
  contact_moved_org: "Contact no longer at organization",
  auto_reply_only: "Auto-reply only (no human response)",
  spam_blocked: "Suppressed / blocked by receiving server",
};
