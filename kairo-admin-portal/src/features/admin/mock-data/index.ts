/**
 * Admin Portal — Mock Data Layer
 *
 * ISOLATED from the candidate-facing application. Do not import candidate
 * mock data here, and do not import from this file outside `src/features/admin`.
 *
 * Replace each exported constant with a TanStack Query hook backed by the
 * real admin API when it becomes available. Keep the shapes in `./types.ts`
 * as the source of truth.
 */

import type {
  AdminActivity,
  AdminMetric,
  AttentionItem,
  FunnelStage,
  PlatformServiceStatus,
  VerificationStatusSummary,
} from "./types";

export const mockAdminMetrics: AdminMetric[] = [
  {
    id: "total_users",
    label: "Total registered users",
    value: 12483,
    changePct: 4.2,
    context: "vs previous 7 days",
  },
  {
    id: "new_users",
    label: "New users",
    value: 318,
    changePct: 12.4,
    context: "in selected period",
  },
  {
    id: "completed_onboarding",
    label: "Completed onboarding",
    value: 241,
    changePct: 6.1,
    context: "in selected period",
  },
  {
    id: "trust_passports",
    label: "Trust Passports created",
    value: 1892,
    changePct: 3.7,
    context: "cumulative",
  },
  {
    id: "pending_review",
    label: "Pending admin review",
    value: 47,
    changePct: -8.3,
    context: "open queue",
  },
  {
    id: "verified_today",
    label: "Verified today",
    value: 63,
    changePct: 9.5,
    context: "vs yesterday",
  },
];

export const mockAttentionItems: AttentionItem[] = [
  {
    id: "sla_breach",
    category: "Verification SLA breach",
    count: 8,
    reason: "Requests have been waiting for review for more than 24 hours.",
    priority: "urgent",
    destinationHref: "/admin/verifications?view=pending-review",
    destinationLabel: "View requests",
  },
  {
    id: "failed_outreach",
    category: "Failed employer outreach",
    count: 5,
    reason: "Outreach emails bounced or were rejected by employer domains.",
    priority: "high",
    destinationHref: "/admin/verifications?view=failed-outreach",
    destinationLabel: "Review outreach",
  },
  {
    id: "resubmitted",
    category: "Resubmitted corrections",
    count: 12,
    reason: "Candidates have responded to correction requests and are awaiting re-review.",
    priority: "high",
    destinationHref: "/admin/verifications?view=resubmitted",
    destinationLabel: "Re-review",
  },
  {
    id: "org_matches",
    category: "Unresolved organization matches",
    count: 9,
    reason: "Employer names could not be matched to a canonical organization record.",
    priority: "normal",
    destinationHref: "/admin/verifications?view=awaiting-organization",
    destinationLabel: "Resolve matches",
  },
  {
    id: "risk",
    category: "High-risk activity",
    count: 2,
    reason: "Accounts flagged by risk heuristics require manual review.",
    priority: "urgent",
    destinationHref: "/admin/users",
    destinationLabel: "Investigate",
  },
];

export const mockFunnel: FunnelStage[] = [
  { id: "registered", label: "Registered", count: 12483 },
  { id: "email_phone", label: "Verified email & phone", count: 10921 },
  { id: "profile", label: "Completed profile", count: 8734 },
  { id: "employment", label: "Added employment", count: 6512 },
  { id: "evidence", label: "Uploaded evidence", count: 4988 },
  { id: "submitted", label: "Submitted verification", count: 3921 },
  { id: "admin_approved", label: "Admin approved", count: 3204 },
  { id: "employer_responded", label: "Employer responded", count: 2418 },
  { id: "verified", label: "Employment verified", count: 1892 },
];

