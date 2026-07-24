/**
 * Kairo Admin — Communications mock data.
 *
 * Deterministic seed data powering the Communications Center at
 * `/admin/communications` and each Communication detail workspace at
 * `/admin/communications/$communicationId`.
 *
 * NEVER MUTATE these exports at runtime — the session layer
 * (`use-communications-session.ts`) owns all session-only overlays.
 *
 * BACKEND INTEGRATION NOTE
 * ------------------------
 * Replace with TanStack Query hooks against the real Communications API
 * when available. Surface loading/empty/error states — never masquerade
 * as real operational data.
 */

import { mockVerificationCases, type Assignee } from "./verification-cases";

// ---------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------

export type CommunicationChannel = "email" | "sms" | "push" | "in_app";
export const COMMUNICATION_CHANNEL_LABEL: Record<CommunicationChannel, string> = {
  email: "Email",
  sms: "SMS",
  push: "Push",
  in_app: "In-app",
};

export type CommunicationDirection = "outbound" | "inbound";

export type CommunicationType =
  | "employer_outreach"
  | "employer_reminder"
  | "employer_clarification"
  | "candidate_notification"
  | "candidate_clarification"
  | "platform_verification"
  | "internal_alert";
export const COMMUNICATION_TYPE_LABEL: Record<CommunicationType, string> = {
  employer_outreach: "Employer outreach",
  employer_reminder: "Employer reminder",
  employer_clarification: "Employer clarification",
  candidate_notification: "Candidate notification",
  candidate_clarification: "Candidate clarification",
  platform_verification: "Platform verification",
  internal_alert: "Internal alert",
};

export type CommunicationStatus =
  | "pending"
  | "queued"
  | "delivered"
  | "opened"
  | "awaiting_response"
  | "responded"
  | "failed"
  | "bounced"
  | "complaint"
  | "suppressed";
export const COMMUNICATION_STATUS_LABEL: Record<CommunicationStatus, string> = {
  pending: "Pending",
  queued: "Queued",
  delivered: "Delivered",
  opened: "Opened",
  awaiting_response: "Awaiting response",
  responded: "Responded",
  failed: "Failed",
  bounced: "Bounced",
  complaint: "Complaint",
  suppressed: "Suppressed",
};

export type DeliveryEventKind =
  | "prepared"
  | "queued"
  | "delivered"
  | "opened"
  | "verification_link_opened"
  | "employer_responded"
  | "reminder_sent"
  | "failed"
  | "bounce"
  | "complaint"
  | "suppressed";
export const DELIVERY_EVENT_LABEL: Record<DeliveryEventKind, string> = {
  prepared: "Prepared",
  queued: "Queued",
  delivered: "Delivered",
  opened: "Opened",
  verification_link_opened: "Verification link opened",
  employer_responded: "Employer responded",
  reminder_sent: "Reminder sent",
  failed: "Failed",
  bounce: "Bounce",
  complaint: "Complaint",
  suppressed: "Suppressed",
};

export type TemplateKey =
  | "employment_verification"
  | "education_verification"
  | "certification_verification"
  | "reference_verification"
  | "reminder"
  | "clarification"
  | "platform_verification";

export interface TemplateDefinition {
  key: TemplateKey;
  name: string;
  version: string;
  status: "active" | "draft" | "deprecated";
  channel: CommunicationChannel;
  category: CommunicationType;
  variables: string[];
  subjectPreview: string;
  bodyPreview: string;
  updatedAt: string;
}

export interface DeliveryEvent {
  id: string;
  at: string;
  kind: DeliveryEventKind;
  detail?: string;
  actor?: string;
  /** True for events simulated in the current session. */
  sessionOnly?: boolean;
}

export interface EmployerResponseRecord {
  id: string;
  at: string;
  outcome: "confirmed" | "denied" | "partial" | "unable";
  body: string;
  actionRequired?: string;
}

export type FailureReason =
  | "hard_bounce"
  | "soft_bounce"
  | "complaint"
  | "suppressed"
  | "invalid_contact"
  | "delivery_failure"
  | "attempt_limit_reached";
