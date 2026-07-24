import { ArrowRight } from "lucide-react";
import { Link } from "@tanstack/react-router";
import { PriorityBadge } from "./priority-badge";
import { parseDestination, type AttentionItem } from "../data/types";

export function AttentionCard({ item }: { item: AttentionItem }) {
  const { path, search } = parseDestination(item.destinationHref);
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <p className="truncate text-sm font-semibold text-foreground">{item.category}</p>
            <PriorityBadge priority={item.priority} />
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{item.reason}</p>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-2xl font-semibold tabular-nums text-foreground">{item.count}</div>
        </div>
      </div>
      <div className="flex justify-end">
        <Link
          to={path}
          search={search}
          className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:bg-accent"
        >
          {item.destinationLabel}
          <ArrowRight aria-hidden className="size-3.5" />
        </Link>
      </div>
    </div>
  );
}
