import { useState } from "react";
import { cn } from "@/lib/utils";

const RANGES = [
  { id: "today", label: "Today" },
  { id: "7d", label: "7 days" },
  { id: "30d", label: "30 days" },
  { id: "custom", label: "Custom" },
] as const;

/** UI-only date-range selector. State stays local until real filters land. */
export function DateRangeSelector() {
  const [value, setValue] = useState<(typeof RANGES)[number]["id"]>("7d");
  return (
    <div
      role="radiogroup"
      aria-label="Date range"
      className="inline-flex items-center rounded-md border border-border bg-card p-0.5"
    >
      {RANGES.map((r) => {
        const active = value === r.id;
        return (
          <button
            key={r.id}
            role="radio"
            aria-checked={active}
            onClick={() => setValue(r.id)}
            className={cn(
              "rounded px-2.5 py-1 text-xs font-medium transition-colors",
              active
                ? "bg-foreground text-background"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {r.label}
          </button>
        );
      })}
    </div>
  );
}
