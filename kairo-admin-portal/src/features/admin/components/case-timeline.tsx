import { cn } from "@/lib/utils";
import {
  FileText,
  Upload,
  Cpu,
  UserPlus,
  ArrowUp,
  Building2,
  MailCheck,
  Send,
  Wrench,
  RotateCcw,
  StickyNote,
  Flag,
  ShieldCheck,
  Reply,
  Plus,
} from "lucide-react";
import type { CaseTimelineEvent, TimelineEventKind } from "../data/cases";
import { formatRelativeTime } from "../lib/format";

const KIND_META: Record<TimelineEventKind, { icon: typeof Plus; label: string }> = {
  case_created: { icon: Plus, label: "Case created" },
  candidate_submitted: { icon: Upload, label: "Candidate submitted" },
  evidence_uploaded: { icon: FileText, label: "Evidence uploaded" },
  processing_result: { icon: Cpu, label: "Processing result" },
  assignment_changed: { icon: UserPlus, label: "Assignment changed" },
  priority_changed: { icon: ArrowUp, label: "Priority changed" },
  organization_match: { icon: Building2, label: "Organization match" },
  contact_approved: { icon: MailCheck, label: "Contact approved" },
  outreach_event: { icon: Send, label: "Outreach event" },
  correction_requested: { icon: Wrench, label: "Correction requested" },
  candidate_resubmitted: { icon: RotateCcw, label: "Candidate resubmitted" },
  internal_note_added: { icon: StickyNote, label: "Internal note" },
  attention_flag_created: { icon: Flag, label: "Attention flag" },
  attention_flag_acknowledged: { icon: ShieldCheck, label: "Flag acknowledged" },
  employer_response: { icon: Reply, label: "Employer response" },
  decision_prepared: { icon: ShieldCheck, label: "Decision prepared" },
};

export function CaseTimeline({ events }: { events: CaseTimelineEvent[] }) {
  if (events.length === 0) {
    return <p className="text-xs text-muted-foreground">No events recorded yet.</p>;
  }
  const sorted = [...events].sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime());
  return (
    <>
      <p className="mb-3 text-[11px] italic text-muted-foreground">
        Case timeline is append-only in this build. Historical events are never edited or removed.
      </p>
      <ol className="relative space-y-3 border-l border-border pl-5" aria-label="Case timeline">
        {sorted.map((ev) => {
          const meta = KIND_META[ev.kind];
          const Icon = meta.icon;
          return (
            <li key={ev.id} className="relative">
              <span
                aria-hidden
                className={cn(
                  "absolute -left-[27px] top-0.5 flex size-5 items-center justify-center rounded-full border",
                  ev.sessionOnly
                    ? "border-sky-300 bg-sky-50 text-sky-700 dark:border-sky-700 dark:bg-sky-950 dark:text-sky-300"
                    : "border-border bg-background text-muted-foreground",
                )}
              >
                <Icon className="size-3" />
              </span>
              <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-0.5">
                <p className="text-xs font-medium text-foreground">{meta.label}</p>
                <p className="text-[11px] tabular-nums text-muted-foreground">
                  {formatRelativeTime(ev.at)}
                </p>
              </div>
              <p className="mt-0.5 text-xs text-muted-foreground">{ev.description}</p>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                <span className="capitalize">{ev.actorSource}</span> · {ev.actor}
                {ev.sessionOnly ? (
                  <span className="ml-1 rounded bg-sky-50 px-1 py-0.5 text-[10px] text-sky-700 ring-1 ring-inset ring-sky-200 dark:bg-sky-950/40 dark:text-sky-300 dark:ring-sky-900/60">
                    session-only
                  </span>
                ) : null}
              </p>
            </li>
          );
        })}
      </ol>
    </>
  );
}
