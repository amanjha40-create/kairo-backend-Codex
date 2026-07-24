import { cn } from "@/lib/utils";
import type { VerificationStatus } from "../data/types";

const STATUS_LABELS: Record<VerificationStatus, string> = {
  pending_review: "Pending review",
  corrections_requested: "Corrections requested",
  resubmitted: "Resubmitted",
  awaiting_organization: "Awaiting organization",
  awaiting_employer: "Awaiting employer",
  clarification_requested: "Clarification requested",
  verified: "Verified",
  rejected: "Rejected",
  failed_outreach: "Failed outreach",
  unable_to_verify: "Unable to verify",
};

/**
 * Restrained status colors — meaning first, decoration never.
 * Values use tailwind arbitrary tokens keyed by semantic role.
 */
const STATUS_CLASSES: Record<VerificationStatus, string> = {
  pending_review:
    "bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-900/60",
  corrections_requested:
    "bg-orange-50 text-orange-900 ring-orange-200 dark:bg-orange-950/40 dark:text-orange-200 dark:ring-orange-900/60",
  resubmitted:
    "bg-sky-50 text-sky-900 ring-sky-200 dark:bg-sky-950/40 dark:text-sky-200 dark:ring-sky-900/60",
  awaiting_organization:
    "bg-violet-50 text-violet-900 ring-violet-200 dark:bg-violet-950/40 dark:text-violet-200 dark:ring-violet-900/60",
  awaiting_employer:
    "bg-indigo-50 text-indigo-900 ring-indigo-200 dark:bg-indigo-950/40 dark:text-indigo-200 dark:ring-indigo-900/60",
  clarification_requested:
    "bg-yellow-50 text-yellow-900 ring-yellow-200 dark:bg-yellow-950/40 dark:text-yellow-200 dark:ring-yellow-900/60",
  verified:
    "bg-emerald-50 text-emerald-900 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-200 dark:ring-emerald-900/60",
  rejected:
    "bg-rose-50 text-rose-900 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:ring-rose-900/60",
  failed_outreach:
    "bg-rose-50 text-rose-900 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:ring-rose-900/60",
  unable_to_verify:
    "bg-zinc-100 text-zinc-800 ring-zinc-200 dark:bg-zinc-800/60 dark:text-zinc-200 dark:ring-zinc-700",
};

export function StatusBadge({
  status,
  className,
}: {
  status: VerificationStatus;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        STATUS_CLASSES[status],
        className,
      )}
    >
      <span aria-hidden className="size-1.5 rounded-full bg-current opacity-70" />
      {STATUS_LABELS[status]}
    </span>
  );
}
