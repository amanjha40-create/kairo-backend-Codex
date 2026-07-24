import { cn } from "@/lib/utils";
import type { PlatformServiceState, PlatformServiceStatus } from "../data/types";

const STATE_LABEL: Record<PlatformServiceState, string> = {
  operational: "Operational",
  degraded: "Degraded",
  action_required: "Action required",
};

const DOT: Record<PlatformServiceState, string> = {
  operational: "bg-emerald-500",
  degraded: "bg-amber-500",
  action_required: "bg-rose-500",
};

export function PlatformSummary({ services }: { services: PlatformServiceStatus[] }) {
  return (
    <ul className="divide-y divide-border rounded-lg border border-border bg-card">
      {services.map((s) => (
        <li key={s.id} className="flex items-center justify-between gap-3 px-3 py-2.5">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span aria-hidden className={cn("size-2 rounded-full", DOT[s.state])} />
              <span className="text-sm font-medium text-foreground">{s.name}</span>
            </div>
            {s.note ? <p className="mt-0.5 pl-4 text-xs text-muted-foreground">{s.note}</p> : null}
          </div>
          <span className="text-xs font-medium text-muted-foreground">{STATE_LABEL[s.state]}</span>
        </li>
      ))}
    </ul>
  );
}