export const FAILURE_REASON_LABEL: Record<FailureReason, string> = {
  hard_bounce: "Hard bounce",
  soft_bounce: "Soft bounce",
  complaint: "Complaint",
  suppressed: "Suppressed",
  invalid_contact: "Invalid contact",
  delivery_failure: "Delivery failure",
  attempt_limit_reached: "Attempt limit reached",
};

export const FAILURE_RECOMMENDED_ACTION: Record<FailureReason, string> = {
  hard_bounce: "Mark contact invalid and request an alternative from candidate.",
  soft_bounce: "Retry after 24h; escalate if it recurs.",
  complaint: "Suppress recipient and route to Trust & Safety review.",
  suppressed: "Do not retry. Use an alternative approved contact.",
  invalid_contact: "Remove contact and request replacement from the candidate.",
  delivery_failure: "Retry once; escalate to Operations if failure persists.",
  attempt_limit_reached: "Escalate case to Unable to Verify unless a new contact is provided.",
};

export interface FailureRecord {
  id: string;
  at: string;
  reason: FailureReason;
  detail: string;
}

export interface FollowUpRecord {
  id: string;
  scheduledAt: string;
  attempt: number;
  status: "pending" | "sent" | "cancelled" | "rescheduled";
  reason?: string;
  sessionOnly?: boolean;
}

export interface InternalNoteSeed {
  id: string;
  at: string;
  actor: string;
  actorRole: string;
  body: string;
}

export interface Communication {
  id: string;
  reference: string;
  channel: CommunicationChannel;
  direction: CommunicationDirection;
  type: CommunicationType;
  template: TemplateKey;
  templateVersion: string;
  subject: string;
  status: CommunicationStatus;
  caseId?: string;
  caseReference?: string;
  candidateId?: string;
  candidateName?: string;
  organizationId?: string;
  organizationName?: string;
  contactName?: string;
  contactEmailMasked?: string;
  assignedReviewer: Assignee;
  sentAt: string;
  lastEventAt: string;
  nextFollowUpAt?: string;
  attemptCount: number;
  awaitingResponse: boolean;
  events: DeliveryEvent[];
  followUps: FollowUpRecord[];
  failures: FailureRecord[];
  responses: EmployerResponseRecord[];
  internalNotes: InternalNoteSeed[];
  attentionTags: string[];
}

// ---------------------------------------------------------------------
// Deterministic clocks & helpers
// ---------------------------------------------------------------------

const NOW = new Date(Math.floor(Date.now() / 3_600_000) * 3_600_000);
function iso(daysAgo: number, hours = 0, minutes = 0): string {
  const d = new Date(NOW);
  d.setUTCMinutes(d.getUTCMinutes() - minutes);
  d.setUTCHours(d.getUTCHours() - hours);
  d.setUTCDate(d.getUTCDate() - daysAgo);
  return d.toISOString();
}
function isoAhead(days: number, hours = 0): string {
  const d = new Date(NOW);
  d.setUTCHours(d.getUTCHours() + hours);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString();
}
function mask(local: string, domain: string) {
  const shown = local.slice(0, 1);
  const rest = local.length > 1 ? "•".repeat(Math.max(2, local.length - 1)) : "";
  return `${shown}${rest}@${domain}`;
}

// ---------------------------------------------------------------------
// Templates
// ---------------------------------------------------------------------

