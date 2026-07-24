/**
 * Kairo Admin — System Operations mock data.
 *
 * Deterministic, isolated. Represents the shape of a future
 * observability / platform-control API. NOT connected to real infra.
 * Never mutate the exported constants — use `useSystemSession` for
 * session overlays.
 */

// ---------------------------------------------------------------------
// Shared enums
// ---------------------------------------------------------------------

export type ServiceHealthState = "operational" | "degraded" | "delayed" | "incident" | "unknown";

export const SERVICE_HEALTH_LABEL: Record<ServiceHealthState, string> = {
  operational: "Operational",
  degraded: "Degraded",
  delayed: "Delayed",
  incident: "Incident",
  unknown: "Unknown",
};

// ---------------------------------------------------------------------
// Platform health
// ---------------------------------------------------------------------

export type PlatformServiceKey =
  | "api"
  | "postgres"
  | "redis"
  | "document_storage"
  | "email"
  | "sms"
  | "auth"
  | "public_passport"
  | "verification_engine"
  | "admin_portal"
  | "background_jobs";

export interface PlatformService {
  id: PlatformServiceKey;
  name: string;
  state: ServiceHealthState;
  lastChecked: string;
  latencyMs: number;
  errorRatePct: number;
  dependency?: string;
  recentIncident?: string;
  note?: string;
}

export const mockPlatformServices: PlatformService[] = [
  {
    id: "api",
    name: "API Gateway",
    state: "operational",
    lastChecked: isoMinutesAgo(1),
    latencyMs: 148,
    errorRatePct: 0.12,
    dependency: "postgres, redis",
  },
  {
    id: "postgres",
    name: "PostgreSQL (primary)",
    state: "operational",
    lastChecked: isoMinutesAgo(1),
    latencyMs: 6,
    errorRatePct: 0.02,
    dependency: "storage volumes",
  },
  {
    id: "redis",
    name: "Redis (cache)",
    state: "operational",
    lastChecked: isoMinutesAgo(1),
    latencyMs: 2,
    errorRatePct: 0.0,
  },
  {
    id: "document_storage",
    name: "Document storage",
    state: "degraded",
    lastChecked: isoMinutesAgo(2),
    latencyMs: 812,
    errorRatePct: 3.4,
    recentIncident: "Elevated PUT latency (region eu-west-1)",
    note: "Retention policy review overdue.",
  },
  {
    id: "email",
    name: "Email provider",
    state: "degraded",
    lastChecked: isoMinutesAgo(3),
    latencyMs: 420,
    errorRatePct: 4.7,
    recentIncident: "Bounces on 2 employer domains",
    dependency: "external ESP",
  },
  {
    id: "sms",
    name: "SMS provider",
    state: "operational",
    lastChecked: isoMinutesAgo(4),
    latencyMs: 690,
    errorRatePct: 0.9,
    dependency: "external SMS gateway",
  },
  {
    id: "auth",
    name: "Authentication",
    state: "operational",
    lastChecked: isoMinutesAgo(1),
    latencyMs: 92,
    errorRatePct: 0.04,
    dependency: "postgres",
  },
  {
    id: "public_passport",
    name: "Public Trust Passport",
    state: "operational",
    lastChecked: isoMinutesAgo(2),
    latencyMs: 210,
    errorRatePct: 0.15,
    dependency: "api, document storage",
  },
  {
    id: "verification_engine",
    name: "Verification engine",
    state: "delayed",
    lastChecked: isoMinutesAgo(2),
    latencyMs: 1980,
    errorRatePct: 0.8,
    note: "OCR backlog above threshold.",
  },
  {
    id: "admin_portal",
    name: "Admin portal",
    state: "operational",
    lastChecked: isoMinutesAgo(1),
    latencyMs: 118,
    errorRatePct: 0.0,
  },
  {
    id: "background_jobs",
    name: "Background jobs",
    state: "degraded",
    lastChecked: isoMinutesAgo(1),
    latencyMs: 0,
    errorRatePct: 2.1,
    note: "OCR queue depth elevated.",
  },
];

// ---------------------------------------------------------------------
// Background jobs
// ---------------------------------------------------------------------

export type JobType =
  | "document_processing"
  | "ocr_extraction"
  | "verification_reminder"
  | "invitation_expiry"
  | "passport_view_aggregation"
  | "trust_score_recalc"
  | "email_delivery"
  | "sms_delivery"
  | "data_export"
  | "cleanup";

export const JOB_TYPE_LABEL: Record<JobType, string> = {
  document_processing: "Document processing",
  ocr_extraction: "OCR extraction",
  verification_reminder: "Verification reminder",
  invitation_expiry: "Invitation expiry",
  passport_view_aggregation: "Passport view aggregation",
  trust_score_recalc: "Trust Score recalculation",
  email_delivery: "Email delivery",
  sms_delivery: "SMS delivery",
  data_export: "Data export",
  cleanup: "Cleanup",
};

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "retrying" | "cancelled";

