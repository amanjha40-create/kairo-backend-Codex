import { Link } from "@tanstack/react-router";
import { ArrowUpRight, X } from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { StatusBadge } from "./status-badge";
import { PriorityBadge } from "./priority-badge";
import { formatAge, formatRelativeTime } from "../lib/format";
import {
  ATTENTION_FLAG_LABEL,
  ORGANIZATION_STATUS_LABEL,
  SLA_LABEL,
  VERIFICATION_TYPE_LABEL,
  type VerificationCase,
} from "../data/verifications";

function slaHours(iso: string) {
  return Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 3_600_000));
}

interface Props {
  caseRecord: VerificationCase | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CasePreviewDrawer({ caseRecord, open, onOpenChange }: Props) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="flex w-full flex-col gap-0 overflow-y-auto p-0 sm:max-w-lg"
      >
        {caseRecord ? (
          <>
            <SheetHeader className="border-b border-border px-5 py-4 text-left">
              <div className="flex items-center gap-2">
                <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] font-medium text-muted-foreground">
                  {caseRecord.reference}
                </span>
                <StatusBadge status={caseRecord.status} />
                <PriorityBadge priority={caseRecord.priority} />
              </div>
              <SheetTitle className="mt-2 text-base font-semibold">
                {caseRecord.candidateName}
              </SheetTitle>
              <SheetDescription className="text-xs text-muted-foreground">
                {VERIFICATION_TYPE_LABEL[caseRecord.verificationType]} · {caseRecord.roleOrProgram}
              </SheetDescription>
            </SheetHeader>

            <div className="flex-1 space-y-5 px-5 py-4 text-sm">
              <Field label="Candidate">
                <div>{caseRecord.candidateName}</div>
                <div className="text-xs text-muted-foreground">{caseRecord.candidateEmail}</div>
              </Field>
              <Field label="Organization">
                <div>{caseRecord.organizationName}</div>
                <div className="text-xs text-muted-foreground">
                  {ORGANIZATION_STATUS_LABEL[caseRecord.organizationStatus]}
                </div>
              </Field>
              <div className="grid grid-cols-2 gap-4">
                <Field label="Verification type">
                  {VERIFICATION_TYPE_LABEL[caseRecord.verificationType]}
                </Field>
                <Field label="Priority">
                  <PriorityBadge priority={caseRecord.priority} />
                </Field>
                <Field label="Assigned reviewer">{caseRecord.assignedReviewer}</Field>
                <Field label="Evidence">
                  <span className="tabular-nums">{caseRecord.evidenceCount} items</span>
                </Field>
                <Field label="Submitted">
                  <div className="tabular-nums">
                    {new Date(caseRecord.submittedAt).toLocaleDateString()}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {formatRelativeTime(caseRecord.submittedAt)}
                  </div>
                </Field>
                <Field label="Age & SLA">
                  <div className="tabular-nums">{formatAge(slaHours(caseRecord.submittedAt))}</div>
                  <div className="text-xs text-muted-foreground">
                    {SLA_LABEL[caseRecord.slaState]}
                  </div>
                </Field>
              </div>

              <Field label="Attention flags">
                {caseRecord.attentionFlags.length === 0 ? (
                  <span className="text-xs text-muted-foreground">None</span>
                ) : (
                  <ul className="flex flex-wrap gap-1.5">
                    {caseRecord.attentionFlags.map((f) => (
                      <li
                        key={f}
                        className="rounded-md bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-900 ring-1 ring-inset ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-900/60"
                      >
                        {ATTENTION_FLAG_LABEL[f]}
                      </li>
                    ))}
                  </ul>
                )}
              </Field>

              <Field label="Last activity">
                <div>{caseRecord.lastActivitySummary}</div>
                <div className="text-xs text-muted-foreground">
                  Updated {formatRelativeTime(caseRecord.updatedAt)}
                </div>
              </Field>

              <div className="rounded-md border border-dashed border-border bg-muted/40 p-2.5 text-[11px] leading-relaxed text-muted-foreground">
                Approval, rejection and correction actions are not available in the preview. Open
                the full case to review decisions.
              </div>
            </div>

            <div className="flex items-center justify-between gap-2 border-t border-border bg-background px-5 py-3">
              <button
                onClick={() => onOpenChange(false)}
                className="inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                <X aria-hidden className="size-3.5" /> Close
              </button>
              <Link
                to="/admin/verifications/$caseId"
                params={{ caseId: caseRecord.id }}
                search={{ view: "all-active" }}
                className="inline-flex items-center gap-1 rounded-md bg-foreground px-3 py-1.5 text-xs font-semibold text-background hover:bg-foreground/90"
              >
                Open full case
                <ArrowUpRight aria-hidden className="size-3.5" />
              </Link>
            </div>
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="text-sm text-foreground">{children}</div>
    </div>
  );
}