export const mockTemplates: TemplateDefinition[] = [
  {
    key: "employment_verification",
    name: "Employment Verification",
    version: "v4.2",
    status: "active",
    channel: "email",
    category: "employer_outreach",
    variables: [
      "candidate_name",
      "role",
      "organization_name",
      "employment_dates",
      "verification_link",
    ],
    subjectPreview: "Verification request for {{candidate_name}} — {{role}}",
    bodyPreview:
      "Hello,\n\nKairo is verifying employment details for {{candidate_name}} ({{role}}) at {{organization_name}}. Please confirm the employment dates listed at {{verification_link}}.\n\nThank you,\nKairo Verification Team",
    updatedAt: iso(45),
  },
  {
    key: "education_verification",
    name: "Education Verification",
    version: "v2.1",
    status: "active",
    channel: "email",
    category: "employer_outreach",
    variables: [
      "candidate_name",
      "program",
      "institution_name",
      "graduation_year",
      "verification_link",
    ],
    subjectPreview: "Verification of {{program}} for {{candidate_name}}",
    bodyPreview:
      "Dear Registrar,\n\nPlease confirm {{candidate_name}} completed {{program}} at {{institution_name}} in {{graduation_year}}. Use {{verification_link}} to respond securely.\n\nKairo",
    updatedAt: iso(60),
  },
  {
    key: "certification_verification",
    name: "Certification Verification",
    version: "v1.4",
    status: "active",
    channel: "email",
    category: "employer_outreach",
    variables: ["candidate_name", "certification_name", "issuer", "credential_id"],
    subjectPreview: "Confirm credential {{credential_id}} for {{candidate_name}}",
    bodyPreview:
      "Hello,\n\nWe are verifying credential {{credential_id}} ({{certification_name}}) issued by {{issuer}} to {{candidate_name}}. Kindly confirm status via the secure link.\n\nKairo",
    updatedAt: iso(90),
  },
  {
    key: "reference_verification",
    name: "Reference Verification",
    version: "v1.0",
    status: "active",
    channel: "email",
    category: "employer_outreach",
    variables: ["candidate_name", "reference_name", "context"],
    subjectPreview: "Reference request for {{candidate_name}}",
    bodyPreview:
      "Hello {{reference_name}},\n\n{{candidate_name}} listed you as a reference on Kairo. Please respond to a short set of verification questions using the secure link.\n\nKairo",
    updatedAt: iso(120),
  },
  {
    key: "reminder",
    name: "Reminder",
    version: "v3.0",
    status: "active",
    channel: "email",
    category: "employer_reminder",
    variables: ["organization_name", "candidate_name", "days_pending"],
    subjectPreview: "Reminder — verification for {{candidate_name}}",
    bodyPreview:
      "This is a courtesy reminder — a verification request for {{candidate_name}} has been pending {{days_pending}} days.",
    updatedAt: iso(30),
  },
  {
    key: "clarification",
    name: "Clarification",
    version: "v1.2",
    status: "active",
    channel: "email",
    category: "employer_clarification",
    variables: ["candidate_name", "question", "verification_link"],
    subjectPreview: "Clarification needed — {{candidate_name}}",
    bodyPreview:
      "Hello,\n\nThank you for your response. We need a small clarification: {{question}}. Please reply via {{verification_link}}.\n\nKairo",
    updatedAt: iso(50),
  },
  {
    key: "platform_verification",
    name: "Platform Verification",
    version: "v1.0",
    status: "active",
    channel: "email",
    category: "platform_verification",
    variables: ["candidate_name", "platform_name"],
    subjectPreview: "Platform verification for {{candidate_name}} — {{platform_name}}",
    bodyPreview:
      "Verifying {{candidate_name}}'s activity on {{platform_name}} via public profile and API.",
    updatedAt: iso(180),
  },
];

export function getTemplate(key: TemplateKey): TemplateDefinition | undefined {
  return mockTemplates.find((t) => t.key === key);
}

// ---------------------------------------------------------------------
// Communications — deterministic derivation from verification cases
// ---------------------------------------------------------------------

interface CommSeed {
  caseIndex: number; // 0-based index into mockVerificationCases
  channel?: CommunicationChannel;
  type: CommunicationType;
  template: TemplateKey;
  status: CommunicationStatus;
  sentDaysAgo: number;
  attempts?: number;
  awaitingResponse?: boolean;
  addResponse?: EmployerResponseRecord["outcome"];
  addFailure?: FailureReason;
  followUpInDays?: number; // schedule reminder ahead
  extraOpens?: boolean;
  extraLinkOpen?: boolean;
  reminderDaysAgo?: number;
  attentionTags?: string[];
}

