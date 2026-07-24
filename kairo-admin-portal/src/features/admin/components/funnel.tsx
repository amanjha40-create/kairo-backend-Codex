import { cn } from "@/lib/utils";
import { formatNumber } from "../lib/format";
import type { FunnelStage } from "../data/types";

export function Funnel({ stages }: { stages: FunnelStage[] }) {
  if (stages.length === 0) return null;
  const total = stages[0].count;
  // Identify the largest drop-off between consecutive stages.
  let biggestDropIndex = 1;
  let biggestDrop = 0;
  for (let i = 1; i < stages.length; i++) {
    const drop = stages[i - 1].count - stages[i].count;
    if (drop > biggestDrop) {
      biggestDrop = drop;
      biggestDropIndex = i;
    }
  }

  return (
    <ol className="space-y-1.5">
      {stages.map((stage, i) => {
        const overall = total > 0 ? (stage.count / total) * 100 : 0;
        const fromPrev =
          i === 0 ? 100 : stages[i - 1].count > 0 ? (stage.count / stages[i - 1].count) * 100 : 0;
        const isBiggestDrop = i === biggestDropIndex;
        return (
          <li key={stage.id} className="group">
            <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
              <span className="font-medium text-foreground">{stage.label}</span>
              <span className="tabular-nums">
                {formatNumber(stage.count)}
                <span className="mx-2 text-border">·</span>
                {i === 0 ? "100.0%" : `${fromPrev.toFixed(1)}% from prev`}
                <span className="mx-2 text-border">·</span>
                {overall.toFixed(1)}% overall
                {isBiggestDrop && i > 0 ? (
                  <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-900 dark:bg-amber-950/50 dark:text-amber-200">
                    largest drop
                  </span>
                ) : null}
              </span>
            </div>
            <div className="mt-1 h-2 w-full overflow-hidden rounded-sm bg-muted">
              <div
                className={cn(
                  "h-full rounded-sm transition-all",
                  isBiggestDrop && i > 0 ? "bg-amber-500/80" : "bg-foreground/80",
                )}
                style={{ width: `${overall}%` }}
                aria-hidden
              />
            </div>
          </li>
        );
      })}
    </ol>
  );
}