export const JOB_STATUS_LABEL: Record<JobStatus, string> = {
  queued: "Queued",
  running: "Running",
  succeeded: "Succeeded",
  failed: "Failed",
  retrying: "Retrying",
  cancelled: "Cancelled",
};

export interface JobAttempt {
  attempt: number;
  startedAt: string;
  finishedAt?: string;
  outcome: "succeeded" | "failed" | "cancelled";
  error?: string;
  durationMs: number;
}

export interface RelatedRecord {
  kind: "user" | "verification_case" | "organization" | "communication" | "risk_investigation";
  id: string;
  label: string;
  linkTo?: string;
}

export interface BackgroundJob {
  id: string;
  reference: string; // human-friendly
  type: JobType;
  status: JobStatus;
  createdAt: string;
  startedAt?: string;
  completedAt?: string;
  attempts: number;
  maxAttempts: number;
  owner: string; // service that enqueued
  related: RelatedRecord[];
  lastError?: string;
  payloadPreview: Record<string, string | number | boolean>;
  attemptHistory: JobAttempt[];
  retryable: boolean;
  durationMs?: number;
  preparedAction?: "retry" | "cancel" | "escalate" | "reviewed";
}

export const mockBackgroundJobs: BackgroundJob[] = [
  {
    id: "job-1001",
    reference: "JOB-1001",
    type: "ocr_extraction",
    status: "failed",
    createdAt: isoMinutesAgo(38),
    startedAt: isoMinutesAgo(37),
    completedAt: isoMinutesAgo(35),
    attempts: 3,
    maxAttempts: 5,
    owner: "verification_engine",
    related: [
      {
        kind: "verification_case",
        id: "vc-004",
        label: "Case VC-004",
        linkTo: "/admin/verifications/vc-004",
      },
    ],
    lastError: "OCR provider returned 502 (Bad Gateway) — upstream timeout after 30s.",
    payloadPreview: { documentId: "doc-9812", pages: 3, language: "en", region: "eu-west-1" },
    attemptHistory: [
      {
        attempt: 1,
        startedAt: isoMinutesAgo(37),
        finishedAt: isoMinutesAgo(37),
        outcome: "failed",
        error: "Upstream 502",
        durationMs: 32000,
      },
      {
        attempt: 2,
        startedAt: isoMinutesAgo(36),
        finishedAt: isoMinutesAgo(36),
        outcome: "failed",
        error: "Upstream 502",
        durationMs: 31500,
      },
      {
        attempt: 3,
        startedAt: isoMinutesAgo(35),
        finishedAt: isoMinutesAgo(35),
        outcome: "failed",
        error: "Upstream 502",
        durationMs: 30800,
      },
    ],
    retryable: true,
    durationMs: 94300,
  },
  {
    id: "job-1002",
    reference: "JOB-1002",
    type: "email_delivery",
    status: "failed",
    createdAt: isoMinutesAgo(22),
    startedAt: isoMinutesAgo(22),
    completedAt: isoMinutesAgo(22),
    attempts: 1,
    maxAttempts: 3,
    owner: "communications",
    related: [
      {
        kind: "communication",
        id: "cm-2201",
        label: "Outreach CM-2201",
        linkTo: "/admin/communications",
      },
    ],
    lastError: "SMTP 550 5.1.1: recipient address rejected — mailbox unavailable.",
    payloadPreview: { to: "h***@northwind.example", template: "outreach_v3", provider: "postmark" },
    attemptHistory: [
      {
        attempt: 1,
        startedAt: isoMinutesAgo(22),
        finishedAt: isoMinutesAgo(22),
        outcome: "failed",
        error: "SMTP 550",
        durationMs: 1200,
      },
    ],
    retryable: false,
    durationMs: 1200,
  },
  {
    id: "job-1003",
    reference: "JOB-1003",
    type: "document_processing",
    status: "running",
    createdAt: isoMinutesAgo(6),
    startedAt: isoMinutesAgo(5),
    attempts: 1,
    maxAttempts: 3,
    owner: "verification_engine",
    related: [
      {
        kind: "verification_case",
        id: "vc-011",
        label: "Case VC-011",
        linkTo: "/admin/verifications/vc-011",
      },
    ],
    payloadPreview: { documentId: "doc-9820", pages: 2, kind: "employment_letter" },
    attemptHistory: [
      { attempt: 1, startedAt: isoMinutesAgo(5), outcome: "succeeded", durationMs: 0 },
    ],
    retryable: false,
  },
  {
    id: "job-1004",
    reference: "JOB-1004",
    type: "trust_score_recalc",
    status: "queued",
    createdAt: isoMinutesAgo(2),
    attempts: 0,
    maxAttempts: 3,
    owner: "trust_engine",
    related: [
      { kind: "user", id: "usr-1042", label: "Priya Shah", linkTo: "/admin/users/usr-1042" },
    ],
    payloadPreview: { userId: "usr-1042", trigger: "evidence_added" },
    attemptHistory: [],
    retryable: false,
  },
  {
    id: "job-1005",
    reference: "JOB-1005",
    type: "verification_reminder",
    status: "succeeded",
    createdAt: isoMinutesAgo(120),
    startedAt: isoMinutesAgo(119),
    completedAt: isoMinutesAgo(119),
    attempts: 1,
    maxAttempts: 3,
    owner: "reminder_scheduler",
    related: [
      {
        kind: "verification_case",
        id: "vc-002",
        label: "Case VC-002",
        linkTo: "/admin/verifications/vc-002",
      },
    ],
    payloadPreview: { channel: "email", template: "reminder_first" },
    attemptHistory: [
      {
        attempt: 1,
        startedAt: isoMinutesAgo(119),
        finishedAt: isoMinutesAgo(119),
        outcome: "succeeded",
        durationMs: 640,
      },
    ],
    retryable: false,
    durationMs: 640,
  },
  {
    id: "job-1006",
    reference: "JOB-1006",
    type: "passport_view_aggregation",
    status: "succeeded",
    createdAt: isoMinutesAgo(60),
    startedAt: isoMinutesAgo(60),
    completedAt: isoMinutesAgo(59),
    attempts: 1,
    maxAttempts: 3,
    owner: "analytics_scheduler",
    related: [],
    payloadPreview: { window: "hourly", partitions: 4 },
    attemptHistory: [
      {
        attempt: 1,
        startedAt: isoMinutesAgo(60),
        finishedAt: isoMinutesAgo(59),
        outcome: "succeeded",
        durationMs: 42000,
      },
    ],
    retryable: false,
    durationMs: 42000,
  },
  {
    id: "job-1007",
    reference: "JOB-1007",
    type: "invitation_expiry",
    status: "retrying",
    createdAt: isoMinutesAgo(15),
    startedAt: isoMinutesAgo(15),
    attempts: 2,
    maxAttempts: 5,
    owner: "reminder_scheduler",
    related: [
      {
        kind: "organization",
        id: "org-108",
        label: "Northwind Global",
        linkTo: "/admin/registry/org-108",
      },
    ],
    lastError: "Rate limited by email provider — retrying with backoff.",
    payloadPreview: { batchSize: 40, provider: "postmark" },
    attemptHistory: [
      {
        attempt: 1,
        startedAt: isoMinutesAgo(15),
        finishedAt: isoMinutesAgo(15),
        outcome: "failed",
        error: "429 Too Many Requests",
        durationMs: 800,
      },
      {
        attempt: 2,
        startedAt: isoMinutesAgo(14),
        finishedAt: isoMinutesAgo(14),
        outcome: "failed",
        error: "429 Too Many Requests",
        durationMs: 820,
      },
    ],
    retryable: true,
  },
  {
    id: "job-1008",
    reference: "JOB-1008",
    type: "data_export",
    status: "succeeded",
    createdAt: isoMinutesAgo(240),
    startedAt: isoMinutesAgo(240),
    completedAt: isoMinutesAgo(238),
    attempts: 1,
    maxAttempts: 2,
    owner: "admin_portal",
    related: [
      { kind: "user", id: "usr-1042", label: "Priya Shah", linkTo: "/admin/users/usr-1042" },
    ],
    payloadPreview: { format: "csv", rows: 214, requestedBy: "Aman Jha" },
    attemptHistory: [
      {
        attempt: 1,
        startedAt: isoMinutesAgo(240),
        finishedAt: isoMinutesAgo(238),
        outcome: "succeeded",
        durationMs: 108000,
      },
    ],
    retryable: false,
    durationMs: 108000,
  },
  {
    id: "job-1009",
    reference: "JOB-1009",
    type: "cleanup",
    status: "succeeded",
    createdAt: isoMinutesAgo(360),
    startedAt: isoMinutesAgo(360),
    completedAt: isoMinutesAgo(358),
    attempts: 1,
    maxAttempts: 3,
    owner: "cleanup_scheduler",
    related: [],
    payloadPreview: { target: "temp_uploads", olderThanHours: 24 },
    attemptHistory: [
      {
        attempt: 1,
        startedAt: isoMinutesAgo(360),
        finishedAt: isoMinutesAgo(358),
        outcome: "succeeded",
        durationMs: 120000,
      },
    ],
    retryable: false,
    durationMs: 120000,
  },
  {
    id: "job-1010",
    reference: "JOB-1010",
    type: "sms_delivery",
    status: "failed",
    createdAt: isoMinutesAgo(48),
    startedAt: isoMinutesAgo(48),
    completedAt: isoMinutesAgo(48),
    attempts: 3,
    maxAttempts: 3,
    owner: "communications",
    related: [
      { kind: "user", id: "usr-1088", label: "Marco Bianchi", linkTo: "/admin/users/usr-1088" },
    ],
    lastError: "Carrier reported invalid destination number.",
    payloadPreview: { to: "+39********12", template: "otp_v2" },
    attemptHistory: [
      {
        attempt: 1,
        startedAt: isoMinutesAgo(48),
        finishedAt: isoMinutesAgo(48),
        outcome: "failed",
        error: "Invalid destination",
        durationMs: 210,
      },
      {
        attempt: 2,
        startedAt: isoMinutesAgo(47),
        finishedAt: isoMinutesAgo(47),
        outcome: "failed",
        error: "Invalid destination",
        durationMs: 220,
      },
      {
        attempt: 3,
        startedAt: isoMinutesAgo(46),
        finishedAt: isoMinutesAgo(46),
        outcome: "failed",
        error: "Invalid destination",
        durationMs: 205,
      },
    ],
    retryable: false,
    durationMs: 635,
  },
];

