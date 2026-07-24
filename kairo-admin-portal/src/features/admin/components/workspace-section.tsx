import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Section shell used across the case workspace. */
export function WorkspaceSection({
  id,
  title,
  description,
  action,
  children,
  className,
}: {
  id?: string;
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      id={id}
      aria-labelledby={id ? `${id}-heading` : undefined}
      className={cn("rounded-lg border border-border bg-card", className)}
    >
      <header className="flex flex-wrap items-start justify-between gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <h2
            id={id ? `${id}-heading` : undefined}
            className="text-sm font-semibold tracking-tight text-foreground"
          >
            {title}
          </h2>
          {description ? (
            <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
          ) : null}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </header>
      <div className="px-4 py-3">{children}</div>
    </section>
  );
}

const SOURCE_CLASSES = {
  candidate:
    "bg-sky-50 text-sky-900 ring-sky-200 dark:bg-sky-950/40 dark:text-sky-200 dark:ring-sky-900/60",
  kairo_derived:
    "bg-violet-50 text-violet-900 ring-violet-200 dark:bg-violet-950/40 dark:text-violet-200 dark:ring-violet-900/60",
  verifier_confirmed:
    "bg-emerald-50 text-emerald-900 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-200 dark:ring-emerald-900/60",
} as const;

const SOURCE_LABELS = {
  candidate: "Provided by candidate",
  kairo_derived: "Matched by Kairo",
  verifier_confirmed: "Confirmed by verifier",
} as const;

export function SourceBadge({
  source,
  className,
}: {
  source: keyof typeof SOURCE_CLASSES;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset",
        SOURCE_CLASSES[source],
        className,
      )}
      aria-label={SOURCE_LABELS[source]}
    >
      {SOURCE_LABELS[source]}
    </span>
  );
}
