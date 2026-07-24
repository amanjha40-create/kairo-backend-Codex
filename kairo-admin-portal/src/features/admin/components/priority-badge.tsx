import { cn } from "@/lib/utils";
import type { Priority } from "../data/types";

const LABELS: Record<Priority, string> = {
  low: "Low",
  normal: "Normal",
  high: "High",
  urgent: "Urgent",
};
const CLASSES: Record<Priority, string> = {
  low: "bg-muted text-muted-foreground ring-border",
  normal:
    "bg-sky-50 text-sky-900 ring-sky-200 dark:bg-sky-950/40 dark:text-sky-200 dark:ring-sky-900/60",
  high: "bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-900/60",
  urgent:
    "bg-rose-50 text-rose-900 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:ring-rose-900/60",
};

export function PriorityBadge({ priority, className }: { priority: Priority; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        CLASSES[priority],
        className,
      )}
      aria-label={`Priority: ${LABELS[priority]}`}
    >
      {LABELS[priority]}
    </span>
  );
}