export function getJobById(id: string): BackgroundJob | undefined {
  return mockBackgroundJobs.find((j) => j.id === id);
}

// ---------------------------------------------------------------------
// Feature flags
// ---------------------------------------------------------------------

export type FlagEnvironment = "development" | "staging" | "production";
export type FlagState = "off" | "on" | "rollout";
export type FlagRiskLevel = "low" | "medium" | "high" | "critical";

export const FLAG_STATE_LABEL: Record<FlagState, string> = {
  off: "Off",
  on: "On",
  rollout: "Rollout",
};

export interface FeatureFlag {
  id: string;
  key: string;
  name: string;
  description: string;
  environment: FlagEnvironment;
  state: FlagState;
  rolloutPct: number;
  owner: string;
  lastUpdated: string;
  dependencies: string[];
  risk: FlagRiskLevel;
}

export const mockFeatureFlags: FeatureFlag[] = [
  {
    id: "ff-01",
    key: "resume_parsing",
    name: "Resume parsing",
    description: "Automatically extract structured fields from uploaded resumes.",
    environment: "production",
    state: "on",
    rolloutPct: 100,
    owner: "Verification Engine",
    lastUpdated: isoDaysAgo(3),
    dependencies: [],
    risk: "medium",
  },
  {
    id: "ff-02",
    key: "digilocker_integration",
    name: "DigiLocker integration",
    description: "Fetch official Indian government documents from DigiLocker.",
    environment: "production",
    state: "rollout",
    rolloutPct: 35,
    owner: "Verification Engine",
    lastUpdated: isoDaysAgo(1),
    dependencies: ["resume_parsing"],
    risk: "high",
  },
  {
    id: "ff-03",
    key: "passport_view_tracking",
    name: "Passport view tracking",
    description: "Record employer / recruiter views of Trust Passports.",
    environment: "production",
    state: "on",
    rolloutPct: 100,
    owner: "Analytics",
    lastUpdated: isoDaysAgo(9),
    dependencies: [],
    risk: "low",
  },
  {
    id: "ff-04",
    key: "trust_score_v2",
    name: "Trust Score v2",
    description: "Second-generation scoring model with stricter fraud heuristics.",
    environment: "staging",
    state: "on",
    rolloutPct: 100,
    owner: "Trust Engine",
    lastUpdated: isoDaysAgo(2),
    dependencies: ["resume_parsing"],
    risk: "critical",
  },
  {
    id: "ff-05",
    key: "university_verification",
    name: "University verification",
    description: "Automated verification against university registries.",
    environment: "production",
    state: "rollout",
    rolloutPct: 10,
    owner: "Verification Engine",
    lastUpdated: isoDaysAgo(5),
    dependencies: [],
    risk: "medium",
  },
  {
    id: "ff-06",
    key: "candidate_notifications",
    name: "Candidate notifications",
    description: "In-app notification center for candidates.",
    environment: "production",
    state: "on",
    rolloutPct: 100,
    owner: "Product",
    lastUpdated: isoDaysAgo(14),
    dependencies: [],
    risk: "low",
  },
  {
    id: "ff-07",
    key: "hr_onboarding",
    name: "HR onboarding",
    description: "Guided HR employer onboarding flow.",
    environment: "production",
    state: "off",
    rolloutPct: 0,
    owner: "Growth",
    lastUpdated: isoDaysAgo(21),
    dependencies: [],
    risk: "low",
  },
  {
    id: "ff-08",
    key: "public_passport_analytics",
    name: "Public Passport analytics",
    description: "Show aggregated view analytics on public passports.",
    environment: "production",
    state: "rollout",
    rolloutPct: 20,
    owner: "Analytics",
    lastUpdated: isoDaysAgo(4),
    dependencies: ["passport_view_tracking"],
    risk: "medium",
  },
  {
    id: "ff-09",
    key: "document_anomaly_detection",
    name: "Document anomaly detection",
    description: "Detect edited or synthetic documents.",
    environment: "production",
    state: "on",
    rolloutPct: 100,
    owner: "Trust & Safety",
    lastUpdated: isoDaysAgo(1),
    dependencies: [],
    risk: "high",
  },
  {
    id: "ff-10",
    key: "mobile_app_access",
    name: "Mobile app access",
    description: "Allow session refresh from the new mobile app.",
    environment: "staging",
    state: "on",
    rolloutPct: 100,
    owner: "Mobile",
    lastUpdated: isoDaysAgo(7),
    dependencies: [],
    risk: "medium",
  },
];

