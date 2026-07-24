import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatNumber, formatSignedPct } from "../lib/format";
import type { AdminMetric } from "../data/types";

export function MetricCard({ metric }: { metric: AdminMetric }) {
  const dir = metric.changePct > 0 ? "up" : metric.changePct < 0 ? "down" : "flat";
  const Icon = dir === "up" ? ArrowUpRight : dir === "down" ? ArrowDownRight : Minus;
  const tone =
    dir === "up"
      ? "text-emerald-700 dark:text-emerald-400"
      : dir === "down"
        ? "text-rose-700 dark:text-rose-400"
        : "text-muted-foreground";

  return (
    <div className="rounded-lg border border-border bg-card p-4 transition-colors hover:border-border/80">
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {metric.label}
        </p>
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="text-2xl font-semibold tabular-nums text-foreground">
          {formatNumber(metric.value, metric.format)}
        </span>
        <span
          className={cn("inline-flex items-center gap-0.5 text-xs font-medium tabular-nums", tone)}
        >
          <Icon aria-hidden className="size-3.5" />
          {formatSignedPct(metric.changePct)}
        </span>
      </div>
      {metric.context ? (
        <p className="mt-1 text-xs text-muted-foreground">{metric.context}</p>
      ) : null}
    </div>
  );
}