export const mockVerificationStatuses: VerificationStatusSummary[] = [
  {
    status: "pending_review",
    label: "Pending review",
    count: 47,
    oldestAgeHours: 38,
    periodDelta: -6,
  },
  {
    status: "corrections_requested",
    label: "Corrections requested",
    count: 23,
    oldestAgeHours: 96,
    periodDelta: 4,
  },
  { status: "resubmitted", label: "Resubmitted", count: 12, oldestAgeHours: 14, periodDelta: 3 },
  {
    status: "awaiting_organization",
    label: "Awaiting organization",
    count: 9,
    oldestAgeHours: 52,
    periodDelta: 1,
  },
  {
    status: "awaiting_employer",
    label: "Awaiting employer",
    count: 71,
    oldestAgeHours: 120,
    periodDelta: 8,
  },
  { status: "verified", label: "Verified", count: 1892, periodDelta: 63 },
  { status: "rejected", label: "Rejected", count: 84, periodDelta: 2 },
  {
    status: "failed_outreach",
    label: "Failed outreach",
    count: 5,
    oldestAgeHours: 40,
    periodDelta: 1,
  },
];

export const mockActivity: AdminActivity[] = [
  {
    id: "a1",
    kind: "verification_approved",
    actor: "Aman Jha",
    actorRole: "admin",
    action: "approved verification for",
    subject: "Jonas Weiss",
    timestamp: isoMinutesAgo(4),
    detailHref: "/admin/verifications",
  },
  {
    id: "a2",
    kind: "email_delivery_failed",
    actor: "System",
    actorRole: "system",
    action: "email delivery failed to",
    subject: "hr@northwind.example",
    timestamp: isoMinutesAgo(11),
    detailHref: "/admin/communications",
  },
  {
    id: "a3",
    kind: "resubmitted",
    actor: "Priya Shah",
    actorRole: "candidate",
    action: "resubmitted corrections",
    timestamp: isoMinutesAgo(23),
    detailHref: "/admin/verifications",
  },
  {
    id: "a4",
    kind: "employer_responded",
    actor: "Acme Corp",
    actorRole: "employer",
    action: "confirmed employment for",
    subject: "Marco Bianchi",
    timestamp: isoMinutesAgo(41),
    detailHref: "/admin/verifications",
  },
  {
    id: "a5",
    kind: "correction_requested",
    actor: "Daniel Kim",
    actorRole: "admin",
    action: "requested corrections from",
    subject: "Lena Fischer",
    timestamp: isoMinutesAgo(58),
    detailHref: "/admin/verifications",
  },
  {
    id: "a6",
    kind: "organization_resolved",
    actor: "Aman Jha",
    actorRole: "admin",
    action: "resolved organization",
    subject: "Globex Ltd",
    timestamp: isoMinutesAgo(72),
    detailHref: "/admin/registry",
  },
  {
    id: "a7",
    kind: "employer_outreach_sent",
    actor: "System",
    actorRole: "system",
    action: "sent outreach to",
    subject: "hr@umbrella.example",
    timestamp: isoMinutesAgo(96),
    detailHref: "/admin/communications",
  },
  {
    id: "a8",
    kind: "verification_submitted",
    actor: "Ravi Patel",
    actorRole: "candidate",
    action: "submitted verification request",
    timestamp: isoMinutesAgo(120),
    detailHref: "/admin/verifications",
  },
  {
    id: "a9",
    kind: "user_registered",
    actor: "Sofia Martins",
    actorRole: "candidate",
    action: "registered",
    timestamp: isoMinutesAgo(140),
    detailHref: "/admin/users",
  },
  {
    id: "a10",
    kind: "trust_passport_updated",
    actor: "System",
    actorRole: "system",
    action: "updated Trust Passport for",
    subject: "Jonas Weiss",
    timestamp: isoMinutesAgo(160),
    detailHref: "/admin/users",
  },
];

export const mockPlatformServices: PlatformServiceStatus[] = [
  { id: "auth", name: "Authentication service", state: "operational" },
  {
    id: "email",
    name: "Email delivery",
    state: "degraded",
    note: "Elevated bounce rate on 2 employer domains.",
  },
  { id: "verification", name: "Verification workflow", state: "operational" },
  { id: "background", name: "Background processing", state: "operational" },
  {
    id: "storage",
    name: "Document storage",
    state: "action_required",
    note: "Retention policy review overdue.",
  },
];

function isoMinutesAgo(min: number): string {
  // Deterministic base so mock activity stays stable within a session.
  const base = new Date();
  base.setSeconds(0, 0);
  return new Date(base.getTime() - min * 60_000).toISOString();
}
