import { Link } from "@tanstack/react-router";
import { StatusBadge } from "./status-badge";
import { formatAge, formatNumber } from "../lib/format";
import type { VerificationStatus, VerificationStatusSummary } from "../data/types";

/** Maps a semantic verification status to the queue's `?view=` filter. */
type QueueView =
  | "all-active"
  | "pending-review"
  | "corrections"
  | "resubmitted"
  | "awaiting-organization"
  | "awaiting-employer"
  | "clarification"
  | "failed-outreach"
  | "completed";

const STATUS_TO_VIEW: Record<VerificationStatus, QueueView> = {
  pending_review: "pending-review",
  corrections_requested: "corrections",
  resubmitted: "resubmitted",
  awaiting_organization: "awaiting-organization",
  awaiting_employer: "awaiting-employer",
  clarification_requested: "clarification",
  failed_outreach: "failed-outreach",
  verified: "completed",
  rejected: "completed",
  unable_to_verify: "completed",
};

export function VerificationStatusGrid({ items }: { items: VerificationStatusSummary[] }) {
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
      {items.map((s) => {
        const delta = s.periodDelta;
        const deltaLabel =
          delta === 0 ? "no change" : delta > 0 ? `+${delta} in period` : `${delta} in period`;
        const deltaTone =
          delta > 0
            ? "text-amber-700 dark:text-amber-400"
            : delta < 0
              ? "text-emerald-700 dark:text-emerald-400"
              : "text-muted-foreground";
        return (
          <Link
            key={s.status}
            to="/admin/verifications"
            search={{ view: STATUS_TO_VIEW[s.status] }}
            className="group flex flex-col gap-2 rounded-lg border border-border bg-card p-3 transition-colors hover:border-foreground/20 hover:bg-accent/40"
            aria-label={`Open ${s.label} queue`}
          >
            <div className="flex items-center justify-between">
              <StatusBadge status={s.status} />
              <span className="text-lg font-semibold tabular-nums text-foreground">
                {formatNumber(s.count)}
              </span>
            </div>
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">
                {s.oldestAgeHours != null ? (
                  <>
                    Oldest:{" "}
                    <span className="tabular-nums text-foreground">
                      {formatAge(s.oldestAgeHours)}
                    </span>
                  </>
                ) : (
                  <span className="opacity-60">—</span>
                )}
              </span>
              <span className={deltaTone}>{deltaLabel}</span>
            </div>
          </Link>
        );
      })}
    </div>
  );
}
