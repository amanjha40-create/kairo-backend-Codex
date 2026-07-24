/**
 * Admin Portal — Mock Data Types
 *
 * These typed interfaces model the shapes the Admin Portal expects from
 * the real backend once the operations APIs are available. Every UI
 * surface reads from the mock-data layer in `./index.ts`.
 *
 * BACKEND INTEGRATION NOTE
 * ------------------------
 * When the real admin APIs are ready, replace the mock exports in
 * `./index.ts` with TanStack Query hooks (e.g. `useAdminMetrics()`) that
 * call the backend. Do NOT silently fall back to mock data at that point:
 * an unconfigured admin API should render the error / empty states, not
 * masquerade as real operational data.
 */

export type VerificationStatus =
  | "pending_review"
  | "corrections_requested"
  | "resubmitted"
  | "awaiting_organization"
  | "awaiting_employer"
  | "clarification_requested"
  | "verified"
  | "rejected"
  | "failed_outreach"
  | "unable_to_verify";

export type Priority = "low" | "normal" | "high" | "urgent";

export type PlatformServiceState = "operational" | "degraded" | "action_required";

export interface AdminMetric {
  id: string;
  label: string;
  value: number;
  /** Change vs previous period, as a signed percentage (e.g. +12.4, -3.1). */
  changePct: number;
  /** Short supporting context, e.g. "vs previous 7 days". */
  context?: string;
  /** Optional format hint. Defaults to plain integer formatting. */
  format?: "integer" | "compact";
}

export interface AttentionItem {
  id: string;
  category: string;
  count: number;
  reason: string;
  priority: Priority;
  /** Route to a future filtered Admin Portal destination. May include ?query. */
  destinationHref: string;
  destinationLabel: string;
}

/** Split a destinationHref like `/admin/verifications?view=pending-review`
 * into a path and a plain search object. Values are always strings. */
export function parseDestination(href: string): { path: string; search: Record<string, string> } {
  const [path, query = ""] = href.split("?");
  const search: Record<string, string> = {};
  if (query) {
    for (const part of query.split("&")) {
      const [k, v = ""] = part.split("=");
      if (k) search[decodeURIComponent(k)] = decodeURIComponent(v);
    }
  }
  return { path, search };
}

export interface FunnelStage {
  id: string;
  label: string;
  count: number;
}

export interface VerificationStatusSummary {
  status: VerificationStatus;
  label: string;
  count: number;
  /** Age of the oldest open item in hours, where relevant. */
  oldestAgeHours?: number;
  /** Change during the selected period (signed integer). */
  periodDelta: number;
}

export type AdminActivityKind =
  | "user_registered"
  | "verification_submitted"
  | "correction_requested"
  | "resubmitted"
  | "organization_resolved"
  | "employer_outreach_sent"
  | "employer_responded"
  | "verification_approved"
  | "email_delivery_failed"
  | "trust_passport_updated";

export interface AdminActivity {
  id: string;
  kind: AdminActivityKind;
  actor: string;
  actorRole: "admin" | "candidate" | "employer" | "system";
  action: string;
  subject?: string;
  /** ISO timestamp. */
  timestamp: string;
  /** Placeholder to the future detail record. */
  detailHref: string;
}

export interface PlatformServiceStatus {
  id: string;
  name: string;
  state: PlatformServiceState;
  note?: string;
}