// ---------------------------------------------------------------------
// Email & SMS logs
// ---------------------------------------------------------------------

export type MessageChannel = "email" | "sms";
export type MessageStatus =
  "queued" | "sent" | "delivered" | "opened" | "bounced" | "failed" | "rejected" | "spam_complaint";

export const MESSAGE_STATUS_LABEL: Record<MessageStatus, string> = {
  queued: "Queued",
  sent: "Sent",
  delivered: "Delivered",
  opened: "Opened",
  bounced: "Bounced",
  failed: "Failed",
  rejected: "Rejected",
  spam_complaint: "Spam complaint",
};

export type MessageKind =
  | "otp"
  | "trust_invitation"
  | "verification_request"
  | "password_reset"
  | "outreach"
  | "candidate_notification";

export const MESSAGE_KIND_LABEL: Record<MessageKind, string> = {
  otp: "OTP",
  trust_invitation: "Trust invitation",
  verification_request: "Verification request",
  password_reset: "Password reset",
  outreach: "Outreach",
  candidate_notification: "Candidate notification",
};

export interface MessageLog {
  id: string;
  reference: string;
  channel: MessageChannel;
  kind: MessageKind;
  recipientMasked: string; // never raw addresses / phone / OTP
  provider: string;
  status: MessageStatus;
  createdAt: string;
  sentAt?: string;
  deliveredAt?: string;
  failedAt?: string;
  failureReason?: string;
  relatedUserId?: string;
  relatedCaseId?: string;
  relatedOrganizationId?: string;
}