const SEEDS: CommSeed[] = [
  {
    caseIndex: 0,
    type: "employer_outreach",
    template: "employment_verification",
    status: "delivered",
    sentDaysAgo: 2,
    attempts: 1,
    awaitingResponse: true,
    extraOpens: true,
    followUpInDays: 1,
    attentionTags: ["awaiting_reply"],
  },
  {
    caseIndex: 1,
    type: "candidate_notification",
    template: "reminder",
    status: "delivered",
    sentDaysAgo: 1,
    attempts: 1,
  },
  {
    caseIndex: 2,
    type: "employer_outreach",
    template: "employment_verification",
    status: "awaiting_response",
    sentDaysAgo: 4,
    attempts: 2,
    awaitingResponse: true,
    extraOpens: true,
    extraLinkOpen: true,
    reminderDaysAgo: 1,
    followUpInDays: 2,
    attentionTags: ["awaiting_reply"],
  },
  {
    caseIndex: 3,
    type: "candidate_notification",
    template: "clarification",
    status: "opened",
    sentDaysAgo: 1,
    attempts: 1,
  },
  {
    caseIndex: 4,
    type: "employer_outreach",
    template: "employment_verification",
    status: "failed",
    sentDaysAgo: 3,
    attempts: 3,
    addFailure: "invalid_contact",
    attentionTags: ["needs_alt_contact"],
  },
  {
    caseIndex: 5,
    type: "employer_outreach",
    template: "education_verification",
    status: "delivered",
    sentDaysAgo: 2,
    attempts: 1,
    awaitingResponse: true,
    extraOpens: true,
    followUpInDays: 3,
  },
  {
    caseIndex: 6,
    type: "employer_outreach",
    template: "certification_verification",
    status: "responded",
    sentDaysAgo: 6,
    attempts: 1,
    extraOpens: true,
    extraLinkOpen: true,
    addResponse: "confirmed",
  },
  {
    caseIndex: 7,
    type: "employer_outreach",
    template: "employment_verification",
    status: "bounced",
    sentDaysAgo: 5,
    attempts: 2,
    addFailure: "hard_bounce",
    attentionTags: ["needs_alt_contact"],
  },
  {
    caseIndex: 8,
    type: "employer_outreach",
    template: "employment_verification",
    status: "awaiting_response",
    sentDaysAgo: 3,
    attempts: 1,
    awaitingResponse: true,
    extraOpens: true,
    followUpInDays: 0,
  },
  {
    caseIndex: 9,
    type: "employer_outreach",
    template: "employment_verification",
    status: "delivered",
    sentDaysAgo: 1,
    attempts: 1,
    awaitingResponse: true,
  },
  {
    caseIndex: 10,
    type: "employer_outreach",
    template: "employment_verification",
    status: "responded",
    sentDaysAgo: 8,
    attempts: 2,
    extraOpens: true,
    extraLinkOpen: true,
    addResponse: "partial",
  },
  {
    caseIndex: 11,
    type: "employer_outreach",
    template: "reference_verification",
    status: "delivered",
    sentDaysAgo: 2,
    attempts: 1,
    awaitingResponse: true,
    followUpInDays: 2,
  },
  {
    caseIndex: 12,
    type: "employer_reminder",
    template: "reminder",
    status: "delivered",
    sentDaysAgo: 0,
    attempts: 1,
  },
  {
    caseIndex: 13,
    type: "employer_outreach",
    template: "employment_verification",
    status: "complaint",
    sentDaysAgo: 10,
    attempts: 2,
    addFailure: "complaint",
    attentionTags: ["trust_safety_review"],
  },
  {
    caseIndex: 14,
    type: "platform_verification",
    template: "platform_verification",
    status: "responded",
    sentDaysAgo: 12,
    attempts: 1,
    addResponse: "confirmed",
  },
  {
    caseIndex: 15,
    type: "platform_verification",
    template: "platform_verification",
    status: "delivered",
    sentDaysAgo: 4,
    attempts: 1,
  },
  {
    caseIndex: 16,
    type: "employer_outreach",
    template: "employment_verification",
    status: "suppressed",
    sentDaysAgo: 7,
    attempts: 4,
    addFailure: "attempt_limit_reached",
    attentionTags: ["needs_alt_contact"],
  },
  {
    caseIndex: 17,
    type: "employer_outreach",
    template: "employment_verification",
    status: "queued",
    sentDaysAgo: 0,
    attempts: 1,
  },
  {
    caseIndex: 18,
    type: "employer_outreach",
    template: "education_verification",
    status: "responded",
    sentDaysAgo: 14,
    attempts: 1,
    addResponse: "denied",
  },
  {
    caseIndex: 19,
    type: "employer_outreach",
    template: "employment_verification",
    status: "failed",
    sentDaysAgo: 5,
    attempts: 3,
    addFailure: "delivery_failure",
    attentionTags: ["retry_pending"],
  },
  {
    caseIndex: 20,
    type: "employer_reminder",
    template: "reminder",
    status: "delivered",
    sentDaysAgo: 2,
    attempts: 1,
    followUpInDays: 4,
  },
  {
    caseIndex: 21,
    type: "employer_outreach",
    template: "employment_verification",
    status: "opened",
    sentDaysAgo: 3,
    attempts: 1,
    awaitingResponse: true,
    extraOpens: true,
    followUpInDays: 0,
  },
  {
    caseIndex: 22,
    type: "internal_alert",
    template: "clarification",
    status: "delivered",
    sentDaysAgo: 6,
    attempts: 1,
  },
  {
    caseIndex: 23,
    type: "employer_outreach",
    template: "employment_verification",
    status: "pending",
    sentDaysAgo: 0,
    attempts: 1,
  },
];

