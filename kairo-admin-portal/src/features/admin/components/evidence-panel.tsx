import { useState } from "react";
import { FileText, AlertTriangle, CheckCircle2, Clock, XCircle, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { EmptyState } from "./states";
import {
  EVIDENCE_DOC_LABEL,
  formatFileSize,
  type EvidenceItem,
  type EvidenceProcessingState,
  type EvidenceReviewState,
  type ComparisonResult,
} from "../data/cases";
import { formatRelativeTime } from "../lib/format";

const PROCESSING_META: Record<
  EvidenceProcessingState,
  { label: string; className: string; icon: typeof CheckCircle2 }
> = {
  uploaded: { label: "Uploaded", className: "text-muted-foreground", icon: Clock },
  processing: { label: "Processing", className: "text-sky-700 dark:text-sky-300", icon: Loader2 },
  processed: {
    label: "Processed",
    className: "text-emerald-700 dark:text-emerald-300",
    icon: CheckCircle2,
  },
  failed: { label: "Failed", className: "text-rose-700 dark:text-rose-300", icon: XCircle },
};

const REVIEW_META: Record<EvidenceReviewState, { label: string; className: string }> = {
  not_reviewed: { label: "Not reviewed", className: "bg-muted text-muted-foreground" },
  reviewed: {
    label: "Reviewed",
    className: "bg-emerald-50 text-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200",
  },
  needs_attention: {
    label: "Needs attention",
    className: "bg-amber-50 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200",
  },
  unsupported: {
    label: "Unsupported",
    className: "bg-zinc-100 text-zinc-800 dark:bg-zinc-800/60 dark:text-zinc-200",
  },
  duplicate: {
    label: "Duplicate",
    className: "bg-orange-50 text-orange-900 dark:bg-orange-950/40 dark:text-orange-200",
  },
};

const COMPARISON_META: Record<ComparisonResult, { label: string; className: string }> = {
  match: {
    label: "Match",
    className: "bg-emerald-50 text-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200",
  },
  partial_match: {
    label: "Partial",
    className: "bg-amber-50 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200",
  },
  mismatch: {
    label: "Mismatch",
    className: "bg-rose-50 text-rose-900 dark:bg-rose-950/40 dark:text-rose-200",
  },
  not_found: {
    label: "Not found",
    className: "bg-zinc-100 text-zinc-800 dark:bg-zinc-800/60 dark:text-zinc-200",
  },
  not_applicable: {
    label: "N/A",
    className: "bg-muted text-muted-foreground",
  },
};

export function EvidencePanel({ items }: { items: EvidenceItem[] }) {
  const [openId, setOpenId] = useState<string | null>(null);
  const open = items.find((i) => i.id === openId) ?? null;

  if (items.length === 0) {
    return (
      <EmptyState
        title="No evidence uploaded"
        description="The candidate has not attached any supporting documents to this case yet."
      />
    );
  }

  return (
    <>
      <ul className="grid grid-cols-1 gap-2 md:grid-cols-2">
        {items.map((ev) => (
          <li key={ev.id}>
            <EvidenceCard item={ev} onOpen={() => setOpenId(ev.id)} />
          </li>
        ))}
      </ul>

      <Sheet open={!!open} onOpenChange={(v) => (!v ? setOpenId(null) : null)}>
        <SheetContent
          side="right"
          className="w-full overflow-y-auto sm:max-w-xl"
          aria-describedby={undefined}
        >
          {open ? <EvidencePreview item={open} /> : null}
        </SheetContent>
      </Sheet>
    </>
  );
}

function EvidenceCard({ item, onOpen }: { item: EvidenceItem; onOpen: () => void }) {
  const proc = PROCESSING_META[item.processingStatus];
  const rev = REVIEW_META[item.reviewStatus];
  const ProcIcon = proc.icon;
  return (
    <button
      type="button"
      onClick={onOpen}
      className="group flex w-full items-start gap-3 rounded-lg border border-border bg-background p-3 text-left transition-colors hover:bg-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
        <FileText aria-hidden className="size-4" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <p className="truncate text-sm font-medium text-foreground">{item.title}</p>
          <span
            className={cn("shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium", rev.className)}
          >
            {rev.label}
          </span>
        </div>
        <p className="mt-0.5 truncate text-xs text-muted-foreground">
          {EVIDENCE_DOC_LABEL[item.docType]} · {item.filename}
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
          <span className={cn("inline-flex items-center gap-1", proc.className)}>
            <ProcIcon
              aria-hidden
              className={cn("size-3", item.processingStatus === "processing" && "animate-spin")}
            />
            {proc.label}
          </span>
          <span>{formatFileSize(item.fileSizeBytes)}</span>
          {item.pageCount ? <span>{item.pageCount} pages</span> : null}
          <span>Uploaded {formatRelativeTime(item.uploadedAt)}</span>
        </div>
        {item.attentionFlags.length > 0 ? (
          <div className="mt-2 inline-flex items-center gap-1 rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-900 ring-1 ring-inset ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-900/60">
            <AlertTriangle aria-hidden className="size-3" />
            Requires attention
          </div>
        ) : null}
      </div>
    </button>
  );
}

function EvidencePreview({ item }: { item: EvidenceItem }) {
  return (
    <>
      <SheetHeader>
        <SheetTitle className="text-base">{item.title}</SheetTitle>
        <SheetDescription>
          {EVIDENCE_DOC_LABEL[item.docType]} · {item.filename}
        </SheetDescription>
      </SheetHeader>

      <div className="mt-4 flex flex-col gap-4">
        {/* Mocked document canvas */}
        <div
          role="img"
          aria-label="Mocked document preview"
          className="relative flex aspect-[4/5] items-center justify-center overflow-hidden rounded-md border border-dashed border-border bg-muted/40"
        >
          <div className="text-center">
            <FileText aria-hidden className="mx-auto size-8 text-muted-foreground" />
            <p className="mt-2 text-xs font-medium text-foreground">Mock preview</p>
            <p className="mt-1 max-w-[220px] text-[11px] text-muted-foreground">
              Real document rendering is not enabled in this build.
            </p>
          </div>
          <span className="absolute left-2 top-2 rounded bg-background/80 px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground ring-1 ring-inset ring-border">
            MOCK
          </span>
        </div>

        <dl className="grid grid-cols-2 gap-2 text-xs">
          <MetaRow label="File size" value={formatFileSize(item.fileSizeBytes)} />
          <MetaRow label="Pages" value={item.pageCount ? String(item.pageCount) : "—"} />
          <MetaRow label="Uploaded" value={formatRelativeTime(item.uploadedAt)} />
          <MetaRow label="Source" value={item.source.replace(/_/g, " ")} />
          <MetaRow label="Processing" value={PROCESSING_META[item.processingStatus].label} />
          <MetaRow label="Review" value={REVIEW_META[item.reviewStatus].label} />
        </dl>

        {item.extraction ? (
          <div className="rounded-md border border-border bg-background p-3">
            <p className="text-xs font-semibold text-foreground">Extracted fields</p>
            {item.extraction.extractedFields.length ? (
              <ul className="mt-2 space-y-1.5">
                {item.extraction.extractedFields.map((f) => (
                  <li key={f.label} className="flex items-center justify-between gap-2 text-xs">
                    <span className="text-muted-foreground">{f.label}</span>
                    <span className="flex items-center gap-2 text-foreground">
                      <span className="truncate">{f.value}</span>
                      <span className="rounded bg-muted px-1 py-0.5 text-[10px] tabular-nums text-muted-foreground">
                        {(f.confidence * 100).toFixed(0)}%
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-xs text-muted-foreground">No fields extracted.</p>
            )}
            {item.extraction.detectedDates?.length ? (
              <p className="mt-3 text-xs">
                <span className="text-muted-foreground">Detected dates:</span>{" "}
                <span className="text-foreground">{item.extraction.detectedDates.join(", ")}</span>
              </p>
            ) : null}
            {item.extraction.mismatchWarnings?.length ? (
              <div className="mt-3 rounded bg-amber-50 p-2 text-xs text-amber-900 ring-1 ring-inset ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-900/60">
                <p className="font-medium">Mismatch warnings</p>
                <ul className="mt-1 list-inside list-disc space-y-0.5">
                  {item.extraction.mismatchWarnings.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {item.extraction.processingDetails ? (
              <p className="mt-3 text-[11px] italic text-muted-foreground">
                {item.extraction.processingDetails}
              </p>
            ) : null}
          </div>
        ) : null}

        {item.comparisons?.length ? (
          <div className="rounded-md border border-border bg-background p-3">
            <p className="text-xs font-semibold text-foreground">Claim vs evidence</p>
            <table className="mt-2 w-full text-left text-xs">
              <thead className="text-[10px] uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="pb-1 font-medium">Field</th>
                  <th className="pb-1 font-medium">Claimed</th>
                  <th className="pb-1 font-medium">Evidence</th>
                  <th className="pb-1 text-right font-medium">Result</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {item.comparisons.map((c) => (
                  <tr key={c.field}>
                    <td className="py-1.5 text-muted-foreground">{c.field}</td>
                    <td className="py-1.5 text-foreground">{c.claimed}</td>
                    <td className="py-1.5 text-foreground">{c.evidence}</td>
                    <td className="py-1.5 text-right">
                      <span
                        className={cn(
                          "rounded px-1.5 py-0.5 text-[10px] font-medium",
                          COMPARISON_META[c.result].className,
                        )}
                      >
                        {COMPARISON_META[c.result].label}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        {item.candidateNote ? (
          <div className="rounded-md border border-border bg-background p-3 text-xs">
            <p className="font-medium text-foreground">Candidate note</p>
            <p className="mt-1 text-muted-foreground">{item.candidateNote}</p>
          </div>
        ) : null}
      </div>
    </>
  );
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border bg-background p-2">
      <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 text-xs text-foreground">{value}</dd>
    </div>
  );
}