export const mockMessageLogs: MessageLog[] = [
  {
    id: "msg-1",
    reference: "MSG-001",
    channel: "email",
    kind: "outreach",
    recipientMasked: "h***@northwind.example",
    provider: "postmark",
    status: "bounced",
    createdAt: isoMinutesAgo(22),
    sentAt: isoMinutesAgo(22),
    failedAt: isoMinutesAgo(22),
    failureReason: "SMTP 550 mailbox unavailable",
    relatedOrganizationId: "org-108",
    relatedCaseId: "vc-004",
  },
  {
    id: "msg-2",
    reference: "MSG-002",
    channel: "email",
    kind: "verification_request",
    recipientMasked: "h***@acme.example",
    provider: "postmark",
    status: "delivered",
    createdAt: isoMinutesAgo(31),
    sentAt: isoMinutesAgo(31),
    deliveredAt: isoMinutesAgo(30),
    relatedOrganizationId: "org-002",
    relatedCaseId: "vc-002",
  },
  {
    id: "msg-3",
    reference: "MSG-003",
    channel: "email",
    kind: "verification_request",
    recipientMasked: "h***@umbrella.example",
    provider: "postmark",
    status: "opened",
    createdAt: isoMinutesAgo(96),
    sentAt: isoMinutesAgo(96),
    deliveredAt: isoMinutesAgo(95),
  },
  {
    id: "msg-4",
    reference: "MSG-004",
    channel: "sms",
    kind: "otp",
    recipientMasked: "+39********12",
    provider: "twilio",
    status: "failed",
    createdAt: isoMinutesAgo(48),
    sentAt: isoMinutesAgo(48),
    failedAt: isoMinutesAgo(48),
    failureReason: "Carrier reported invalid destination",
    relatedUserId: "usr-1088",
  },
  {
    id: "msg-5",
    reference: "MSG-005",
    channel: "sms",
    kind: "otp",
    recipientMasked: "+44********54",
    provider: "twilio",
    status: "delivered",
    createdAt: isoMinutesAgo(11),
    sentAt: isoMinutesAgo(11),
    deliveredAt: isoMinutesAgo(11),
  },
  {
    id: "msg-6",
    reference: "MSG-006",
    channel: "email",
    kind: "password_reset",
    recipientMasked: "p***@example.com",
    provider: "postmark",
    status: "delivered",
    createdAt: isoMinutesAgo(180),
    sentAt: isoMinutesAgo(180),
    deliveredAt: isoMinutesAgo(180),
    relatedUserId: "usr-1042",
  },
  {
    id: "msg-7",
    reference: "MSG-007",
    channel: "email",
    kind: "trust_invitation",
    recipientMasked: "recruiter@***",
    provider: "postmark",
    status: "opened",
    createdAt: isoDaysAgo(1),
    sentAt: isoDaysAgo(1),
    deliveredAt: isoDaysAgo(1),
  },
  {
    id: "msg-8",
    reference: "MSG-008",
    channel: "email",
    kind: "candidate_notification",
    recipientMasked: "j***@example.com",
    provider: "postmark",
    status: "spam_complaint",
    createdAt: isoDaysAgo(2),
    sentAt: isoDaysAgo(2),
    deliveredAt: isoDaysAgo(2),
    failureReason: "Recipient reported as spam",
    relatedUserId: "usr-1042",
  },
  {
    id: "msg-9",
    reference: "MSG-009",
    channel: "email",
    kind: "outreach",
    recipientMasked: "h***@globex.example",
    provider: "postmark",
    status: "rejected",
    createdAt: isoMinutesAgo(240),
    sentAt: isoMinutesAgo(240),
    failedAt: isoMinutesAgo(240),
    failureReason: "Recipient policy rejection",
    relatedOrganizationId: "org-004",
  },
  {
    id: "msg-10",
    reference: "MSG-010",
    channel: "sms",
    kind: "otp",
    recipientMasked: "+91********99",
    provider: "msg91",
    status: "delivered",
    createdAt: isoMinutesAgo(3),
    sentAt: isoMinutesAgo(3),
    deliveredAt: isoMinutesAgo(3),
  },
];

