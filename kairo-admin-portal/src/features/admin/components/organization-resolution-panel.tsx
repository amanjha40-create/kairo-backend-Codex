/**
 * OrganizationResolutionPanel — Registry-backed org resolution UI for
 * the case workspace. All actions are session-only and route through
 * useOutreachSession so timeline + readiness stay in sync.
 */
import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { toast } from "sonner";
import { AlertTriangle, Building2, CheckCircle2, HelpCircle, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { WorkspaceSection } from "./workspace-section";
import type { VerificationCaseDetail, OrganizationSuggestion } from "@/features/admin/data/cases";
import { ORGANIZATION_STATUS_LABEL } from "@/features/admin/data/verifications";
import type { UseOutreachSessionResult } from "@/features/admin/workflow/use-outreach-session";

interface Props {
  detail: VerificationCaseDetail;
  outreach: UseOutreachSessionResult;
}

export function OrganizationResolutionPanel({ detail, outreach }: Props) {
  const { organization } = detail;
  const [mode, setMode] = useState<"none" | "propose" | "flag">("none");

  const resolved = outreach.orgResolvedInSession;
  const acceptedId = outreach.acceptedOrgMatchId;

  function handleAccept(s: OrganizationSuggestion) {
    outreach.acceptOrgMatch(s.id, s.name);
    toast(`Accepted match: ${s.name}`, { description: "Session-only." });
  }
  function handleReject(s: OrganizationSuggestion) {
    outreach.rejectOrgSuggestion(s.id, s.name);
    toast(`Rejected match: ${s.name}`, { description: "Session-only." });
  }
  function handleUncertain(s: OrganizationSuggestion) {
    outreach.markOrgUncertain(s.id, s.name);
    toast(`Marked uncertain: ${s.name}`, { description: "Session-only." });
  }

  return (
    <WorkspaceSection
      id="organization"
      title="Organization resolution"
      description={ORGANIZATION_STATUS_LABEL[detail.summary.organizationStatus]}
      action={
        <span
          className={cn(
            "inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-medium",
            resolved
              ? "bg-emerald-50 text-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200"
              : "bg-amber-50 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200",
          )}
        >
          {resolved ? "Resolved" : "Unresolved"}
        </span>
      }
    >
      <div className="space-y-3 text-xs">
        <div>
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
            Candidate entered
          </p>
          <p className="text-foreground">{organization.candidateEntered}</p>
        </div>
        {organization.matched ? (
          <div
            className={cn(
              "rounded-md border p-2.5",
              acceptedId === organization.matched.id
                ? "border-emerald-300 bg-emerald-50/40 dark:border-emerald-800 dark:bg-emerald-950/30"
                : "border-border bg-background",
            )}
          >
            <p className="flex items-center gap-1.5 text-xs font-medium text-foreground">
              <Building2 aria-hidden className="size-3" />
              {organization.matched.canonicalName}
            </p>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              {organization.matched.orgType} · {organization.matched.country}
              {organization.matched.domain ? ` · ${organization.matched.domain}` : ""}
            </p>
            <p className="mt-1 text-[11px] text-muted-foreground">
              Match confidence {(organization.matched.matchConfidence * 100).toFixed(0)}% —{" "}
              {organization.matched.matchReason}
            </p>
          </div>
        ) : (
          <p className="text-[11px] text-muted-foreground">No canonical organization matched.</p>
        )}

        {organization.duplicateWarning ? (
          <div className="rounded bg-amber-50 p-2 text-[11px] text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
            <AlertTriangle aria-hidden className="mr-1 inline size-3" />
            {organization.duplicateWarning}
          </div>
        ) : null}

        {organization.suggestions.length > 0 ? (
          <div>
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
              Suggested matches
            </p>
            <ul className="mt-1 space-y-1.5">
              {organization.suggestions.map((s) => {
                const isAccepted = acceptedId === s.id;
                const isRejected = outreach.rejectedSuggestionIds.has(s.id);
                const isUncertain = outreach.uncertainSuggestionIds.has(s.id);
                return (
                  <li
                    key={s.id}
                    className={cn(
                      "rounded-md border p-2",
                      isAccepted &&
                        "border-emerald-300 bg-emerald-50/40 dark:border-emerald-800 dark:bg-emerald-950/30",
                      isRejected &&
                        "border-rose-300 bg-rose-50/40 opacity-70 dark:border-rose-900 dark:bg-rose-950/30",
                      isUncertain &&
                        !isAccepted &&
                        !isRejected &&
                        "border-amber-300 bg-amber-50/40 dark:border-amber-800 dark:bg-amber-950/30",
                      !isAccepted && !isRejected && !isUncertain && "border-border bg-background",
                    )}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-xs font-medium text-foreground">{s.name}</p>
                        <p className="text-[11px] text-muted-foreground">
                          {(s.confidence * 100).toFixed(0)}% · {s.reason}
                        </p>
                        <div className="mt-1 flex flex-wrap gap-1">
                          {isAccepted ? <Chip tone="emerald">Accepted (session)</Chip> : null}
                          {isRejected ? <Chip tone="rose">Rejected (session)</Chip> : null}
                          {isUncertain && !isAccepted && !isRejected ? (
                            <Chip tone="amber">Uncertain (session)</Chip>
                          ) : null}
                        </div>
                      </div>
                      <div className="flex shrink-0 flex-col items-end gap-1">
                        <button
                          type="button"
                          onClick={() => handleAccept(s)}
                          disabled={isAccepted}
                          className="inline-flex h-6 items-center gap-1 rounded border border-border bg-background px-1.5 text-[10px] text-foreground hover:bg-accent disabled:opacity-50"
                        >
                          <CheckCircle2 aria-hidden className="size-3" />
                          Accept
                        </button>
                        <button
                          type="button"
                          onClick={() => handleReject(s)}
                          disabled={isRejected}
                          className="inline-flex h-6 items-center gap-1 rounded border border-border bg-background px-1.5 text-[10px] text-foreground hover:bg-accent disabled:opacity-50"
                        >
                          <X aria-hidden className="size-3" />
                          Reject
                        </button>
                        <button
                          type="button"
                          onClick={() => handleUncertain(s)}
                          disabled={isUncertain}
                          className="inline-flex h-6 items-center gap-1 rounded border border-border bg-background px-1.5 text-[10px] text-foreground hover:bg-accent disabled:opacity-50"
                        >
                          <HelpCircle aria-hidden className="size-3" />
                          Uncertain
                        </button>
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null}

        {outreach.proposedOrgs.length > 0 ? (
          <div>
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
              Proposed Registry organizations (session)
            </p>
            <ul className="mt-1 space-y-1">
              {outreach.proposedOrgs.map((p) => (
                <li
                  key={p.id}
                  className="rounded-md border border-sky-300 bg-sky-50/40 p-2 text-[11px] dark:border-sky-800 dark:bg-sky-950/30"
                >
                  <p className="font-medium text-foreground">{p.name}</p>
                  <p className="text-muted-foreground">
                    {p.domain ? `${p.domain} · ` : ""}
                    {p.country ?? ""}
                  </p>
                  <p className="text-muted-foreground">Reason: {p.reason}</p>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {outreach.duplicateFlagNotes.length > 0 ? (
          <div className="rounded bg-amber-50 p-2 text-[11px] text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
            <p className="font-medium">Duplicate flags (session)</p>
            <ul className="mt-0.5 list-inside list-disc">
              {outreach.duplicateFlagNotes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          </div>
        ) : null}

        {mode === "propose" ? (
          <InlineForm
            label="Propose new Registry organization"
            fields={[
              { key: "name", label: "Organization name", required: true },
              { key: "domain", label: "Domain (optional)" },
              { key: "country", label: "Country (optional)" },
              { key: "reason", label: "Why is this needed?", required: true, textarea: true },
            ]}
            submitLabel="Propose (session-only)"
            onCancel={() => setMode("none")}
            onSubmit={(values) => {
              outreach.proposeNewOrg({
                name: values.name!,
                domain: values.domain || undefined,
                country: values.country || undefined,
                reason: values.reason!,
              });
              toast("Registry organization proposed", { description: "Session-only." });
              setMode("none");
            }}
          />
        ) : null}
        {mode === "flag" ? (
          <InlineForm
            label="Flag duplicate"
            fields={[
              { key: "note", label: "What looks duplicated?", required: true, textarea: true },
            ]}
            submitLabel="Flag (session-only)"
            onCancel={() => setMode("none")}
            onSubmit={(values) => {
              outreach.flagOrgDuplicate(values.note!);
              toast("Duplicate flagged", { description: "Session-only." });
              setMode("none");
            }}
          />
        ) : null}

        <div className="flex flex-wrap gap-1.5 pt-1">
          <button
            type="button"
            onClick={() => setMode(mode === "propose" ? "none" : "propose")}
            className="inline-flex h-7 items-center gap-1 rounded-md border border-border bg-background px-2 text-[11px] text-foreground hover:bg-accent"
          >
            Propose Registry organization
          </button>
          <button
            type="button"
            onClick={() => setMode(mode === "flag" ? "none" : "flag")}
            className="inline-flex h-7 items-center gap-1 rounded-md border border-border bg-background px-2 text-[11px] text-foreground hover:bg-accent"
          >
            Flag duplicate
          </button>
          <Link
            to="/admin/registry"
            className="inline-flex h-7 items-center gap-1 rounded-md border border-border bg-background px-2 text-[11px] text-foreground hover:bg-accent"
          >
            Search Registry
          </Link>
        </div>
      </div>
    </WorkspaceSection>
  );
}

function Chip({
  tone,
  children,
}: {
  tone: "emerald" | "rose" | "amber";
  children: React.ReactNode;
}) {
  const cls = {
    emerald: "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-200",
    rose: "bg-rose-100 text-rose-900 dark:bg-rose-900/40 dark:text-rose-200",
    amber: "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200",
  }[tone];
  return (
    <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium", cls)}>{children}</span>
  );
}

interface InlineFormField {
  key: string;
  label: string;
  required?: boolean;
  textarea?: boolean;
}
function InlineForm({
  label,
  fields,
  submitLabel,
  onCancel,
  onSubmit,
}: {
  label: string;
  fields: InlineFormField[];
  submitLabel: string;
  onCancel: () => void;
  onSubmit: (values: Record<string, string>) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const missing = fields.some((f) => f.required && !values[f.key]?.trim());
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (missing) return;
        onSubmit(values);
      }}
      className="space-y-2 rounded-md border border-sky-300 bg-sky-50/30 p-3 dark:border-sky-800 dark:bg-sky-950/20"
    >
      <p className="text-[11px] font-semibold text-foreground">{label}</p>
      {fields.map((f) => (
        <div key={f.key}>
          <label className="block text-[11px] text-muted-foreground">
            {f.label}
            {f.required ? " *" : ""}
          </label>
          {f.textarea ? (
            <textarea
              value={values[f.key] ?? ""}
              onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
              rows={2}
              className="mt-0.5 w-full rounded border border-border bg-background p-1.5 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            />
          ) : (
            <input
              type="text"
              value={values[f.key] ?? ""}
              onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
              className="mt-0.5 h-7 w-full rounded border border-border bg-background px-2 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            />
          )}
        </div>
      ))}
      <div className="flex justify-end gap-1.5">
        <button
          type="button"
          onClick={onCancel}
          className="inline-flex h-7 items-center rounded border border-border bg-background px-2 text-[11px] text-foreground hover:bg-accent"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={missing}
          className="inline-flex h-7 items-center rounded bg-foreground px-2 text-[11px] font-medium text-background hover:bg-foreground/90 disabled:opacity-50"
        >
          {submitLabel}
        </button>
      </div>
    </form>
  );
}