function buildEvents(seed: CommSeed): DeliveryEvent[] {
  const events: DeliveryEvent[] = [];
  const base = seed.sentDaysAgo;
  events.push({ id: "prepared", at: iso(base, 2, 30), kind: "prepared" });
  events.push({ id: "queued", at: iso(base, 2, 15), kind: "queued" });
  if (seed.status === "pending" || seed.status === "queued") return events;

  events.push({ id: "delivered", at: iso(base, 2), kind: "delivered" });
  if (seed.extraOpens) events.push({ id: "opened", at: iso(base, 1), kind: "opened" });
  if (seed.extraLinkOpen)
    events.push({ id: "link_open", at: iso(base, 0, 45), kind: "verification_link_opened" });
  if (seed.reminderDaysAgo != null) {
    events.push({ id: "reminder", at: iso(seed.reminderDaysAgo, 3), kind: "reminder_sent" });
  }
  if (seed.addResponse)
    events.push({
      id: "employer_responded",
      at: iso(Math.max(0, base - 1)),
      kind: "employer_responded",
      detail: `Response: ${seed.addResponse}`,
    });
  if (seed.addFailure) {
    const kind: DeliveryEventKind =
      seed.addFailure === "hard_bounce" || seed.addFailure === "soft_bounce"
        ? "bounce"
        : seed.addFailure === "complaint"
          ? "complaint"
          : seed.addFailure === "suppressed"
            ? "suppressed"
            : "failed";
    events.push({
      id: "failure",
      at: iso(Math.max(0, base - 1), 1),
      kind,
      detail: FAILURE_REASON_LABEL[seed.addFailure],
    });
  }
  return events;
}