// ---------------------------------------------------------------------
// Audit log
// ---------------------------------------------------------------------

export type AuditResourceKind =
  | "verification_case"
  | "user"
  | "organization"
  | "communication"
  | "risk_investigation"
  | "feature_flag"
  | "background_job"
  | "system"
  | "permissions";

export const AUDIT_RESOURCE_LABEL: Record<AuditResourceKind, string> = {
  verification_case: "Verification case",
  user: "User",
  organization: "Organization",
  communication: "Communication",
  risk_investigation: "Risk investigation",
  feature_flag: "Feature flag",
  background_job: "Background job",
  system: "System",
  permissions: "Permissions",
};

export interface AuditEvent {
  id: string;
  at: string;
  actor: string;
  actorRole: string;
  action: string;
  resourceKind: AuditResourceKind;
  resourceId: string;
  resourceLabel: string;
  result: "success" | "failure" | "prepared";
  source: string; // e.g., "admin_portal"
  ipSummary: string; // masked, e.g., "203.0.113.xxx (Berlin, DE)"
  reason?: string;
  linkTo?: string;
}

export const mockAuditEvents: AuditEvent[] = [
  {
    id: "aud-001",
    at: isoMinutesAgo(4),
    actor: "Aman Jha",
    actorRole: "Operations Lead",
    action: "Verified case",
    resourceKind: "verification_case",
    resourceId: "vc-002",
    resourceLabel: "VC-002",
    result: "success",
    source: "admin_portal",
    ipSummary: "203.0.113.xxx (Berlin, DE)",
    linkTo: "/admin/verifications/vc-002",
  },
  {
    id: "aud-002",
    at: isoMinutesAgo(11),
    actor: "System",
    actorRole: "system",
    action: "Email delivery failed",
    resourceKind: "communication",
    resourceId: "cm-2201",
    resourceLabel: "MSG-001",
    result: "failure",
    source: "worker",
    ipSummary: "internal",
    reason: "SMTP 550",
  },
  {
    id: "aud-003",
    at: isoMinutesAgo(23),
    actor: "Priya Shah",
    actorRole: "Candidate",
    action: "Resubmitted corrections",
    resourceKind: "verification_case",
    resourceId: "vc-004",
    resourceLabel: "VC-004",
    result: "success",
    source: "candidate_app",
    ipSummary: "198.51.100.xxx (Mumbai, IN)",
  },
  {
    id: "aud-004",
    at: isoMinutesAgo(41),
    actor: "Aman Jha",
    actorRole: "Operations Lead",
    action: "Resolved organization match",
    resourceKind: "organization",
    resourceId: "org-004",
    resourceLabel: "Globex Ltd",
    result: "success",
    source: "admin_portal",
    ipSummary: "203.0.113.xxx (Berlin, DE)",
    linkTo: "/admin/registry/org-004",
  },
  {
    id: "aud-005",
    at: isoMinutesAgo(58),
    actor: "Daniel Kim",
    actorRole: "Reviewer",
    action: "Requested corrections",
    resourceKind: "verification_case",
    resourceId: "vc-007",
    resourceLabel: "VC-007",
    result: "success",
    source: "admin_portal",
    ipSummary: "192.0.2.xxx (Seoul, KR)",
  },
  {
    id: "aud-006",
    at: isoMinutesAgo(90),
    actor: "Aman Jha",
    actorRole: "Operations Lead",
    action: "Prepared feature flag change",
    resourceKind: "feature_flag",
    resourceId: "ff-02",
    resourceLabel: "digilocker_integration",
    result: "prepared",
    source: "admin_portal",
    ipSummary: "203.0.113.xxx (Berlin, DE)",
    reason: "Increase rollout to 50%",
  },
  {
    id: "aud-007",
    at: isoMinutesAgo(120),
    actor: "System",
    actorRole: "system",
    action: "Escalated alert",
    resourceKind: "system",
    resourceId: "alert-002",
    resourceLabel: "Email delivery degraded",
    result: "success",
    source: "monitor",
    ipSummary: "internal",
  },
  {
    id: "aud-008",
    at: isoMinutesAgo(180),
    actor: "Aman Jha",
    actorRole: "Operations Lead",
    action: "Prepared job retry",
    resourceKind: "background_job",
    resourceId: "job-1001",
    resourceLabel: "JOB-1001",
    result: "prepared",
    source: "admin_portal",
    ipSummary: "203.0.113.xxx (Berlin, DE)",
  },
  {
    id: "aud-009",
    at: isoDaysAgo(1),
    actor: "Aman Jha",
    actorRole: "Operations Lead",
    action: "Assigned reviewer",
    resourceKind: "verification_case",
    resourceId: "vc-009",
    resourceLabel: "VC-009",
    result: "success",
    source: "admin_portal",
    ipSummary: "203.0.113.xxx (Berlin, DE)",
  },
  {
    id: "aud-010",
    at: isoDaysAgo(2),
    actor: "Aman Jha",
    actorRole: "Operations Lead",
    action: "Rotated admin permissions",
    resourceKind: "permissions",
    resourceId: "role-reviewer",
    resourceLabel: "Reviewer role",
    result: "success",
    source: "admin_portal",
    ipSummary: "203.0.113.xxx (Berlin, DE)",
    reason: "Removed unused permission",
  },
];

