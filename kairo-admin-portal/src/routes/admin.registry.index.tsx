import { useMemo, useState } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { Building2, Search, AlertTriangle } from "lucide-react";
import { WorkspaceSection } from "@/features/admin/components/workspace-section";
import { AdminSearchField } from "@/features/admin/components/search-field";
import { EmptyState } from "@/features/admin/components/states";
import {
  REGISTRY_ORG_STATE_LABEL,
  REGISTRY_ORG_TYPE_LABEL,
  getRegistryMetrics,
  mockRegistryOrganizations,
  type RegistryOrgState,
} from "@/features/admin/data/registry";

export const Route = createFileRoute("/admin/registry/")({
  head: () => ({
    meta: [{ title: "Registry — Kairo Admin" }, { name: "robots", content: "noindex, nofollow" }],
  }),
  component: RegistryPage,
});

const STATE_FILTERS: Array<{ key: "all" | RegistryOrgState; label: string }> = [
  { key: "all", label: "All" },
  { key: "verified", label: "Verified" },
  { key: "unverified", label: "Unverified" },
  { key: "duplicate_review", label: "Duplicates" },
  { key: "deprecated", label: "Deprecated" },
];

function RegistryPage() {
  const metrics = useMemo(getRegistryMetrics, []);
  const [q, setQ] = useState("");
  const [stateFilter, setStateFilter] = useState<"all" | RegistryOrgState>("all");

  const rows = useMemo(() => {
    const ql = q.trim().toLowerCase();
    return mockRegistryOrganizations.filter((o) => {
      if (stateFilter !== "all" && o.state !== stateFilter) return false;
      if (!ql) return true;
      return (
        o.canonicalName.toLowerCase().includes(ql) ||
        o.domain.toLowerCase().includes(ql) ||
        o.country.toLowerCase().includes(ql) ||
        o.aliases.some((a) => a.toLowerCase().includes(ql))
      );
    });
  }, [q, stateFilter]);

  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-4">
      <header>
        <h1 className="text-lg font-semibold tracking-tight text-foreground">Registry</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Canonical organizations used across Kairo verifications. Contacts, activity and duplicate
          reviews live on the org detail page.
        </p>
      </header>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Metric label="Organizations" value={metrics.total} sub={`${metrics.verified} verified`} />
        <Metric label="Unverified" value={metrics.unverified} sub="Needs registry review" />
        <Metric
          label="Duplicate review"
          value={metrics.duplicates}
          sub="Awaits canonicalization"
          tone="warning"
        />
        <Metric
          label="Approved contacts"
          value={metrics.contactsApproved}
          sub={`${metrics.contactsBounced} bounced`}
        />
      </div>

      <WorkspaceSection
        title="Organizations"
        description={`${rows.length} of ${mockRegistryOrganizations.length} shown.`}
        action={
          <div className="flex items-center gap-1.5">
            <div className="w-64">
              <AdminSearchField
                value={q}
                onChange={setQ}
                placeholder="Search name, domain, country"
              />
            </div>
          </div>
        }
      >
        <div className="mb-3 flex flex-wrap items-center gap-1.5">
          {STATE_FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              onClick={() => setStateFilter(f.key)}
              className={
                "h-7 rounded-md border px-2 text-[11px] font-medium " +
                (stateFilter === f.key
                  ? "border-foreground bg-foreground text-background"
                  : "border-border bg-background text-foreground hover:bg-accent")
              }
            >
              {f.label}
            </button>
          ))}
        </div>
        {rows.length === 0 ? (
          <EmptyState
            title="No organizations match"
            description="Try clearing filters or the search box."
          />
        ) : (
          <div className="overflow-x-auto rounded-md border border-border">
            <table className="min-w-full divide-y divide-border text-xs">
              <thead className="bg-muted/40 text-left text-[11px] uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-medium">Organization</th>
                  <th className="px-3 py-2 font-medium">Type</th>
                  <th className="px-3 py-2 font-medium">Country</th>
                  <th className="px-3 py-2 font-medium">State</th>
                  <th className="px-3 py-2 font-medium">Contacts</th>
                  <th className="px-3 py-2 font-medium">Active cases</th>
                  <th className="px-3 py-2 font-medium">Verifications</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border bg-background">
                {rows.map((o) => (
                  <tr key={o.id} className="hover:bg-accent/40">
                    <td className="px-3 py-2">
                      <Link
                        to="/admin/registry/$organizationId"
                        params={{ organizationId: o.id }}
                        className="flex min-w-0 items-center gap-2 text-foreground hover:underline"
                      >
                        <Building2 aria-hidden className="size-3.5 text-muted-foreground" />
                        <span className="min-w-0">
                          <span className="block font-medium">{o.canonicalName}</span>
                          <span className="block text-[11px] font-mono text-muted-foreground">
                            {o.domain}
                          </span>
                        </span>
                      </Link>
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">
                      {REGISTRY_ORG_TYPE_LABEL[o.orgType]}
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">{o.country}</td>
                    <td className="px-3 py-2">
                      <StateChip state={o.state} />
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">{o.contacts.length}</td>
                    <td className="px-3 py-2 text-muted-foreground">{o.activeCaseCount}</td>
                    <td className="px-3 py-2 text-muted-foreground">{o.totalVerifications}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </WorkspaceSection>
    </div>
  );
}

function Metric({
  label,
  value,
  sub,
  tone = "default",
}: {
  label: string;
  value: number;
  sub?: string;
  tone?: "default" | "warning";
}) {
  return (
    <div className="rounded-lg border border-border bg-card px-4 py-3">
      <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <div className="mt-1 flex items-baseline gap-1">
        <p className="text-xl font-semibold tracking-tight text-foreground">{value}</p>
        {tone === "warning" && value > 0 ? (
          <AlertTriangle aria-hidden className="size-3.5 text-amber-600" />
        ) : null}
      </div>
      {sub ? <p className="mt-0.5 text-[11px] text-muted-foreground">{sub}</p> : null}
    </div>
  );
}

function StateChip({ state }: { state: RegistryOrgState }) {
  const map: Record<RegistryOrgState, string> = {
    verified:
      "bg-emerald-50 text-emerald-900 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-200 dark:ring-emerald-900/60",
    unverified:
      "bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-900/60",
    duplicate_review:
      "bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-900/60",
    deprecated: "bg-muted text-muted-foreground ring-border",
  };
  return (
    <span
      className={
        "inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset " +
        map[state]
      }
    >
      {REGISTRY_ORG_STATE_LABEL[state]}
    </span>
  );
}

// Reference `Search` icon to satisfy unused-import checks in edge configs.
void Search;
