/**
 * WorkflowActionDialog — reusable shell for every controlled decision flow.
 *
 * Provides consistent layout, eligibility summary, warnings, footer, and
 * simulated submission handling (never claims a server request occurred).
 */
import { useState, type FormEvent, type ReactNode } from "react";
import { AlertTriangle, Loader2, ShieldOff } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import type { WorkflowEligibilityResult } from "../workflow/types";

interface WorkflowActionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  consequenceSummary: string;
  eligibility: WorkflowEligibilityResult;
  destructive?: boolean;
  submitLabel: string;
  onSubmit: () => Promise<void> | void;
  onCancel?: () => void;
  submitDisabled?: boolean;
  children: ReactNode;
  /** Optional right-column extra: candidate-facing preview, contact readiness, etc. */
  aside?: ReactNode;
  candidateImpactNote?: string;
}

export function WorkflowActionDialog({
  open,
  onOpenChange,
  title,
  consequenceSummary,
  eligibility,
  destructive,
  submitLabel,
  onSubmit,
  onCancel,
  submitDisabled,
  children,
  aside,
  candidateImpactNote,
}: WorkflowActionDialogProps) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (submitting) return;
    setError(null);
    setSubmitting(true);
    try {
      await onSubmit();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed.");
    } finally {
      setSubmitting(false);
    }
  }

  const permissionBlocked = eligibility.blockingReasons.some((r) =>
    r.toLowerCase().includes("permission"),
  );

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (submitting) return;
        onOpenChange(o);
        if (!o) onCancel?.();
      }}
    >
      <DialogContent
        className={cn(
          "flex max-h-[90vh] max-w-2xl flex-col overflow-hidden p-0 sm:max-w-3xl",
          destructive && "border-destructive/40",
        )}
        onEscapeKeyDown={(e) => submitting && e.preventDefault()}
        onInteractOutside={(e) => submitting && e.preventDefault()}
      >
        <DialogHeader className="border-b border-border px-5 pb-3 pt-5">
          <DialogTitle className={cn("text-base font-semibold", destructive && "text-destructive")}>
            {title}
          </DialogTitle>
          <DialogDescription className="text-xs">{consequenceSummary}</DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <div className="grid min-h-0 flex-1 grid-cols-1 divide-y divide-border overflow-hidden md:grid-cols-[minmax(0,1fr)_260px] md:divide-x md:divide-y-0">
            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
              {/* Blocking reasons */}
              {eligibility.blockingReasons.length > 0 && (
                <div
                  role="alert"
                  className="mb-4 rounded-md border border-destructive/30 bg-destructive/5 p-3"
                >
                  <p className="flex items-center gap-1.5 text-xs font-medium text-destructive">
                    {permissionBlocked ? (
                      <ShieldOff aria-hidden className="size-3.5" />
                    ) : (
                      <AlertTriangle aria-hidden className="size-3.5" />
                    )}
                    {permissionBlocked ? "Permission required" : "This action is currently blocked"}
                  </p>
                  <ul className="mt-1.5 list-inside list-disc space-y-0.5 text-[11px] text-destructive">
                    {eligibility.blockingReasons.map((r) => (
                      <li key={r}>{r}</li>
                    ))}
                  </ul>
                </div>
              )}
              {eligibility.warnings.length > 0 && (
                <div className="mb-4 rounded-md border border-amber-300 bg-amber-50 p-3 dark:border-amber-800 dark:bg-amber-950/40">
                  <p className="flex items-center gap-1.5 text-xs font-medium text-amber-900 dark:text-amber-200">
                    <AlertTriangle aria-hidden className="size-3.5" />
                    Review before confirming
                  </p>
                  <ul className="mt-1.5 list-inside list-disc space-y-0.5 text-[11px] text-amber-900 dark:text-amber-200">
                    {eligibility.warnings.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                </div>
              )}

              {children}

              {error ? (
                <p role="alert" className="mt-3 text-xs text-destructive">
                  {error}
                </p>
              ) : null}
            </div>
            {aside ? (
              <aside className="min-h-0 overflow-y-auto bg-muted/30 px-4 py-4 text-xs md:max-w-[260px]">
                {aside}
              </aside>
            ) : null}
          </div>

          {candidateImpactNote ? (
            <p className="border-t border-border bg-muted/30 px-5 py-2 text-[11px] italic text-muted-foreground">
              {candidateImpactNote}
            </p>
          ) : null}

          <DialogFooter className="gap-2 border-t border-border bg-background px-5 py-3 sm:justify-between">
            <p className="hidden text-[11px] text-muted-foreground sm:block">
              Session-only change. Not persisted to the backend.
            </p>
            <div className="flex flex-wrap justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  if (submitting) return;
                  onOpenChange(false);
                  onCancel?.();
                }}
                disabled={submitting}
                className="inline-flex h-8 items-center rounded-md border border-border bg-background px-3 text-xs font-medium text-foreground hover:bg-accent disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={submitting || !eligibility.allowed || submitDisabled === true}
                className={cn(
                  "inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-xs font-medium disabled:opacity-50",
                  destructive
                    ? "bg-destructive text-destructive-foreground hover:bg-destructive/90"
                    : "bg-foreground text-background hover:bg-foreground/90",
                )}
              >
                {submitting ? (
                  <>
                    <Loader2 aria-hidden className="size-3 animate-spin" />
                    Recording…
                  </>
                ) : (
                  submitLabel
                )}
              </button>
            </div>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Small input helpers used inside every workflow dialog. */
export function Field({
  label,
  htmlFor,
  error,
  hint,
  required,
  children,
}: {
  label: string;
  htmlFor?: string;
  error?: string;
  hint?: string;
  required?: boolean;
  children: ReactNode;
}) {
  const hintId = hint ? `${htmlFor ?? label}-hint` : undefined;
  const errorId = error ? `${htmlFor ?? label}-err` : undefined;
  return (
    <div className="mb-3">
      <label
        htmlFor={htmlFor}
        className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-muted-foreground"
      >
        {label}
        {required ? <span className="ml-0.5 text-destructive">*</span> : null}
      </label>
      {children}
      {hint ? (
        <p id={hintId} className="mt-1 text-[11px] text-muted-foreground">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} role="alert" className="mt-1 text-[11px] text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}