// ---------------------------------------------------------------------
// Alerts & incidents
// ---------------------------------------------------------------------

export type AlertSeverity = "info" | "warning" | "critical";
export type AlertStatus = "open" | "acknowledged" | "investigating" | "resolved";

export const ALERT_SEVERITY_LABEL: Record<AlertSeverity, string> = {
  info: "Info",
  warning: "Warning",
  critical: "Critical",
};
export const ALERT_STATUS_LABEL: Record<AlertStatus, string> = {
  open: "Open",
  acknowledged: "Acknowledged",
  investigating: "Investigating",
  resolved: "Resolved",
};

export type AlertKind =
  | "service_degradation"
  | "failed_job_spike"
  | "email_delivery_failure"
  | "sms_delivery_failure"
  | "document_processing_delay"
  | "authentication_anomaly"
  | "database_latency"
  | "storage_issue"
  | "security_alert"
  | "manual_incident";

export const ALERT_KIND_LABEL: Record<AlertKind, string> = {
  service_degradation: "Service degradation",
  failed_job_spike: "Failed job spike",
  email_delivery_failure: "Email delivery failure",
  sms_delivery_failure: "SMS delivery failure",
  document_processing_delay: "Document processing delay",
  authentication_anomaly: "Authentication anomaly",
  database_latency: "Database latency",
  storage_issue: "Storage issue",
  security_alert: "Security alert",
  manual_incident: "Manual incident",
};

export interface AlertRecord {
  id: string;
  title: string;
  kind: AlertKind;
  severity: AlertSeverity;
  status: AlertStatus;
  affectedService: PlatformServiceKey;
  owner?: string;
  createdAt: string;
  lastUpdate: string;
  impact: string;
  relatedJobIds?: string[];
  relatedFlagIds?: string[];
}

export const mockAlerts: AlertRecord[] = [
  {
    id: "alert-001",
    title: "Document storage PUT latency elevated",
    kind: "storage_issue",
    severity: "warning",
    status: "investigating",
    affectedService: "document_storage",
    owner: "Aman Jha",
    createdAt: isoMinutesAgo(90),
    lastUpdate: isoMinutesAgo(30),
    impact: "Uploads slower for eu-west-1 candidates. No data loss.",
  },
  {
    id: "alert-002",
    title: "Email bounces above 3% on 2 domains",
    kind: "email_delivery_failure",
    severity: "warning",
    status: "open",
    affectedService: "email",
    createdAt: isoMinutesAgo(60),
    lastUpdate: isoMinutesAgo(20),
    impact: "Outreach delivery to affected employers unreliable.",
    relatedJobIds: ["job-1002"],
  },
  {
    id: "alert-003",
    title: "OCR backlog above threshold",
    kind: "document_processing_delay",
    severity: "warning",
    status: "acknowledged",
    affectedService: "verification_engine",
    owner: "Daniel Kim",
    createdAt: isoMinutesAgo(75),
    lastUpdate: isoMinutesAgo(15),
    impact: "Some cases delayed by up to 8 minutes.",
    relatedJobIds: ["job-1001", "job-1003"],
  },
  {
    id: "alert-004",
    title: "Failed job spike on OCR extraction",
    kind: "failed_job_spike",
    severity: "critical",
    status: "open",
    affectedService: "background_jobs",
    createdAt: isoMinutesAgo(35),
    lastUpdate: isoMinutesAgo(10),
    impact: "3 consecutive failures of JOB-1001.",
    relatedJobIds: ["job-1001"],
  },
  {
    id: "alert-005",
    title: "Auth: increased 2FA prompts (India)",
    kind: "authentication_anomaly",
    severity: "info",
    status: "resolved",
    affectedService: "auth",
    owner: "Trust & Safety",
    createdAt: isoDaysAgo(1),
    lastUpdate: isoMinutesAgo(300),
    impact: "Elevated risk score for region; auto-resolved by heuristic.",
  },
];