function toCommunication(seed: CommSeed, index: number): Communication {
  const caseRow = mockVerificationCases[seed.caseIndex];
  const template = getTemplate(seed.template)!;
  const orgDomain = caseRow.organizationName.toLowerCase().replace(/[^a-z0-9]+/g, "") + ".example";
  const contactName = "HR Team";
  const contactEmail = mask("hr", orgDomain);
  const events = buildEvents(seed);
  const lastEvent = events[events.length - 1];
  const failures: FailureRecord[] = seed.addFailure
    ? [
        {
          id: `${index}-f1`,
          at: iso(Math.max(0, seed.sentDaysAgo - 1), 1),
          reason: seed.addFailure,
          detail: `Delivery to ${contactEmail} failed: ${FAILURE_REASON_LABEL[seed.addFailure]}.`,
        },
      ]
    : [];
  const responses: EmployerResponseRecord[] = seed.addResponse
    ? [
        {
          id: `${index}-r1`,
          at: iso(Math.max(0, seed.sentDaysAgo - 1)),
          outcome: seed.addResponse,
          body:
            seed.addResponse === "confirmed"
              ? "We confirm the employment details as listed."
              : seed.addResponse === "denied"
                ? "We cannot confirm the details as listed — please review."
                : seed.addResponse === "partial"
                  ? "Employment dates confirmed; role title differs slightly."
                  : "We are unable to verify at this time.",
          actionRequired:
            seed.addResponse === "denied"
              ? "Reject or request additional evidence."
              : seed.addResponse === "partial"
                ? "Clarify role title with candidate."
                : undefined,
        },
      ]
    : [];
  const followUps: FollowUpRecord[] =
    seed.followUpInDays != null
      ? [
          {
            id: `${index}-fu1`,
            scheduledAt: isoAhead(seed.followUpInDays, seed.followUpInDays === 0 ? 4 : 0),
            attempt: (seed.attempts ?? 1) + 1,
            status: "pending",
            reason: "Automatic reminder if no response received.",
          },
        ]
      : [];
  const reference = `COMM-${String(24500 + index).padStart(5, "0")}`;
  const subject = template.subjectPreview
    .replace("{{candidate_name}}", caseRow.candidateName)
    .replace("{{role}}", caseRow.roleOrProgram)
    .replace("{{program}}", caseRow.roleOrProgram)
    .replace("{{organization_name}}", caseRow.organizationName)
    .replace("{{platform_name}}", caseRow.organizationName)
    .replace("{{reference_name}}", contactName)
    .replace("{{certification_name}}", caseRow.roleOrProgram)
    .replace("{{credential_id}}", `CRED-${caseRow.candidateId.replace("cand-", "")}`);

  const notes: InternalNoteSeed[] =
    seed.addFailure || seed.addResponse
      ? [
          {
            id: `${index}-n1`,
            at: iso(Math.max(0, seed.sentDaysAgo - 1), 2),
            actor: "Aman Jha",
            actorRole: "Operations Lead",
            body: seed.addFailure
              ? `Recorded ${FAILURE_REASON_LABEL[seed.addFailure].toLowerCase()} — awaiting alternative contact.`
              : `Response logged (${seed.addResponse}). Case queued for follow-up.`,
          },
        ]
      : [];

  return {
    id: `comm-${String(index + 1).padStart(3, "0")}`,
    reference,
    channel: seed.channel ?? "email",
    direction: "outbound",
    type: seed.type,
    template: seed.template,
    templateVersion: template.version,
    subject,
    status: seed.status,
    caseId: caseRow.id,
    caseReference: caseRow.reference,
    candidateId: caseRow.candidateId,
    candidateName: caseRow.candidateName,
    organizationId: caseRow.organizationId,
    organizationName: caseRow.organizationName,
    contactName,
    contactEmailMasked: contactEmail,
    assignedReviewer: caseRow.assignedReviewer,
    sentAt: iso(seed.sentDaysAgo, 2),
    lastEventAt: lastEvent?.at ?? iso(seed.sentDaysAgo, 2),
    nextFollowUpAt: followUps[0]?.scheduledAt,
    attemptCount: seed.attempts ?? 1,
    awaitingResponse: !!seed.awaitingResponse,
    events,
    followUps,
    failures,
    responses,
    internalNotes: notes,
    attentionTags: seed.attentionTags ?? [],
  };
}

export const mockCommunications: Communication[] = SEEDS.map(toCommunication);

// ---------------------------------------------------------------------
// Accessors
// ---------------------------------------------------------------------

export function getCommunication(id: string): Communication | undefined {
  return mockCommunications.find((c) => c.id === id);
}

export function getCommunicationsForCase(caseId: string): Communication[] {
  return mockCommunications.filter((c) => c.caseId === caseId);
}

const FAILED_STATUSES = new Set<CommunicationStatus>([
  "failed",
  "bounced",
  "complaint",
  "suppressed",
]);
export function isFailedStatus(s: CommunicationStatus): boolean {
  return FAILED_STATUSES.has(s);
}

/** Overview-facing metrics summary. */
export function getCommunicationMetrics() {
  const list = mockCommunications;
  const today = new Date(NOW);
  today.setUTCHours(23, 59, 59, 999);
  const followUpsDueToday = list.filter(
    (c) => c.nextFollowUpAt && new Date(c.nextFollowUpAt).getTime() <= today.getTime(),
  ).length;
  return {
    total: list.length,
    pending: list.filter((c) => c.status === "pending" || c.status === "queued").length,
    delivered: list.filter((c) => c.status === "delivered" || c.status === "opened").length,
    awaitingResponse: list.filter((c) => c.awaitingResponse).length,
    failed: list.filter((c) => c.status === "failed").length,
    bounced: list.filter((c) => c.status === "bounced").length,
    complaints: list.filter((c) => c.status === "complaint").length,
    suppressed: list.filter((c) => c.status === "suppressed").length,
    responded: list.filter((c) => c.status === "responded").length,
    followUpsDueToday,
    failedTotal: list.filter((c) => FAILED_STATUSES.has(c.status)).length,
  };
}