// ---------------------------------------------------------------------
// Deployments
// ---------------------------------------------------------------------

export interface Deployment {
  id: string;
  version: string;
  environment: FlagEnvironment;
  deployedAt: string;
  deployedBy: string;
  summary: string;
}

export const mockDeployments: Deployment[] = [
  {
    id: "dep-001",
    version: "2026.07.19-a3f21",
    environment: "production",
    deployedAt: isoMinutesAgo(240),
    deployedBy: "release-bot",
    summary: "Admin: system operations center.",
  },
  {
    id: "dep-002",
    version: "2026.07.18-c1002",
    environment: "production",
    deployedAt: isoDaysAgo(1),
    deployedBy: "release-bot",
    summary: "Trust & Safety investigation workspace.",
  },
  {
    id: "dep-003",
    version: "2026.07.17-b8801",
    environment: "staging",
    deployedAt: isoDaysAgo(2),
    deployedBy: "release-bot",
    summary: "Trust Score v2 hardening.",
  },
];

// ---------------------------------------------------------------------
// Configuration reference (safe, non-secret)
// ---------------------------------------------------------------------

export interface ConfigEntry {
  key: string;
  label: string;
  value: string;
  group: "environment" | "providers" | "release" | "region";
  hint?: string;
}

export const mockConfigReference: ConfigEntry[] = [
  { key: "env_name", label: "Environment name", value: "production", group: "environment" },
  { key: "feature_env", label: "Feature environment", value: "prod-eu", group: "environment" },
  {
    key: "api_base_label",
    label: "API base label",
    value: "api.kairo.example (public)",
    group: "environment",
    hint: "Base URL label only. Real host not exposed here.",
  },
  { key: "region", label: "Region", value: "eu-west-1", group: "region" },
  {
    key: "secondary_region",
    label: "Secondary region",
    value: "ap-south-1 (read replica)",
    group: "region",
  },
  {
    key: "storage_provider",
    label: "Document storage provider",
    value: "S3-compatible (managed)",
    group: "providers",
  },
  { key: "email_provider", label: "Email provider", value: "Postmark", group: "providers" },
  {
    key: "sms_provider",
    label: "SMS provider",
    value: "Twilio + MSG91 (regional)",
    group: "providers",
  },
  { key: "app_version", label: "Application version", value: "2026.07.19-a3f21", group: "release" },
  { key: "build_id", label: "Build identifier", value: "build-4102", group: "release" },
  { key: "deployed_at", label: "Deployment date", value: isoMinutesAgo(240), group: "release" },
];

// ---------------------------------------------------------------------
// Overview metrics
// ---------------------------------------------------------------------

export interface SystemOverviewMetrics {
  api: ServiceHealthState;
  database: ServiceHealthState;
  redis: ServiceHealthState;
  documentStorage: ServiceHealthState;
  emailDelivery: ServiceHealthState;
  smsDelivery: ServiceHealthState;
  backgroundJobs: ServiceHealthState;
  failedJobs: number;
  pendingJobs: number;
  recentDeployments: number;
  openAlerts: number;
  auditEvents24h: number;
}

export function getSystemOverviewMetrics(): SystemOverviewMetrics {
  const svc = (key: PlatformServiceKey): ServiceHealthState =>
    mockPlatformServices.find((s) => s.id === key)?.state ?? "unknown";
  const now = Date.now();
  return {
    api: svc("api"),
    database: svc("postgres"),
    redis: svc("redis"),
    documentStorage: svc("document_storage"),
    emailDelivery: svc("email"),
    smsDelivery: svc("sms"),
    backgroundJobs: svc("background_jobs"),
    failedJobs: mockBackgroundJobs.filter((j) => j.status === "failed").length,
    pendingJobs: mockBackgroundJobs.filter(
      (j) => j.status === "queued" || j.status === "running" || j.status === "retrying",
    ).length,
    recentDeployments: mockDeployments.filter(
      (d) => now - new Date(d.deployedAt).getTime() < 7 * 86_400_000,
    ).length,
    openAlerts: mockAlerts.filter((a) => a.status !== "resolved").length,
    auditEvents24h: mockAuditEvents.filter((a) => now - new Date(a.at).getTime() < 86_400_000)
      .length,
  };
}

// ---------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------

function isoMinutesAgo(min: number): string {
  const base = new Date();
  base.setSeconds(0, 0);
  return new Date(base.getTime() - min * 60_000).toISOString();
}
function isoDaysAgo(d: number): string {
  return isoMinutesAgo(d * 60 * 24);
}
